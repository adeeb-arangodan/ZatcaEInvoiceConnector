import io
import zipfile
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views import View
from django.views.generic import DeleteView, DetailView, FormView, ListView

from organization.mixins import OrgScopedMixin

from .exports import build_invoice_workbook
from .models import InvoiceSubmission, InvoiceSubmissionFailure
from .pipeline import InvoiceSubmissionRejected, deliver_to_zatca, process_invoice_submission
from .qr import generate_qr_image_data_uri
from .serializers import InvoiceSubmissionSerializer
from .services import (
    DuplicateReturnNumberError,
    create_custom_return_credit_note,
    create_return_credit_note,
)
from .xml_builder import VAT_RATE, _compute_totals


class InvoiceFilterMixin:
    """Shared GET-param filtering for the invoice list and export views.

    Requires OrgScopedMixin earlier in the MRO for get_organization().
    """

    def _get_filters(self):
        if hasattr(self, "_filters"):
            return self._filters

        params = self.request.GET
        if params:
            issue_date_from = params.get("issue_date_from", "").strip()
            issue_date_to = params.get("issue_date_to", "").strip()
        else:
            # Cold navigation (e.g. from the dashboard link) with no query
            # string at all — default to "today" rather than dumping the
            # organization's entire invoice history into one query/page.
            today = timezone.localdate().isoformat()
            issue_date_from = issue_date_to = today

        self._filters = {
            "invoice_number": params.get("invoice_number", "").strip(),
            "customer_name": params.get("customer_name", "").strip(),
            "icv": params.get("icv", "").strip(),
            "document_type": params.get("document_type", "").strip(),
            "status": params.get("status", "").strip(),
            "issue_date_from": issue_date_from,
            "issue_date_to": issue_date_to,
        }
        return self._filters

    def get_queryset(self):
        self.organization = self.get_organization()
        queryset = self.organization.invoice_submissions.select_related("device", "original_invoice")
        filters = self._get_filters()

        if filters["invoice_number"]:
            queryset = queryset.filter(invoice_number__icontains=filters["invoice_number"])
        if filters["icv"]:
            queryset = queryset.filter(icv=filters["icv"])
        if filters["document_type"]:
            queryset = queryset.filter(document_type=filters["document_type"])
        if filters["status"]:
            queryset = queryset.filter(status=filters["status"])
        if filters["issue_date_from"]:
            queryset = queryset.filter(payload__issue_date__gte=filters["issue_date_from"])
        if filters["issue_date_to"]:
            queryset = queryset.filter(payload__issue_date__lte=filters["issue_date_to"])
        if filters["customer_name"]:
            queryset = queryset.filter(payload__customer_name__icontains=filters["customer_name"])

        return queryset


class InvoiceListView(LoginRequiredMixin, OrgScopedMixin, InvoiceFilterMixin, ListView):
    context_object_name = "invoices"
    template_name = "invoices/invoice_list.html"
    paginate_by = 25

    def _get_summary_scope(self):
        scope = self.request.GET.get("summary_scope", "page")
        return scope if scope in ("page", "all") else "page"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.organization
        for submission in context[self.context_object_name]:
            _attach_totals(submission)
            _attach_remarks(submission)

        filters = self._get_filters()
        summary_scope = self._get_summary_scope()
        if summary_scope == "all":
            for submission in self.object_list:
                _attach_totals(submission)
            summary = _sum_totals(self.object_list)
        else:
            summary = _sum_totals(context[self.context_object_name])

        context["filters"] = filters
        context["document_type_choices"] = InvoiceSubmission.DOCUMENT_TYPE_CHOICES
        context["status_choices"] = InvoiceSubmission.STATUS_CHOICES
        context["summary"] = summary
        context["summary_scope"] = summary_scope

        filter_qs = urlencode({k: v for k, v in filters.items() if v})
        base = f"?{filter_qs}&" if filter_qs else "?"
        context["summary_toggle_urls"] = {
            "page": f"{base}summary_scope=page",
            "all": f"{base}summary_scope=all",
        }
        context["querystring"] = urlencode({**{k: v for k, v in filters.items() if v}, "summary_scope": summary_scope})
        export_base_url = reverse("organization:invoice-export", args=[self.organization.pk])
        context["export_url"] = f"{export_base_url}?{filter_qs}" if filter_qs else export_base_url
        xml_zip_base_url = reverse("organization:invoice-xml-zip-export", args=[self.organization.pk])
        context["xml_zip_export_url"] = f"{xml_zip_base_url}?{filter_qs}" if filter_qs else xml_zip_base_url
        return context


