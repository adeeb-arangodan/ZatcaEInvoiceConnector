from decimal import Decimal
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, ListView

from organization.mixins import OrgScopedMixin

from .models import InvoiceSubmission
from .pipeline import deliver_to_zatca
from .services import DuplicateReturnNumberError, create_return_credit_note
from .xml_builder import _compute_totals


class InvoiceListView(LoginRequiredMixin, OrgScopedMixin, ListView):
    context_object_name = "invoices"
    template_name = "invoices/invoice_list.html"
    paginate_by = 25

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

    def _get_summary_scope(self):
        scope = self.request.GET.get("summary_scope", "page")
        return scope if scope in ("page", "all") else "page"

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


def _sum_totals(submissions):
    fields = ["total_amount", "discount_amount", "net_before_tax", "tax_amount", "net_with_tax"]
    sums = {field: Decimal("0") for field in fields}
    count = 0
    for submission in submissions:
        count += 1
        for field in fields:
            value = getattr(submission, field)
            if value is not None:
                sums[field] += value
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

        if credit_note.status == "submitted":
            messages.success(
                self.request, f"Credit note created and submitted to ZATCA (ICV {credit_note.icv})."
            )
        else:
            messages.error(
                self.request, "Credit note created locally but ZATCA submission failed. See status for details."
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
