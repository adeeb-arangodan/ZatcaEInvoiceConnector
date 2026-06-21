import base64
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .models import DeviceKeyMaterial


def _build_zatca_csr_config(device):
    organization = device.organization
    serial_number = f"1-{organization.name}|2-{device.asset_id}|3-{device.egs_sw_serial_number}"
    registered_address = (
        f"{organization.building_number} {organization.street_name}, "
        f"{organization.city_sub_division}, {organization.city_name} {organization.postal_zone}"
    )
    business_category = organization.industry_category.replace("\n", " ").strip()
    common_name = device.asset_id.replace("\n", " ").strip()
    organization_name = organization.name.replace("\n", " ").strip()
    organizational_unit = organization.branch_name.replace("\n", " ").strip()

    return f"""oid_section = OIDs

[ OIDs ]
certificateTemplateName = 1.3.6.1.4.1.311.20.2

[ req ]
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[ dn ]
C = {organization.country_code}
O = {organization_name}
OU = {organizational_unit}
CN = {common_name}
organizationIdentifier = {organization.vat_number}

[ req_ext ]
certificateTemplateName = ASN1:PRINTABLESTRING:ZATCA-Code-Signing
subjectAltName = dirName:alt_names

[ alt_names ]
SN = {serial_number}
UID = {organization.vat_number}
title = {organization.invoice_category}
registeredAddress = {registered_address}
businessCategory = {business_category}
"""