class InvoiceExportView(LoginRequiredMixin, OrgScopedMixin, InvoiceFilterMixin, View):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        self.organization = self.get_organization()
        submissions = list(self.get_queryset())
        for submission in submissions:
            _attach_totals(submission)
            _attach_remarks(submission)
        summary = _sum_totals(submissions)
        workbook = build_invoice_workbook(submissions, summary)

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        filename = f"invoices_{slugify(self.organization.name)}_{timezone.localdate().isoformat()}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        workbook.save(response)
        return response


def _xml_filename(submission):
    return f"{submission.icv}_{slugify(submission.payload.get('invoice_number', ''))}.xml"


class InvoiceXmlView(LoginRequiredMixin, OrgScopedMixin, View):
    http_method_names = ["get"]
    download = False

    def get(self, request, *args, **kwargs):
        submission = get_object_or_404(
            InvoiceSubmission, pk=kwargs["invoice_pk"], organization_id=kwargs["pk"],
        )
        if not submission.xml_document:
            messages.error(request, "No XML is available yet for this invoice.")
            return redirect("organization:invoice-detail", pk=kwargs["pk"], invoice_pk=kwargs["invoice_pk"])

        response = HttpResponse(submission.xml_document, content_type="application/xml")
        disposition = "attachment" if self.download else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{_xml_filename(submission)}"'
        return response


class InvoiceXmlDownloadView(InvoiceXmlView):
    download = True


