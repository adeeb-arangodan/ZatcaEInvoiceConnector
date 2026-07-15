import base64
import io

import qrcode

from .xml_builder import _compute_totals


def _tlv(tag, value_bytes):
    return bytes([tag, len(value_bytes)]) + value_bytes


def generate_qr_tlv(
    organization, validated_data, invoice_hash, signature_b64, public_key_b64, timestamp_str,
    cert_signature_b64='',
):
    totals = _compute_totals(
        validated_data['items'],
        validated_data.get('doc_level_discount_vat', 0),
        validated_data.get('doc_level_discount_novat', 0),
        validated_data.get('advance_paid', 0),
    )
    # BT-115 (Amount due for payment) and BT-110/111 (VAT total) must match
    # the same figures reported in the XML's LegalMonetaryTotal/TaxTotal,
    # or ZATCA rejects with QRCODE_VALIDATION / invoiceTotal_QRCODE_INVALID.
    total_with_vat = totals['payable']
    vat_total = totals['vat_total']

    tlv = b''
    tlv += _tlv(1, organization.name.encode('utf-8'))
    tlv += _tlv(2, organization.vat_number.encode('utf-8'))
    tlv += _tlv(3, timestamp_str.encode('utf-8'))
    tlv += _tlv(4, str(total_with_vat).encode('utf-8'))
    tlv += _tlv(5, str(vat_total).encode('utf-8'))
    # ZATCA embeds the hash and signature as the literal ASCII text of their
    # base64 strings (not the decoded bytes) — confirmed against ZATCA's
    # official sample QR. The public key is the exception: it's the raw
    # decoded bytes.
    tlv += _tlv(6, invoice_hash.encode('ascii'))
    tlv += _tlv(7, signature_b64.encode('ascii'))
    tlv += _tlv(8, base64.b64decode(public_key_b64))
    if cert_signature_b64:
        # Tag 9: the CA's own signature over the device certificate (raw
        # bytes, like tag 8 — not the ASCII-text encoding used for tags 6/7).
        tlv += _tlv(9, base64.b64decode(cert_signature_b64))
    return base64.b64encode(tlv).decode('ascii')


def generate_qr_image_data_uri(qr_code_data):
    """Render the same base64 TLV string embedded in the invoice XML as a
    scannable QR code image, for display/printing — not a separate QR, the
    same data a scanner would read out of the XML's QR AdditionalDocumentReference."""
    image = qrcode.make(qr_code_data)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'
