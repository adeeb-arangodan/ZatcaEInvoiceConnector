import base64
from decimal import Decimal


def _tlv(tag, value_bytes):
    return bytes([tag, len(value_bytes)]) + value_bytes


def generate_qr_tlv(
    organization, validated_data, invoice_hash, signature_b64, public_key_b64, timestamp_str,
    cert_signature_b64='',
):
    items = validated_data['items']
    line_total = sum(
        Decimal(str(i['qty'])) * Decimal(str(i['price'])) for i in items
    )
    vat_total = sum(
        Decimal(str(i['qty'])) * Decimal(str(i['price'])) * Decimal('0.15')
        for i in items if i['vat_type'] == 'S'
    )
    discounts = (
        Decimal(str(validated_data.get('doc_level_discount_vat', 0))) +
        Decimal(str(validated_data.get('doc_level_discount_novat', 0)))
    )
    advance = Decimal(str(validated_data.get('advance_paid', 0)))
    total_with_vat = (line_total - discounts + vat_total - advance).quantize(Decimal('0.01'))
    vat_total = vat_total.quantize(Decimal('0.01'))

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
