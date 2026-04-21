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


def register_device_in_zatca(device):
    pass
