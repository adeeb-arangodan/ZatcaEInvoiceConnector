from django.contrib import admin

from .models import InvoiceSubmission


@admin.register(InvoiceSubmission)
class InvoiceSubmissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'device', 'document_type', 'status', 'created_at')
    list_filter = ('status', 'document_type')
    search_fields = ('organization__name', 'device__asset_id')
    readonly_fields = ('payload', 'created_at', 'updated_at')
