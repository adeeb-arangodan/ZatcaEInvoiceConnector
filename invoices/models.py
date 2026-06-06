from django.db import models

from organization.models import Device, Organization


class InvoiceSubmission(models.Model):
    DOCUMENT_TYPE_INVOICE = 'invoice'
    DOCUMENT_TYPE_CREDIT_NOTE = 'credit_note'
    DOCUMENT_TYPE_DEBIT_NOTE = 'debit_note'

    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_TYPE_INVOICE, 'Invoice'),
        (DOCUMENT_TYPE_CREDIT_NOTE, 'Credit Note'),
        (DOCUMENT_TYPE_DEBIT_NOTE, 'Debit Note'),
    ]

    STATUS_RECEIVED = 'received'
    STATUS_PROCESSING = 'processing'
    STATUS_SUBMITTED = 'submitted'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_RECEIVED, 'Received'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='invoice_submissions',
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='invoice_submissions',
    )
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES)
    payload = models.JSONField(help_text="Raw request payload preserved as-is.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RECEIVED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.organization} - {self.document_type} ({self.status})"
