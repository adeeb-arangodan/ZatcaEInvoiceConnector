from django.contrib import admin

from .models import CreditNote, DebitNote, Invoice

_READONLY_FIELDS = (
    'payload', 'invoice_uuid', 'invoice_hash', 'qr_code_data', 'zatca_response',
    'submitted_at', 'created_at', 'updated_at',
)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'device', 'status', 'icv', 'invoice_uuid', 'created_at')
    list_filter = ('status',)
    search_fields = ('organization__name', 'device__asset_id')
    readonly_fields = _READONLY_FIELDS


@admin.register(CreditNote)
class CreditNoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'device', 'original_invoice', 'status', 'icv', 'invoice_uuid', 'created_at')
    list_filter = ('status',)
    search_fields = ('organization__name', 'device__asset_id')
    readonly_fields = _READONLY_FIELDS


@admin.register(DebitNote)
class DebitNoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'device', 'status', 'icv', 'invoice_uuid', 'created_at')
    list_filter = ('status',)
    search_fields = ('organization__name', 'device__asset_id')
    readonly_fields = _READONLY_FIELDS
