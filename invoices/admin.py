from django.contrib import admin

from .models import InvoiceSubmission


@admin.register(InvoiceSubmission)
class InvoiceSubmissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'device', 'document_type', 'status', 'invoice_uuid', 'created_at')
    list_filter = ('status', 'document_type')
    search_fields = ('organization__name', 'device__asset_id')
    readonly_fields = ('payload', 'invoice_uuid', 'invoice_hash', 'qr_code_data', 'zatca_response', 'submitted_at', 'created_at', 'updated_at')
