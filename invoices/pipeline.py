from django.db import transaction
from django.utils import timezone

from organization.services import encode_to_base64

from .hashing import get_icv_and_pih_atomically, hash_invoice_xml, store_invoice_hash
from .models import InvoiceSubmission
from .qr import generate_qr_tlv
from .signing import sign_invoice_xml
from .submission import submit_to_zatca
from .xml_builder import build_invoice_xml, embed_qr_in_xml

_INVOICE_TYPE_MAP = {'388': 'invoice', '381': 'credit_note', '383': 'debit_note'}


def process_invoice_submission(organization, device, validated_data):
    icv, pih = get_icv_and_pih_atomically(device)
    xml_bytes, invoice_uuid = build_invoice_xml(validated_data, organization, device, icv, pih)
    invoice_hash = hash_invoice_xml(xml_bytes)
    signed_xml_bytes, signature_b64, public_key_b64 = sign_invoice_xml(xml_bytes, device, invoice_hash)

    issue_time = str(validated_data['issue_time'])[:8]
    timestamp_str = f"{validated_data['issue_date']}T{issue_time}Z"
    qr_code_data = generate_qr_tlv(
        organization, validated_data, invoice_hash, signature_b64, public_key_b64, timestamp_str
    )
    final_xml_bytes = embed_qr_in_xml(signed_xml_bytes, qr_code_data)
    encoded_invoice = encode_to_base64(final_xml_bytes.decode('utf-8'))

    zatca_response = submit_to_zatca(
        device, invoice_hash, str(invoice_uuid), encoded_invoice,
        validated_data['invoice_type_code_name_attribute'],
    )
    is_accepted = zatca_response.get('status_code') not in (None, 400, 401, 422)
    document_type = _INVOICE_TYPE_MAP.get(validated_data['invoice_type_code'], 'invoice')

    with transaction.atomic():
        submission = InvoiceSubmission.objects.create(
            organization=organization,
            device=device,
            document_type=document_type,
            payload=_serializable_data(validated_data),
            status=InvoiceSubmission.STATUS_SUBMITTED if is_accepted else InvoiceSubmission.STATUS_REJECTED,
            invoice_uuid=invoice_uuid,
            xml_document=final_xml_bytes.decode('utf-8'),
            invoice_hash=invoice_hash,
            qr_code_data=qr_code_data,
            zatca_response=zatca_response,
            submitted_at=timezone.now() if is_accepted else None,
        )
        if is_accepted:
            store_invoice_hash(device, invoice_hash)

    return submission


def _serializable_data(validated_data):
    result = {}
    for key, value in validated_data.items():
        if hasattr(value, 'isoformat'):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [
                {k: str(v) if hasattr(v, 'quantize') else v for k, v in item.items()}
                for item in value
            ]
        else:
            result[key] = str(value) if hasattr(value, 'quantize') else value
    return result
