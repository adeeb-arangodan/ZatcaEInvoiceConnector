from django.db import models

from organization.models import Device, Organization


class InvoiceDocumentBase(models.Model):
    STATUS_RECEIVED = 'received'
    STATUS_PROCESSING = 'processing'
    STATUS_SUBMITTED = 'submitted'
    STATUS_NOT_SUBMITTED = 'not_submitted'

    STATUS_CHOICES = [
        (STATUS_RECEIVED, 'Received'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_NOT_SUBMITTED, 'Not Submitted'),
    ]

    payload = models.JSONField(help_text="Raw request payload preserved as-is.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RECEIVED)
    icv = models.PositiveIntegerField(null=True, blank=True)
    invoice_uuid = models.UUIDField(null=True, blank=True)
    xml_document = models.TextField(blank=True)
    invoice_hash = models.CharField(max_length=512, blank=True)
    qr_code_data = models.TextField(blank=True)
    zatca_response = models.JSONField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.organization} - {self.__class__.__name__} ({self.status})"


class Invoice(InvoiceDocumentBase):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='invoices',
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='invoices',
    )


class CreditNote(InvoiceDocumentBase):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='credit_notes',
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='credit_notes',
    )
    original_invoice = models.ForeignKey(
        Invoice,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='credit_notes',
    )
    system_return_number = models.CharField(max_length=255, blank=True)


class DebitNote(InvoiceDocumentBase):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='debit_notes',
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='debit_notes',
    )