class InvoiceXmlZipExportView(LoginRequiredMixin, OrgScopedMixin, InvoiceFilterMixin, View):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        self.organization = self.get_organization()
        submissions = self.get_queryset()

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for submission in submissions:
                if not submission.xml_document:
                    continue
                zf.writestr(_xml_filename(submission), submission.xml_document)

        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        filename = f"invoices_xml_{slugify(self.organization.name)}_{timezone.localdate().isoformat()}.zip"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class InvoiceDetailView(LoginRequiredMixin, OrgScopedMixin, DetailView):
    model = InvoiceSubmission
    pk_url_kwarg = "invoice_pk"
    context_object_name = "invoice"
    template_name = "invoices/invoice_detail.html"

    def get_queryset(self):
        # organization_id filter (not just OrgScopedMixin's ownership check
        # on the URL's org pk) is what actually stops viewing another org's
        # invoice by guessing invoice_pk.
        return InvoiceSubmission.objects.filter(organization_id=self.kwargs["pk"]).select_related(
            "organization", "device", "original_invoice",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.get_organization()
        _attach_totals(self.object)
        _attach_remarks(self.object)
        context["line_items"] = _line_items(self.object)
        context["qr_image"] = (
            generate_qr_image_data_uri(self.object.qr_code_data) if self.object.qr_code_data else None
        )
        return context


def _attach_totals(submission):
    items = submission.payload.get("items", [])
    if not items:
        submission.total_amount = None
        submission.discount_amount = None
        submission.net_before_tax = None
        submission.tax_amount = None
        submission.net_with_tax = None
        return
    totals = _compute_totals(
        items,
        submission.payload.get("doc_level_discount_vat", 0),
        submission.payload.get("doc_level_discount_novat", 0),
        submission.payload.get("advance_paid", 0),
    )
    submission.total_amount = totals["line_extension"]
    submission.discount_amount = totals["discount_total"]
    submission.net_before_tax = totals["tax_exclusive"]
    submission.tax_amount = totals["vat_total"]
    submission.net_with_tax = totals["tax_inclusive"]


def _line_items(submission):
    line_items = []
    for item in submission.payload.get("items", []):
        qty = Decimal(str(item["qty"]))
        price = Decimal(str(item["price"]))
        line_amount = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line_vat = (line_amount * VAT_RATE if item["vat_type"] == "S" else Decimal("0")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        line_items.append({
            "slno": item["slno"],
            "code": item["code"],
            "name": item["name"],
            "qty": qty,
            "price": price,
            "vat_type": item["vat_type"],
            "line_amount": line_amount,
            "line_vat": line_vat,
            "line_total": line_amount + line_vat,
        })
    return line_items


# Per-row totals are always positive (matching the UBL/ZATCA XML convention —
# a credit note's "credit" nature is conveyed by its document type code, not
# a negative amount). The summary is a business-reporting aggregate, not part
# of ZATCA compliance, so it nets credit notes against invoices/debit notes
# the way a sales ledger would: invoices + debit notes (charges) - credit
# notes (returns).
_DOCUMENT_TYPE_SUMMARY_SIGN = {
    InvoiceSubmission.DOCUMENT_TYPE_INVOICE: 1,
    InvoiceSubmission.DOCUMENT_TYPE_DEBIT_NOTE: 1,
    InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE: -1,
}


def _sum_totals(submissions):
    fields = ["total_amount", "discount_amount", "net_before_tax", "tax_amount", "net_with_tax"]
    sums = {field: Decimal("0") for field in fields}
    count = 0
    for submission in submissions:
        count += 1
        sign = _DOCUMENT_TYPE_SUMMARY_SIGN.get(submission.document_type, 1)
        for field in fields:
            value = getattr(submission, field)
            if value is not None:
                sums[field] += sign * value
    sums["count"] = count
    return sums


def _attach_remarks(submission):
    if submission.document_type == InvoiceSubmission.DOCUMENT_TYPE_INVOICE:
        submission.remarks = submission.payload.get("notes") or ""
        return

    if submission.original_invoice_id and submission.original_invoice:
        original_number = submission.original_invoice.payload.get("invoice_number", "")
    else:
        original_number = submission.payload.get("billing_reference", "")
    submission.remarks = f"Issued for invoice {original_number}" if original_number else ""


class ReturnInvoiceForm(forms.Form):
    system_return_number = forms.CharField(required=False, label="System return number (optional)")
    reason = forms.CharField(required=False, widget=forms.Textarea, label="Reason (optional)")


class ReturnInvoiceFormView(LoginRequiredMixin, OrgScopedMixin, FormView):
    form_class = ReturnInvoiceForm
    template_name = "invoices/return_invoice_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.invoice = get_object_or_404(
            InvoiceSubmission,
            pk=self.kwargs["invoice_pk"],
            organization_id=self.kwargs["pk"],
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.get_organization()
        context["invoice"] = self.invoice
        return context

    def form_valid(self, form):
        organization = self.get_organization()
        device = self.invoice.device
        if not device.csid_response or "binarySecurityToken" not in device.csid_response:
            messages.error(self.request, "Originating device has no valid compliance CSID.")
            return redirect("organization:invoice-list", pk=organization.pk)

        try:
            credit_note = create_return_credit_note(
                organization=organization,
                device=device,
                original_invoice=self.invoice,
                system_return_number=form.cleaned_data["system_return_number"],
                reason=form.cleaned_data["reason"],
            )
        except DuplicateReturnNumberError as exc:
            form.add_error("system_return_number", str(exc))
            return self.form_invalid(form)
        except InvoiceSubmissionRejected as exc:
            messages.error(
                self.request,
                f"ZATCA rejected this credit note: {exc.failure.zatca_response}. "
                "Correct the payload and resubmit from Failed Submissions.",
            )
            return redirect("organization:invoice-list", pk=organization.pk)

        messages.success(
            self.request, f"Credit note created and submitted to ZATCA (ICV {credit_note.icv})."
        )
        return redirect("organization:invoice-list", pk=organization.pk)


class CustomReturnItemForm(forms.Form):
    slno = forms.IntegerField(widget=forms.HiddenInput)
    code = forms.CharField(widget=forms.HiddenInput)
    name = forms.CharField(widget=forms.HiddenInput)
    vat_type = forms.CharField(widget=forms.HiddenInput)
    include = forms.BooleanField(required=False, initial=True, label="Include")
    qty = forms.DecimalField(max_digits=15, decimal_places=4, label="Qty")
    price = forms.DecimalField(max_digits=15, decimal_places=4, label="Unit Price")


CustomReturnItemFormSet = forms.formset_factory(CustomReturnItemForm, extra=0)


class CustomReturnInvoiceForm(forms.Form):
    issue_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    system_return_number = forms.CharField(required=False, label="System return number (optional)")
    reason = forms.CharField(required=False, widget=forms.Textarea, label="Reason (optional)")


class CustomReturnInvoiceFormView(LoginRequiredMixin, OrgScopedMixin, View):
    template_name = "invoices/return_invoice_custom_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.invoice = get_object_or_404(
            InvoiceSubmission,
            pk=self.kwargs["invoice_pk"],
            organization_id=self.kwargs["pk"],
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
        )
        return super().dispatch(request, *args, **kwargs)

    def _initial_items(self):
        return [
            {
                "slno": item["slno"],
                "code": item["code"],
                "name": item["name"],
                "vat_type": item["vat_type"],
                "include": True,
                "qty": item["qty"],
                "price": item["price"],
            }
            for item in self.invoice.payload.get("items", [])
        ]

    def _render(self, request, form, formset, status=200):
        return render(
            request,
            self.template_name,
            {
                "organization": self.get_organization(),
                "invoice": self.invoice,
                "form": form,
                "formset": formset,
            },
            status=status,
        )

    def get(self, request, *args, **kwargs):
        form = CustomReturnInvoiceForm(initial={"issue_date": timezone.localdate()})
        formset = CustomReturnItemFormSet(initial=self._initial_items())
        return self._render(request, form, formset)

    def post(self, request, *args, **kwargs):
        organization = self.get_organization()
        form = CustomReturnInvoiceForm(request.POST)
        formset = CustomReturnItemFormSet(request.POST, initial=self._initial_items())

        if not (form.is_valid() and formset.is_valid()):
            return self._render(request, form, formset, status=422)

        selected_items = [
            {
                "slno": cleaned["slno"],
                "code": cleaned["code"],
                "name": cleaned["name"],
                "vat_type": cleaned["vat_type"],
                "qty": str(cleaned["qty"]),
                "price": str(cleaned["price"]),
                "VatExceptionReason": "",
            }
            for cleaned in formset.cleaned_data
            if cleaned.get("include")
        ]
        if not selected_items:
            form.add_error(None, "Select at least one item to return.")
            return self._render(request, form, formset, status=422)

        device = self.invoice.device
        if not device.csid_response or "binarySecurityToken" not in device.csid_response:
            messages.error(request, "Originating device has no valid compliance CSID.")
            return redirect("organization:invoice-list", pk=organization.pk)

        try:
            credit_note = create_custom_return_credit_note(
                organization=organization,
                device=device,
                original_invoice=self.invoice,
                items=selected_items,
                issue_date=form.cleaned_data["issue_date"],
                system_return_number=form.cleaned_data["system_return_number"],
                reason=form.cleaned_data["reason"],
            )
        except DuplicateReturnNumberError as exc:
            form.add_error("system_return_number", str(exc))
            return self._render(request, form, formset, status=422)
        except InvoiceSubmissionRejected as exc:
            messages.error(
                request,
                f"ZATCA rejected this credit note: {exc.failure.zatca_response}. "
                "Correct the payload and resubmit from Failed Submissions.",
            )
            return redirect("organization:invoice-list", pk=organization.pk)

        messages.success(
            request, f"Custom credit note created and submitted to ZATCA (ICV {credit_note.icv})."
        )
        return redirect("organization:invoice-list", pk=organization.pk)


class InvoiceResubmitView(LoginRequiredMixin, OrgScopedMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        organization = self.get_organization()
        submission = get_object_or_404(
            InvoiceSubmission, pk=kwargs["invoice_pk"], organization_id=kwargs["pk"],
        )

        if submission.status != InvoiceSubmission.STATUS_NOT_SUBMITTED:
            messages.error(request, "Only invoices with a 'Not Submitted' status can be resubmitted.")
            return redirect("organization:invoice-list", pk=organization.pk)

        deliver_to_zatca(submission)

        if submission.status == InvoiceSubmission.STATUS_SUBMITTED:
            messages.success(request, f"Invoice resubmitted to ZATCA successfully (ICV {submission.icv}).")
        else:
            messages.error(request, "Resubmission failed. See ZATCA status for details.")
        return redirect("organization:invoice-list", pk=organization.pk)


class FailedSubmissionListView(LoginRequiredMixin, OrgScopedMixin, ListView):
    context_object_name = "failures"
    template_name = "invoices/failed_submission_list.html"
    paginate_by = 25

    def _get_filters(self):
        if hasattr(self, "_filters"):
            return self._filters

        params = self.request.GET
        resolved_param = params.get("resolved", "").strip()

        self._filters = {
            "invoice_number": params.get("invoice_number", "").strip(),
            "customer_name": params.get("customer_name", "").strip(),
            "document_type": params.get("document_type", "").strip(),
            # Default to unresolved-only so fixed failures don't clutter the
            # page; an explicit ?resolved=... (including empty-string "all")
            # overrides that default.
            "resolved": resolved_param if "resolved" in params else "false",
        }
        return self._filters

    def get_queryset(self):
        self.organization = self.get_organization()
        queryset = self.organization.invoice_submission_failures.select_related("device")
        filters = self._get_filters()

        if filters["invoice_number"]:
            queryset = queryset.filter(invoice_number__icontains=filters["invoice_number"])
        if filters["document_type"]:
            queryset = queryset.filter(document_type=filters["document_type"])
        if filters["customer_name"]:
            queryset = queryset.filter(payload__customer_name__icontains=filters["customer_name"])
        if filters["resolved"] == "true":
            queryset = queryset.filter(resolved=True)
        elif filters["resolved"] == "false":
            queryset = queryset.filter(resolved=False)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.organization
        filters = self._get_filters()
        context["filters"] = filters
        context["document_type_choices"] = InvoiceSubmission.DOCUMENT_TYPE_CHOICES
        context["querystring"] = urlencode({k: v for k, v in filters.items() if v})
        return context


class FailedSubmissionResubmitView(LoginRequiredMixin, OrgScopedMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        organization = self.get_organization()
        failure = get_object_or_404(
            InvoiceSubmissionFailure, pk=kwargs["failure_pk"], organization_id=kwargs["pk"], resolved=False,
        )

        serializer = InvoiceSubmissionSerializer(data=failure.payload, organization=organization)
        if not serializer.is_valid():
            messages.error(request, f"Corrected payload is still invalid: {serializer.errors}")
            return redirect("organization:failed-submission-list", pk=organization.pk)

        device = serializer.get_resolved_device()

        try:
            submission = process_invoice_submission(
                organization=organization, device=device, validated_data=serializer.validated_data,
            )
        except InvoiceSubmissionRejected as exc:
            messages.error(
                request, f"ZATCA rejected the corrected submission again: {exc.failure.zatca_response}",
            )
            return redirect("organization:failed-submission-list", pk=organization.pk)

        failure.resolved = True
        failure.resolved_submission = submission
        failure.resolved_at = timezone.now()
        failure.save(update_fields=["resolved", "resolved_submission", "resolved_at"])
        messages.success(request, f"Resubmitted successfully as invoice ICV {submission.icv}.")
        return redirect("organization:failed-submission-list", pk=organization.pk)


class FailedSubmissionDeleteView(LoginRequiredMixin, OrgScopedMixin, DeleteView):
    model = InvoiceSubmissionFailure
    pk_url_kwarg = "failure_pk"
    template_name = "invoices/failed_submission_confirm_delete.html"

    def get_queryset(self):
        return InvoiceSubmissionFailure.objects.filter(organization_id=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.get_organization()
        return context

    def get_success_url(self):
        return reverse("organization:failed-submission-list", kwargs={"pk": self.kwargs["pk"]})
