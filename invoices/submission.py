from django.conf import settings

from organization.services import encode_to_base64, _get_requests_module


def submit_to_zatca(device, invoice_hash, invoice_uuid, encoded_invoice, invoice_type_code_name_attribute):
    credential = (
        device.pcsid
        if (device.pcsid and 'binarySecurityToken' in device.pcsid)
        else device.csid_response
    )
    if not credential or 'binarySecurityToken' not in credential:
        return {'status_code': None, 'error': {'message': 'Device has no valid credential (CSID/PCSID).'}}

    # KSA-2 (BR-KSA-06): the invoice transaction code's first 2 digits are the
    # invoice subtype — "01" = standard (clearance required before issuance),
    # "02" = simplified (reported within 24h after issuance). Both subtypes
    # start with "0", so only the 2-digit prefix reliably distinguishes them.
    is_simplified = invoice_type_code_name_attribute.startswith('02')
    endpoint = (
        settings.ZATCA_REPORTING_API_ENDPOINT
        if is_simplified
        else settings.ZATCA_CLEARANCE_API_ENDPOINT
    )
    url = f"{settings.ZATCA_SERVER_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    authorization_token = encode_to_base64(
        f"{credential['binarySecurityToken']}:{credential['secret']}"
    )
    headers = {
        'accept': 'application/json',
        'Accept-Language': 'en',
        'Accept-Version': settings.ZATCA_API_ACCEPT_VERSION,
        'Content-Type': 'application/json',
        'Authorization': f'Basic {authorization_token}',
    }
    body = {
        'invoiceHash': invoice_hash,
        'uuid': invoice_uuid,
        'invoice': encoded_invoice,
    }
    requests = _get_requests_module()
    try:
        response = requests.post(
            url=url,
            headers=headers,
            json=body,
            timeout=settings.ZATCA_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        data['status_code'] = response.status_code
        return data
    except requests.HTTPError as exc:
        try:
            error_payload = exc.response.json()
        except ValueError:
            error_payload = {'raw_response': exc.response.text}
        return {
            'status_code': exc.response.status_code,
            'error': error_payload,
        }
    except requests.RequestException as exc:
        return {
            'status_code': None,
            'error': {'message': str(exc)},
        }
