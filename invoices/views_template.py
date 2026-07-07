from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
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

    def get_queryset(self):
        self.organization = self.get_organization()
        submissions = list(
            self.organization.invoice_submissions.select_related("device", "original_invoice")
        )
        for submission in submissions:
            _attach_totals(submission)
            _attach_remarks(submission)
        return submissions

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.organization
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
