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

    INVOICE_TYPE_CODE_TO_DOCUMENT_TYPE = {
        '388': DOCUMENT_TYPE_INVOICE,
        '381': DOCUMENT_TYPE_CREDIT_NOTE,
        '383': DOCUMENT_TYPE_DEBIT_NOTE,
    }

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
    invoice_number = models.CharField(max_length=100, blank=True, default='')
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

    # Only populated for document_type=credit_note (the return-invoice flow).
    original_invoice = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='credit_notes',
    )
    system_return_number = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'document_type', 'invoice_number'],
                name='unique_invoice_number_per_org_and_type',
            ),
        ]

    def __str__(self):
        return f"{self.organization} - {self.document_type} ({self.status})"


class InvoiceSubmissionFailure(models.Model):
    """A ZATCA-rejected submission attempt that never consumed an ICV.

    process_invoice_submission() rolls back the whole attempt (ICV/PIH/row)
    on rejection and logs it here instead, so the chain never has a gap.
    Correct payload here (e.g. via admin) and resubmit via the Failed
    Submissions page to try again with a fresh ICV.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='invoice_submission_failures',
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name='invoice_submission_failures',
    )
    document_type = models.CharField(max_length=20, choices=InvoiceSubmission.DOCUMENT_TYPE_CHOICES)
    invoice_number = models.CharField(max_length=100, blank=True, default='')
    payload = models.JSONField()
    zatca_response = models.JSONField(null=True, blank=True)
    resolved = models.BooleanField(default=False)
    resolved_submission = models.ForeignKey(
        InvoiceSubmission,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.organization} - {self.document_type} failure ({self.invoice_number})"
