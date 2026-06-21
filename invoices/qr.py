import base64
from decimal import Decimal


def _tlv(tag, value_bytes):
    return bytes([tag, len(value_bytes)]) + value_bytes


def generate_qr_tlv(organization, validated_data, invoice_hash, signature_b64, public_key_b64, timestamp_str):
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
    tlv += _tlv(6, base64.b64decode(invoice_hash))
    tlv += _tlv(7, base64.b64decode(signature_b64))
    tlv += _tlv(8, base64.b64decode(public_key_b64))
    return base64.b64encode(tlv).decode('ascii')