def _get_device_key_cipher():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise ImproperlyConfigured(
            "The 'cryptography' package is required to encrypt device private keys."
        ) from exc

    if not settings.DEVICE_KEY_ENCRYPTION_KEY:
        raise ImproperlyConfigured(
            "DEVICE_KEY_ENCRYPTION_KEY must be set to encrypt device private keys."
        )

    try:
        return Fernet(settings.DEVICE_KEY_ENCRYPTION_KEY.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise ImproperlyConfigured(
            "DEVICE_KEY_ENCRYPTION_KEY must be a valid Fernet key."
        ) from exc


def encrypt_private_key(private_key_pem):
    cipher = _get_device_key_cipher()
    return cipher.encrypt(private_key_pem.encode("ascii")).decode("ascii")


def decrypt_private_key(encrypted_private_key):
    cipher = _get_device_key_cipher()
    return cipher.decrypt(encrypted_private_key.encode("ascii")).decode("ascii")


def _get_requests_module():
    try:
        import requests
    except ImportError as exc:
        raise ImproperlyConfigured(
            "The 'requests' package is required for ZATCA compliance API calls."
        ) from exc
    return requests


def encode_to_base64(value):
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def ensure_device_keys(device):
    if hasattr(device, "key_material"):
        return device.key_material

    openssl_binary = shutil.which("openssl")
    if not openssl_binary:
        raise ImproperlyConfigured(
            "OpenSSL is required to generate and save device keys. Install openssl and make it available on PATH."
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        key_path = temp_path / "device-private-key.pem"
        public_key_path = temp_path / "device-public-key.pem"

        subprocess.run(
            [
                openssl_binary,
                "ecparam",
                "-name",
                "prime256v1",
                "-genkey",
                "-noout",
                "-out",
                str(key_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                openssl_binary,
                "ec",
                "-in",
                str(key_path),
                "-pubout",
                "-out",
                str(public_key_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        return DeviceKeyMaterial.objects.create(
            device=device,
            private_key_pem=encrypt_private_key(key_path.read_text(encoding="ascii")),
            public_key_pem=public_key_path.read_text(encoding="ascii"),
        )


def generate_device_csr(device):
    openssl_binary = shutil.which("openssl")
    if not openssl_binary:
        raise ImproperlyConfigured(
            "OpenSSL is required to generate a ZATCA CSR. Install openssl and make it available on PATH."
        )

    key_material = ensure_device_keys(device)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        config_path = temp_path / "zatca-device.cnf"
        csr_path = temp_path / "device.csr"
        key_path = temp_path / "device-private-key.pem"

        config_path.write_text(_build_zatca_csr_config(device), encoding="ascii")
        key_path.write_text(decrypt_private_key(key_material.private_key_pem), encoding="ascii")

        subprocess.run(
            [
                openssl_binary,
                "req",
                "-new",
                "-sha256",
                "-key",
                str(key_path),
                "-config",
                str(config_path),
                "-out",
                str(csr_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return csr_path.read_text(encoding="ascii")


def request_compliance_csid(csr, zatca_otp):
    requests = _get_requests_module()
    csid_endpoint_url = (
        f"{settings.ZATCA_SERVER_URL.rstrip('/')}"
        f"/{settings.ZATCA_COMPLIANCE_API_ENDPOINT.lstrip('/')}"
    )
    request_headers = {
        "accept": "application/json",
        "OTP": zatca_otp,
        "Accept-Version": settings.ZATCA_API_ACCEPT_VERSION,
        "Content-Type": "application/json",
    }
    request_data = {"csr": encode_to_base64(csr)}

    try:
        response = requests.post(
            url=csid_endpoint_url,
            headers=request_headers,
            json=request_data,
            timeout=settings.ZATCA_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        try:
            error_payload = exc.response.json()
        except ValueError:
            error_payload = {"raw_response": exc.response.text}
        return {
            "status_code": exc.response.status_code,
            "error": error_payload,
        }
    except requests.RequestException as exc:
        return {
            "status_code": None,
            "error": {"message": str(exc)},
        }


def register_device_in_zatca(device):
    csr_content = device.csr_content or generate_device_csr(device)
    return request_compliance_csid(csr_content, device.otp)


def request_compliance_invoice_check(csid, invoice_hash, uuid, encoded_invoice):
    requests = _get_requests_module()
    url = (
        f"{settings.ZATCA_SERVER_URL.rstrip('/')}"
        f"/{settings.ZATCA_COMPLIANCE_INVOICE_CHECK_API_ENDPOINT.lstrip('/')}"
    )
    authorization_token = encode_to_base64(
        f"{csid['binarySecurityToken']}:{csid['secret']}"
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
        'uuid': uuid,
        'invoice': encoded_invoice,
    }
    try:
        response = requests.post(
            url=url, headers=headers, json=body, timeout=settings.ZATCA_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        try:
            error_payload = exc.response.json()
        except ValueError:
            error_payload = {'raw_response': exc.response.text}
        return {'status_code': exc.response.status_code, 'error': error_payload}
    except requests.RequestException as exc:
        return {'status_code': None, 'error': {'message': str(exc)}}


def request_pcsid(csid):
    requests = _get_requests_module()
    url = (
        f"{settings.ZATCA_SERVER_URL.rstrip('/')}"
        f"/{settings.ZATCA_PRODUCTION_CSID_API_ENDPOINT.lstrip('/')}"
    )
    authorization_token = encode_to_base64(
        f"{csid['binarySecurityToken']}:{csid['secret']}"
    )
    headers = {
        'accept': 'application/json',
        'Accept-Language': 'en',
        'Accept-Version': settings.ZATCA_API_ACCEPT_VERSION,
        'Content-Type': 'application/json',
        'Authorization': f'Basic {authorization_token}',
    }
    body = {'compliance_request_id': csid['requestID']}
    try:
        response = requests.post(
            url=url, headers=headers, json=body, timeout=settings.ZATCA_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        try:
            error_payload = exc.response.json()
        except ValueError:
            error_payload = {'raw_response': exc.response.text}
        return {'status_code': exc.response.status_code, 'error': error_payload}
    except requests.RequestException as exc:
        return {'status_code': None, 'error': {'message': str(exc)}}


def acquire_pcsid_for_device(device):
    from invoices.xml_builder import build_compliance_sample_invoice
    from invoices.signing import sign_invoice_xml

    csid = device.csid_response
    if not csid or 'binarySecurityToken' not in csid:
        raise ValueError("Device has no valid CSID. Cannot acquire PCSID.")

    xml_bytes, sample_uuid, invoice_hash = build_compliance_sample_invoice(device)
    signed_xml_bytes, _, _ = sign_invoice_xml(xml_bytes, device, invoice_hash)
    encoded_invoice = encode_to_base64(signed_xml_bytes.decode('utf-8'))

    request_compliance_invoice_check(
        csid=csid,
        invoice_hash=invoice_hash,
        uuid=str(sample_uuid),
        encoded_invoice=encoded_invoice,
    )
    pcsid_result = request_pcsid(csid)
    device.pcsid = pcsid_result
    device.save(update_fields=['pcsid', 'updated_at'])
    return pcsid_result
