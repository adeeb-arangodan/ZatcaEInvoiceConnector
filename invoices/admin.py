from django.contrib import admin

from .models import InvoiceSubmission, InvoiceSubmissionFailure


@admin.register(InvoiceSubmission)
class InvoiceSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'organization', 'device', 'document_type', 'status', 'icv', 'invoice_uuid', 'created_at',
    )
    list_filter = ('status', 'document_type')
    search_fields = ('organization__name', 'device__asset_id')
    readonly_fields = (
        'payload', 'invoice_uuid', 'invoice_hash', 'qr_code_data', 'zatca_response',
        'submitted_at', 'created_at', 'updated_at',
    )


@admin.register(InvoiceSubmissionFailure)
class InvoiceSubmissionFailureAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'organization', 'device', 'document_type', 'invoice_number', 'resolved', 'created_at',
    )
    list_filter = ('resolved', 'document_type')
    search_fields = ('organization__name', 'device__asset_id', 'invoice_number')
    # payload is intentionally editable here — this is where a rejected
    # submission's data gets corrected before clicking Resubmit.
    readonly_fields = (
        'organization', 'device', 'document_type', 'zatca_response',
        'resolved', 'resolved_submission', 'created_at', 'resolved_at',
    )
