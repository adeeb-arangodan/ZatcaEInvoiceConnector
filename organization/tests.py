from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from .models import Device, DeviceKeyMaterial, Organization
from .services import (
    _build_zatca_csr_config,
    decrypt_private_key,
    encrypt_private_key,
    ensure_device_keys,
    encode_to_base64,
    register_device_in_zatca,
    request_compliance_csid,
)


class OrganizationCrudTests(TestCase):
    def test_create_organization(self):
        response = self.client.post(
            reverse("organization:create"),
            {
                "name": "Safa Makkah Polyclinic Company",
                "branch_name": "Branch-2",
                "industry_category": "Healthcare",
                "vat_number": "399999999900003",
                "country_code": "SA",
                "national_address_code": "RCFA3435",
                "street_name": "Al Baraqiyah",
                "building_number": "3435",
                "city_sub_division": "Al Futah Dist",
                "city_name": "Riyadh",
                "postal_zone": "12632",
                "cr_number": "1010138184",
                "invoice_category": "1100",
            },
        )

        self.assertRedirects(response, reverse("organization:list"))
        self.assertEqual(Organization.objects.count(), 1)

    def test_update_organization(self):
        organization = Organization.objects.create(
            name="Safa Makkah Polyclinic Company",
            branch_name="Branch-2",
            industry_category="Healthcare",
            vat_number="399999999900003",
            country_code="SA",
            national_address_code="RCFA3435",
            street_name="Al Baraqiyah",
            building_number="3435",
            city_sub_division="Al Futah Dist",
            city_name="Riyadh",
            postal_zone="12632",
            cr_number="1010138184",
            invoice_category="1100",
        )

        response = self.client.post(
            reverse("organization:update", args=[organization.pk]),
            {
                "name": "Safa Makkah Polyclinic Company",
                "branch_name": "Branch-3",
                "industry_category": "Healthcare",
                "vat_number": "399999999900003",
                "country_code": "SA",
                "national_address_code": "RCFA3435",
                "street_name": "Al Baraqiyah",
                "building_number": "3435",
                "city_sub_division": "Al Futah Dist",
                "city_name": "Jeddah",
                "postal_zone": "12632",
                "cr_number": "1010138184",
                "invoice_category": "1000",
            },
        )

        self.assertRedirects(response, reverse("organization:list"))
        organization.refresh_from_db()
        self.assertEqual(organization.branch_name, "Branch-3")
        self.assertEqual(organization.city_name, "Jeddah")
        self.assertEqual(organization.invoice_category, "1000")

    def test_cannot_update_organization_with_devices(self):
        organization = Organization.objects.create(
            name="Safa Makkah Polyclinic Company",
            branch_name="Branch-2",
            industry_category="Healthcare",
            vat_number="399999999900003",
            country_code="SA",
            national_address_code="RCFA3435",
            street_name="Al Baraqiyah",
            building_number="3435",
            city_sub_division="Al Futah Dist",
            city_name="Riyadh",
            postal_zone="12632",
            cr_number="1010138184",
            invoice_category="1100",
        )
        Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
        )

        response = self.client.post(
            reverse("organization:update", args=[organization.pk]),
            {
                "name": "Changed Name",
                "branch_name": "Branch-3",
                "industry_category": "Healthcare",
                "vat_number": "399999999900003",
                "country_code": "SA",
                "national_address_code": "RCFA3435",
                "street_name": "Al Baraqiyah",
                "building_number": "3435",
                "city_sub_division": "Al Futah Dist",
                "city_name": "Jeddah",
                "postal_zone": "12632",
                "cr_number": "1010138184",
                "invoice_category": "1000",
            },
        )

        self.assertRedirects(response, reverse("organization:list"))
        organization.refresh_from_db()
        self.assertEqual(organization.name, "Safa Makkah Polyclinic Company")
        self.assertEqual(organization.branch_name, "Branch-2")

    def test_delete_organization(self):
        organization = Organization.objects.create(
            name="Safa Makkah Polyclinic Company",
            branch_name="Branch-2",
            industry_category="Healthcare",
            vat_number="399999999900003",
            country_code="SA",
            national_address_code="RCFA3435",
            street_name="Al Baraqiyah",
            building_number="3435",
            city_sub_division="Al Futah Dist",
            city_name="Riyadh",
            postal_zone="12632",
            cr_number="1010138184",
            invoice_category="1100",
        )

        response = self.client.post(reverse("organization:delete", args=[organization.pk]))

        self.assertRedirects(response, reverse("organization:list"))
        self.assertFalse(Organization.objects.filter(pk=organization.pk).exists())

    def test_create_device_for_organization(self):
        organization = Organization.objects.create(
            name="Safa Makkah Polyclinic Company",
            branch_name="Branch-2",
            industry_category="Healthcare",
            vat_number="399999999900003",
            country_code="SA",
            national_address_code="RCFA3435",
            street_name="Al Baraqiyah",
            building_number="3435",
            city_sub_division="Al Futah Dist",
            city_name="Riyadh",
            postal_zone="12632",
            cr_number="1010138184",
            invoice_category="1100",
        )

        with patch("organization.services.shutil.which", return_value="openssl"), patch(
            "organization.services.subprocess.run"
        ) as mock_run, patch("pathlib.Path.read_text") as mock_read_text, patch(
            "organization.services.encrypt_private_key",
            side_effect=lambda value: f"encrypted::{value}",
        ), patch(
            "organization.services.decrypt_private_key",
            side_effect=lambda value: value.removeprefix("encrypted::"),
        ), patch(
            "organization.views.register_device_in_zatca",
            return_value=None,
        ):
            mock_read_text.side_effect = [
                "-----BEGIN EC PRIVATE KEY-----\nPRIVATE\n-----END EC PRIVATE KEY-----\n",
                "-----BEGIN PUBLIC KEY-----\nPUBLIC\n-----END PUBLIC KEY-----\n",
                "-----BEGIN CERTIFICATE REQUEST-----\nCSR\n-----END CERTIFICATE REQUEST-----\n",
            ]
            response = self.client.post(
                reverse("organization:device-create", args=[organization.pk]),
                {
                    "asset_id": "ASSET-100",
                    "egs_sw_serial_number": "SERIAL-200",
                    "otp": "123456",
                },
            )

        self.assertRedirects(response, reverse("organization:list"))
        device = Device.objects.get(organization=organization, asset_id="ASSET-100")
        self.assertEqual(device.egs_sw_serial_number, "SERIAL-200")
        self.assertEqual(device.otp, "123456")
        self.assertTrue(device.csr_content)
        self.assertIsNone(device.csid_response)
        self.assertIsNone(device.pcsid)
        self.assertEqual(mock_run.call_count, 3)
        self.assertEqual(
            device.key_material.private_key_pem,
            "encrypted::-----BEGIN EC PRIVATE KEY-----\nPRIVATE\n-----END EC PRIVATE KEY-----\n",
        )
        self.assertEqual(device.key_material.public_key_pem, "-----BEGIN PUBLIC KEY-----\nPUBLIC\n-----END PUBLIC KEY-----\n")

    def test_delete_device(self):
        organization = Organization.objects.create(
            name="Safa Makkah Polyclinic Company",
            branch_name="Branch-2",
            industry_category="Healthcare",
            vat_number="399999999900003",
            country_code="SA",
            national_address_code="RCFA3435",
            street_name="Al Baraqiyah",
            building_number="3435",
            city_sub_division="Al Futah Dist",
            city_name="Riyadh",
            postal_zone="12632",
            cr_number="1010138184",
            invoice_category="1100",
        )
        device = Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
        )

        response = self.client.post(reverse("organization:device-delete", args=[device.pk]))

        self.assertRedirects(response, reverse("organization:list"))
        self.assertFalse(Device.objects.filter(pk=device.pk).exists())

    def test_build_zatca_csr_config_uses_device_and_organization_fields(self):
        organization = Organization.objects.create(
            name="Safa Makkah Polyclinic Company",
            branch_name="Branch-2",
            industry_category="Healthcare",
            vat_number="399999999900003",
            country_code="SA",
            national_address_code="RCFA3435",
            street_name="Al Baraqiyah",
            building_number="3435",
            city_sub_division="Al Futah Dist",
            city_name="Riyadh",
            postal_zone="12632",
            cr_number="1010138184",
            invoice_category="1100",
        )
        device = Device(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
        )

        config = _build_zatca_csr_config(device)

        self.assertIn("CN = ASSET-100", config)
        self.assertIn("O = Safa Makkah Polyclinic Company", config)
        self.assertIn("OU = Branch-2", config)
        self.assertIn("organizationIdentifier = 399999999900003", config)
        self.assertIn("SN = 1-Safa Makkah Polyclinic Company|2-ASSET-100|3-SERIAL-200", config)
        self.assertIn("UID = 399999999900003", config)
        self.assertIn("title = 1100", config)
        self.assertIn("businessCategory = Healthcare", config)

    def test_ensure_device_keys_creates_keys_once_per_device(self):
        organization = Organization.objects.create(
            name="Safa Makkah Polyclinic Company",
            branch_name="Branch-2",
            industry_category="Healthcare",
            vat_number="399999999900003",
            country_code="SA",
            national_address_code="RCFA3435",
            street_name="Al Baraqiyah",
            building_number="3435",
            city_sub_division="Al Futah Dist",
            city_name="Riyadh",
            postal_zone="12632",
            cr_number="1010138184",
            invoice_category="1100",
        )
        device = Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
        )

        with patch("organization.services.shutil.which", return_value="openssl"), patch(
            "organization.services.subprocess.run"
        ) as mock_run, patch("pathlib.Path.read_text") as mock_read_text, patch(
            "organization.services.encrypt_private_key",
            side_effect=lambda value: f"encrypted::{value}",
        ):
            mock_read_text.side_effect = [
                "-----BEGIN EC PRIVATE KEY-----\nPRIVATE\n-----END EC PRIVATE KEY-----\n",
                "-----BEGIN PUBLIC KEY-----\nPUBLIC\n-----END PUBLIC KEY-----\n",
            ]
            key_material = ensure_device_keys(device)

        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(DeviceKeyMaterial.objects.count(), 1)
        self.assertEqual(
            key_material.private_key_pem,
            "encrypted::-----BEGIN EC PRIVATE KEY-----\nPRIVATE\n-----END EC PRIVATE KEY-----\n",
        )

        with patch("organization.services.subprocess.run") as mock_run:
            existing_key_material = ensure_device_keys(device)

        self.assertEqual(existing_key_material.pk, key_material.pk)
        self.assertFalse(mock_run.called)

    def test_encrypt_and_decrypt_private_key_use_cipher(self):
        class DummyCipher:
            def encrypt(self, value):
                return b"token::" + value

            def decrypt(self, value):
                return value.removeprefix(b"token::")

        with patch("organization.services._get_device_key_cipher", return_value=DummyCipher()):
            encrypted_value = encrypt_private_key("PRIVATE-KEY")
            decrypted_value = decrypt_private_key(encrypted_value)

        self.assertEqual(encrypted_value, "token::PRIVATE-KEY")
        self.assertEqual(decrypted_value, "PRIVATE-KEY")

    def test_encode_to_base64_encodes_csr_text(self):
        encoded_value = encode_to_base64("CSR-CONTENT")

        self.assertEqual(encoded_value, "Q1NSLUNPTlRFTlQ=")

    def test_request_compliance_csid_posts_base64_csr_to_sandbox_endpoint(self):
        captured = {}

        class DummyRequests:
            class HTTPError(Exception):
                pass

            class RequestException(Exception):
                pass

            @staticmethod
            def post(url, headers, json, timeout):
                captured["url"] = url
                captured["headers"] = headers
                captured["body"] = json
                captured["timeout"] = timeout

                class DummyResponse:
                    status_code = 200
                    text = '{"binarySecurityToken":"token","secret":"secret"}'

                    @staticmethod
                    def raise_for_status():
                        return None

                    @staticmethod
                    def json():
                        return {"binarySecurityToken": "token", "secret": "secret"}

                return DummyResponse()

        with patch("organization.services._get_requests_module", return_value=DummyRequests):
            response_payload = request_compliance_csid(
                "-----BEGIN CERTIFICATE REQUEST-----\nCSR\n-----END CERTIFICATE REQUEST-----\n",
                "123456",
            )

        self.assertEqual(
            captured["url"],
            "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal/compliance",
        )
        self.assertEqual(captured["headers"]["OTP"], "123456")
        self.assertEqual(captured["headers"]["Accept-Version"], "V2")
        self.assertEqual(captured["headers"]["Content-Type"], "application/json")
        self.assertEqual(captured["timeout"], 30)
        self.assertIn("csr", captured["body"])
        self.assertEqual(response_payload["binarySecurityToken"], "token")
        self.assertEqual(response_payload["secret"], "secret")

    def test_request_compliance_csid_returns_error_payload_on_http_error(self):
        class DummyResponse:
            status_code = 400
            text = '{"error":"invalid csr"}'

            @staticmethod
            def json():
                return {"error": "invalid csr"}

        class DummyHTTPError(Exception):
            def __init__(self, response):
                self.response = response

        class DummyRequests:
            HTTPError = DummyHTTPError
            RequestException = Exception

            @staticmethod
            def post(url, headers, json, timeout):
                class DummyErrorResponse:
                    response = DummyResponse()

                    @staticmethod
                    def raise_for_status():
                        raise DummyHTTPError(DummyResponse())

                return DummyErrorResponse()

        with patch("organization.services._get_requests_module", return_value=DummyRequests):
            response_payload = request_compliance_csid("CSR", "123456")

        self.assertEqual(response_payload["status_code"], 400)
        self.assertEqual(response_payload["error"]["error"], "invalid csr")

    def test_register_device_in_zatca_uses_existing_csr_content(self):
        organization = Organization.objects.create(
            name="Safa Makkah Polyclinic Company",
            branch_name="Branch-2",
            industry_category="Healthcare",
            vat_number="399999999900003",
            country_code="SA",
            national_address_code="RCFA3435",
            street_name="Al Baraqiyah",
            building_number="3435",
            city_sub_division="Al Futah Dist",
            city_name="Riyadh",
            postal_zone="12632",
            cr_number="1010138184",
            invoice_category="1100",
        )
        device = Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
            csr_content="CSR-CONTENT",
        )

        with patch(
            "organization.services.request_compliance_csid",
            return_value={"binarySecurityToken": "token"},
        ) as mock_request_compliance_csid:
            response_payload = register_device_in_zatca(device)

        mock_request_compliance_csid.assert_called_once_with("CSR-CONTENT", "123456")
        self.assertEqual(response_payload["binarySecurityToken"], "token")
