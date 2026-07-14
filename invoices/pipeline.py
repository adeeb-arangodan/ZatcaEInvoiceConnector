from django.db import transaction
from django.utils import timezone

from organization.services import encode_to_base64

from .hashing import get_icv_and_pih_atomically, hash_invoice_xml, store_invoice_hash
from .models import InvoiceSubmission, InvoiceSubmissionFailure
from .qr import generate_qr_tlv
from .signing import sign_invoice_xml
from .submission import submit_to_zatca
from .xml_builder import build_invoice_xml, embed_qr_in_xml


class InvoiceSubmissionRejected(Exception):
    """Raised when ZATCA rejects a submission attempt.

    By the time this is raised, the whole attempt has already been rolled
    back — no ICV/PIH advance, no InvoiceSubmission row — so nothing was
    consumed and a corrected retry gets the same ICV. The attempt itself is
    preserved in `.failure` (an InvoiceSubmissionFailure) for correction and
    resubmission via the Failed Submissions page.
    """

    def __init__(self, failure):
        self.failure = failure
        super().__init__(f"ZATCA rejected the submission: {failure.zatca_response}")


def process_invoice_submission(organization, device, validated_data, invoice_number_factory=None):
    document_type = InvoiceSubmission.INVOICE_TYPE_CODE_TO_DOCUMENT_TYPE.get(
        validated_data['invoice_type_code'], InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
    )
    rejection_response = None

    with transaction.atomic():
        icv, pih = get_icv_and_pih_atomically(organization)

        if invoice_number_factory is not None:
            validated_data['invoice_number'] = invoice_number_factory(icv)

        submission = InvoiceSubmission.objects.create(
            organization=organization,
            device=device,
            document_type=document_type,
            invoice_number=validated_data['invoice_number'],
            payload=_serializable_data(validated_data),
            status=InvoiceSubmission.STATUS_PROCESSING,
            icv=icv,
        )

        xml_bytes, invoice_uuid = build_invoice_xml(validated_data, organization, device, icv, pih)
        invoice_hash = hash_invoice_xml(xml_bytes)
        signed_xml_bytes, signature_b64, public_key_b64, cert_signature_b64 = sign_invoice_xml(
            xml_bytes, device, invoice_hash
        )

        issue_time = str(validated_data['issue_time'])[:8]
        timestamp_str = f"{validated_data['issue_date']}T{issue_time}"
        qr_code_data = generate_qr_tlv(
            organization, validated_data, invoice_hash, signature_b64, public_key_b64, timestamp_str,
            cert_signature_b64,
        )
        final_xml_bytes = embed_qr_in_xml(signed_xml_bytes, qr_code_data)

        submission.invoice_uuid = invoice_uuid
        submission.xml_document = final_xml_bytes.decode('utf-8')
        submission.invoice_hash = invoice_hash
        submission.qr_code_data = qr_code_data
        submission.save(update_fields=['invoice_uuid', 'xml_document', 'invoice_hash', 'qr_code_data'])

        # ZATCA is contacted from inside this same locked, atomic block now —
        # not after it. ZATCA tracks the last ICV/hash it *accepted* on its
        # side, so advancing our chain on an invoice it goes on to reject
        # would leave a gap it can never reconcile; every invoice created
        # afterward would inherit that gap and get rejected too. Instead, on
        # rejection we roll back everything below (see the else branch) so
        # the ICV/PIH are never consumed and a corrected retry gets them
        # fresh.
        encoded_invoice = encode_to_base64(submission.xml_document)
        zatca_response = submit_to_zatca(
            device, invoice_hash, str(invoice_uuid), encoded_invoice,
            validated_data['invoice_type_code_name_attribute'],
        )
        is_accepted = zatca_response.get('status_code') not in (None, 400, 401, 422)

        if is_accepted:
            submission.status = InvoiceSubmission.STATUS_SUBMITTED
            submission.zatca_response = zatca_response
            submission.submitted_at = timezone.now()
            submission.save(update_fields=['status', 'zatca_response', 'submitted_at'])
            store_invoice_hash(organization, invoice_hash)
        else:
            rejection_response = zatca_response
            transaction.set_rollback(True)

    if rejection_response is not None:
        failure = InvoiceSubmissionFailure.objects.create(
            organization=organization,
            device=device,
            document_type=document_type,
            invoice_number=validated_data.get('invoice_number', ''),
            payload=_serializable_data(validated_data),
            zatca_response=rejection_response,
        )
        raise InvoiceSubmissionRejected(failure)

    return submission


def deliver_to_zatca(submission):
    """POST an already-finalized `not_submitted` row's XML to ZATCA again.

    Legacy path for `InvoiceSubmission` rows created before this app made
    submission fully atomic (see `process_invoice_submission`) — those rows
    already hold a permanently-consumed ICV/PIH position, so retrying them
    in place (same XML/hash, no regeneration) is still correct. New
    rejections no longer create rows like this; they're logged to
    `InvoiceSubmissionFailure` instead and corrected/resubmitted from
    scratch via the Failed Submissions page.
    """
    encoded_invoice = encode_to_base64(submission.xml_document)
    zatca_response = submit_to_zatca(
        submission.device, submission.invoice_hash, str(submission.invoice_uuid), encoded_invoice,
        submission.payload['invoice_type_code_name_attribute'],
    )
    is_accepted = zatca_response.get('status_code') not in (None, 400, 401, 422)

    submission.zatca_response = zatca_response
    submission.status = InvoiceSubmission.STATUS_SUBMITTED if is_accepted else InvoiceSubmission.STATUS_NOT_SUBMITTED
    submission.submitted_at = timezone.now() if is_accepted else None
    submission.save(update_fields=['zatca_response', 'status', 'submitted_at'])

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
