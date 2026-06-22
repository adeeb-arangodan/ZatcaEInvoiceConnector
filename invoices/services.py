from .models import CreditNote
from .pipeline import process_invoice_submission


def build_return_payload(original_invoice, system_return_number='', reason=''):
    payload = dict(original_invoice.payload)
    payload['invoice_type_code'] = '381'
    payload['billing_reference'] = payload.get('invoice_number', '')

    note_parts = [payload.get('notes') or '']
    if reason:
        note_parts.append(f"Return reason: {reason}")
    if system_return_number:
        note_parts.append(f"System return ref: {system_return_number}")
    payload['notes'] = ' | '.join(part for part in note_parts if part)

    return payload


def create_return_credit_note(organization, device, original_invoice, system_return_number='', reason=''):
    validated_data = build_return_payload(original_invoice, system_return_number, reason)

    credit_note = process_invoice_submission(
        organization=organization,
        device=device,
        validated_data=validated_data,
        invoice_number_factory=lambda icv: f"CN-{icv}",
    )

    # original_invoice/system_return_number are CreditNote-specific, so they
    # aren't threaded through the shared pipeline signature — set them here.
    CreditNote.objects.filter(pk=credit_note.pk).update(
        original_invoice=original_invoice,
        system_return_number=system_return_number,
    )
    credit_note.refresh_from_db()
    return credit_note
