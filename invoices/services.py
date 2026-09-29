from decimal import ROUND_HALF_UP, Decimal

from .models import InvoiceSubmission
from .pipeline import process_invoice_submission


class DuplicateReturnNumberError(Exception):
    """Raised when the caller-supplied system_return_number collides with an
    existing credit note invoice number for this organization."""


def _bucket_amount(items, taxable):
    return sum(
        (Decimal(str(i['qty'])) * Decimal(str(i['price'])) for i in items if (i['vat_type'] == 'S') == taxable),
        Decimal('0'),
    )


def _prorate(original_amount, numerator, denominator):
    if not denominator:
        return Decimal('0.00')
    return (Decimal(str(original_amount)) * numerator / denominator).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


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


def build_debit_note_payload(
    source_document, items, issue_date, issue_time,
    doc_level_discount_vat=0, doc_level_discount_novat=0, system_debit_note_number='', reason='',
):
    payload = dict(source_document.payload)
    payload['invoice_type_code'] = '383'
    payload['billing_reference'] = payload.get('invoice_number', '')
    payload['reason'] = reason
    payload['items'] = items
    payload['issue_date'] = issue_date.isoformat() if hasattr(issue_date, 'isoformat') else issue_date
    payload['issue_time'] = issue_time.strftime('%H:%M:%S') if hasattr(issue_time, 'strftime') else issue_time
    payload['doc_level_discount_vat'] = doc_level_discount_vat or 0
    payload['doc_level_discount_novat'] = doc_level_discount_novat or 0
    payload['advance_paid'] = 0

    note_parts = [f"Debit note against {source_document.get_document_type_display()} {payload['billing_reference']}"]
    if system_debit_note_number:
        note_parts.append(f"System reference: {system_debit_note_number}")
    payload['notes'] = ' | '.join(note_parts)

    return payload


def create_debit_note(
    organization, device, source_document, items, issue_date, issue_time,
    doc_level_discount_vat=0, doc_level_discount_novat=0, system_debit_note_number='', reason='',
):
    from .serializers import InvoiceSubmissionSerializer

    payload = build_debit_note_payload(
        source_document, items, issue_date, issue_time,
        doc_level_discount_vat, doc_level_discount_novat, system_debit_note_number, reason,
    )

    # Reusing the credit-note return machinery (DuplicateReturnNumberError,
    # system_return_number) for debit notes too rather than introducing
    # parallel debit-note-specific names for what is functionally identical
    # "caller-supplied document number" handling.
    if system_debit_note_number:
        if InvoiceSubmission.objects.filter(
            organization=organization,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_DEBIT_NOTE,
            invoice_number=system_debit_note_number,
        ).exists():
            raise DuplicateReturnNumberError(
                f"A debit note with invoice number '{system_debit_note_number}' already exists for your organization."
            )
        invoice_number_factory = lambda icv: system_debit_note_number
    else:
        invoice_number_factory = lambda icv: f"DN-{icv}"

    # New user input (freeform correction lines, a new date) flows through
    # here, so validate it properly before it reaches the pipeline.
    serializer = InvoiceSubmissionSerializer(data=payload, organization=organization)
    serializer.is_valid(raise_exception=True)

    debit_note = process_invoice_submission(
        organization=organization,
        device=device,
        validated_data=serializer.validated_data,
        invoice_number_factory=invoice_number_factory,
    )

    # source_document/system_debit_note_number are debit-note-specific, so
    # they aren't threaded through the shared pipeline signature — set them
    # here, same as the credit-note return flows above.
    InvoiceSubmission.objects.filter(pk=debit_note.pk).update(
        original_invoice=source_document,
        system_return_number=system_debit_note_number,
    )
    debit_note.refresh_from_db()
    return debit_note


def build_custom_return_payload(original_invoice, items, issue_date, issue_time, system_return_number='', reason=''):
    payload = dict(original_invoice.payload)
    payload['invoice_type_code'] = '381'
    payload['billing_reference'] = payload.get('invoice_number', '')
    payload['reason'] = reason or 'Sales return'
    payload['items'] = items
    payload['issue_date'] = issue_date.isoformat() if hasattr(issue_date, 'isoformat') else issue_date
    payload['issue_time'] = issue_time.strftime('%H:%M:%S') if hasattr(issue_time, 'strftime') else issue_time

    # A custom return may only reverse some of the original items, so the
    # whole invoice's document-level discount/advance-payment amounts
    # (computed against the full item set) don't carry over as-is — each is
    # scaled down to the fraction of its own bucket actually being returned
    # (a full-item return therefore keeps the full discount; a genuine
    # partial return gets a proportional share instead of losing it all).
    original_items = original_invoice.payload.get('items', [])
    original_taxable = _bucket_amount(original_items, True)
    original_nontaxable = _bucket_amount(original_items, False)
    returned_taxable = _bucket_amount(items, True)
    returned_nontaxable = _bucket_amount(items, False)

    payload['doc_level_discount_vat'] = _prorate(
        original_invoice.payload.get('doc_level_discount_vat', 0), returned_taxable, original_taxable,
    )
    payload['doc_level_discount_novat'] = _prorate(
        original_invoice.payload.get('doc_level_discount_novat', 0), returned_nontaxable, original_nontaxable,
    )
    payload['advance_paid'] = _prorate(
        original_invoice.payload.get('advance_paid', 0),
        returned_taxable + returned_nontaxable, original_taxable + original_nontaxable,
    )

    note_parts = [f"Custom return against invoice {payload['billing_reference']}"]
    if reason:
        note_parts.append(f"Return reason: {reason}")
    if system_return_number:
        note_parts.append(f"System return ref: {system_return_number}")
    payload['notes'] = ' | '.join(note_parts)

    return payload


def create_custom_return_credit_note(
    organization, device, original_invoice, items, issue_date, issue_time, system_return_number='', reason='',
):
    from .serializers import InvoiceSubmissionSerializer

    payload = build_custom_return_payload(original_invoice, items, issue_date, issue_time, system_return_number, reason)

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
