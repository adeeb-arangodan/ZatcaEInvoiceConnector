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
