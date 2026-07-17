from django.utils import timezone

from .models import InvoiceSubmission
from .pipeline import process_invoice_submission


class DuplicateReturnNumberError(Exception):
    """Raised when the caller-supplied system_return_number collides with an
    existing credit note invoice number for this organization."""


def build_return_payload(original_invoice, system_return_number='', reason=''):
    payload = dict(original_invoice.payload)
    payload['invoice_type_code'] = '381'
    payload['billing_reference'] = payload.get('invoice_number', '')

    # ZATCA (BR-KSA-17) requires a non-empty reason for issuance on every
    # credit/debit note, so fall back to a generic one if the caller left it blank.
    payload['reason'] = reason or 'Sales return'

    note_parts = [payload.get('notes') or '']
    if reason:
        note_parts.append(f"Return reason: {reason}")
    if system_return_number:
        note_parts.append(f"System return ref: {system_return_number}")
    payload['notes'] = ' | '.join(part for part in note_parts if part)

    return payload


def create_return_credit_note(organization, device, original_invoice, system_return_number='', reason=''):
    validated_data = build_return_payload(original_invoice, system_return_number, reason)

    # If the caller supplies a system_return_number, it becomes the credit
    # note's invoice number directly; otherwise one is auto-generated from
    # the ICV. Checked up front so a collision fails clean instead of
    # tripping the DB's unique constraint mid-pipeline.
    if system_return_number:
        if InvoiceSubmission.objects.filter(
            organization=organization,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE,
            invoice_number=system_return_number,
        ).exists():
            raise DuplicateReturnNumberError(
                f"A credit note with invoice number '{system_return_number}' already exists for your organization."
            )
        invoice_number_factory = lambda icv: system_return_number
    else:
        invoice_number_factory = lambda icv: f"CN-{icv}"

    credit_note = process_invoice_submission(
        organization=organization,
        device=device,
        validated_data=validated_data,
        invoice_number_factory=invoice_number_factory,
    )

    # original_invoice/system_return_number are credit-note-specific, so they
    # aren't threaded through the shared pipeline signature — set them here.
    InvoiceSubmission.objects.filter(pk=credit_note.pk).update(
        original_invoice=original_invoice,
        system_return_number=system_return_number,
    )
    credit_note.refresh_from_db()
    return credit_note


def build_custom_return_payload(original_invoice, items, issue_date, system_return_number='', reason=''):
    payload = dict(original_invoice.payload)
    payload['invoice_type_code'] = '381'
    payload['billing_reference'] = payload.get('invoice_number', '')
    payload['reason'] = reason or 'Sales return'
    payload['items'] = items
    payload['issue_date'] = issue_date.isoformat() if hasattr(issue_date, 'isoformat') else issue_date
    payload['issue_time'] = timezone.localtime().strftime('%H:%M:%S')

    # A custom return only reverses some of the original items, so the whole
    # invoice's document-level discount/advance-payment amounts (computed
    # against the full item set) don't carry over — they'd overstate the
    # discount against this smaller subset.
    payload['doc_level_discount_vat'] = 0
    payload['doc_level_discount_novat'] = 0
    payload['advance_paid'] = 0

    note_parts = [f"Custom return against invoice {payload['billing_reference']}"]
    if reason:
        note_parts.append(f"Return reason: {reason}")
    if system_return_number:
        note_parts.append(f"System return ref: {system_return_number}")
    payload['notes'] = ' | '.join(note_parts)

    return payload


def create_custom_return_credit_note(
    organization, device, original_invoice, items, issue_date, system_return_number='', reason='',
):
    from .serializers import InvoiceSubmissionSerializer

    payload = build_custom_return_payload(original_invoice, items, issue_date, system_return_number, reason)

    if system_return_number:
        if InvoiceSubmission.objects.filter(
            organization=organization,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE,
            invoice_number=system_return_number,
        ).exists():
            raise DuplicateReturnNumberError(
                f"A credit note with invoice number '{system_return_number}' already exists for your organization."
            )
        invoice_number_factory = lambda icv: system_return_number
    else:
        invoice_number_factory = lambda icv: f"CN-{icv}"

    # New user input (edited qty/price, a new date) flows through here, unlike
    # the full-return path above which only copies an already-once-validated
    # payload — so validate it properly before it reaches the pipeline.
    serializer = InvoiceSubmissionSerializer(data=payload, organization=organization)
    serializer.is_valid(raise_exception=True)

    credit_note = process_invoice_submission(
        organization=organization,
        device=device,
        validated_data=serializer.validated_data,
        invoice_number_factory=invoice_number_factory,
    )

    InvoiceSubmission.objects.filter(pk=credit_note.pk).update(
        original_invoice=original_invoice,
        system_return_number=system_return_number,
    )
    credit_note.refresh_from_db()
    return credit_note
