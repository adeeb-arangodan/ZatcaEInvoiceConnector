from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec as ec_module
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from invoices.models import InvoiceSubmission, InvoiceSubmissionFailure

from .models import Device, DeviceKeyMaterial, Organization
from .services import (
    _build_zatca_csr_config,
    acquire_pcsid_for_device,
    decrypt_private_key,
    encrypt_private_key,
    ensure_device_keys,
    encode_to_base64,
    register_device_in_zatca,
    request_compliance_csid,
)

User = get_user_model()


def _make_owned_organization(email="owner@example.com", **overrides):
    defaults = dict(
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
    defaults.update(overrides)
    user = User.objects.create_user(username=email, email=email, password="testpass123")
    organization = Organization.objects.create(email=email, owner_user=user, **defaults)
    return organization, user


class OrganizationCrudTests(TestCase):
    # django-simple-captcha snapshots CAPTCHA_TEST_MODE at import time, so
    # override_settings has no effect — patch the module attribute directly.
    @patch("captcha.fields.settings.CAPTCHA_TEST_MODE", True)
    def test_create_organization(self):
        response = self.client.post(
            reverse("organization:create"),
            {
                "name": "Safa Makkah Polyclinic Company",
                "email": "newowner@example.com",
                "password": "S0meStrongPass!23",
                "password_confirm": "S0meStrongPass!23",
                "captcha_0": "dummy",
                "captcha_1": "PASSED",
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

        self.assertEqual(Organization.objects.count(), 1)
        organization = Organization.objects.get()
        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))
        self.assertEqual(organization.email, "newowner@example.com")
        self.assertIsNotNone(organization.owner_user)

    def test_update_organization(self):
        organization, user = _make_owned_organization()
        self.client.force_login(user)

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

        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))
        organization.refresh_from_db()
        self.assertEqual(organization.branch_name, "Branch-3")
        self.assertEqual(organization.city_name, "Jeddah")
        self.assertEqual(organization.invoice_category, "1000")

    def test_update_organization_rejects_other_owner(self):
        organization, _owner = _make_owned_organization()
        _other_org, other_user = _make_owned_organization(email="other@example.com", vat_number="399999999900004", cr_number="9999999999")
        self.client.force_login(other_user)

        response = self.client.post(
            reverse("organization:update", args=[organization.pk]),
            {"name": "Hijacked"},
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_update_organization_with_devices(self):
        organization, user = _make_owned_organization()
        self.client.force_login(user)
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

        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))
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
        admin = User.objects.create_user(username="admin@example.com", is_staff=True)
        self.client.force_login(admin)

        response = self.client.post(reverse("organization:delete", args=[organization.pk]))

        self.assertRedirects(response, reverse("organization:list"))
        self.assertFalse(Organization.objects.filter(pk=organization.pk).exists())

    def test_create_device_for_organization(self):
        organization, user = _make_owned_organization(is_active=True)
        self.client.force_login(user)

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
        ), patch(
            "organization.views.acquire_pcsid_for_device",
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

        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))
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
        organization, user = _make_owned_organization()
        self.client.force_login(user)
        device = Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
        )

        response = self.client.post(reverse("organization:device-delete", args=[device.pk]))

        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))
        self.assertFalse(Device.objects.filter(pk=device.pk).exists())

    def test_delete_device_with_invoice_submission_is_blocked_on_post(self):
        organization, user = _make_owned_organization()
        self.client.force_login(user)
        device = Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
        )
        InvoiceSubmission.objects.create(
            organization=organization,
            device=device,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
            invoice_number="INV-001",
            payload={},
        )

        response = self.client.post(reverse("organization:device-delete", args=[device.pk]))

        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))
        self.assertTrue(Device.objects.filter(pk=device.pk).exists())

    def test_delete_device_with_invoice_submission_is_blocked_on_get(self):
        organization, user = _make_owned_organization()
        self.client.force_login(user)
        device = Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
        )
        InvoiceSubmission.objects.create(
            organization=organization,
            device=device,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
            invoice_number="INV-001",
            payload={},
        )

        response = self.client.get(reverse("organization:device-delete", args=[device.pk]))

        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))
        self.assertTrue(Device.objects.filter(pk=device.pk).exists())

    def test_delete_device_with_invoice_submission_failure_is_blocked(self):
        organization, user = _make_owned_organization()
        self.client.force_login(user)
        device = Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
        )
        InvoiceSubmissionFailure.objects.create(
            organization=organization,
            device=device,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
            invoice_number="INV-002",
            payload={},
        )

        response = self.client.post(reverse("organization:device-delete", args=[device.pk]))

        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))
        self.assertTrue(Device.objects.filter(pk=device.pk).exists())

    @override_settings(ZATCA_CSR_CERT_TEMPLATE_NAME="ZATCA-Code-Signing")
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
        self.assertIn("certificateTemplateName = ASN1:PRINTABLESTRING:ZATCA-Code-Signing", config)

    @override_settings(ZATCA_CSR_CERT_TEMPLATE_NAME="PREZATCA-Code-Signing")
    def test_build_zatca_csr_config_uses_simulation_cert_template_when_configured(self):
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

        self.assertIn("certificateTemplateName = ASN1:PRINTABLESTRING:PREZATCA-Code-Signing", config)

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

    @override_settings(ZATCA_SERVER_URL="https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal")
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

    # Real (self-signed, secp256k1) test certificate so signing.py's x509 parsing
    # succeeds the same way it would for a real CSID.
    _FAKE_CSID = {
        "binarySecurityToken": (
            "TUlJQkJqQ0JycUFEQWdFQ0FnRUJNQW9HQ0NxR1NNNDlCQU1DTUE4eERUQUxCZ05WQkFNTUJGUkZVMVF3"
            "SGhjTk1qUXdNVEF4TURBd01EQXdXaGNOTXpBd01UQXhNREF3TURBd1dqQVBNUTB3Q3dZRFZRUUREQVJV"
            "UlZOVU1GWXdFQVlIS29aSXpqMENBUVlGSzRFRUFBb0RRZ0FFNEpZSUluT1BaQWQ3eDlKZnFHZVVnVjNN"
            "Y2VDcTVQVW1HNndiL2Q0MkQ0MzZxSlRoRWMvQStZVFk5Z3E3OTJJWWI4QVczcWw3dkVuWllmaUZJVzFt"
            "N2pBS0JnZ3Foa2pPUFFRREFnTkhBREJFQWlCYzI4eWJDK3JNWjlMV3RZZ01KUjBENk9yd3pTU2V4ZzlT"
            "TnhPWEpOakN6QUlnVm1qZGk3MWxTYzdtV25CZHllZ0dzQTJWZW1ENWxRS0xFQkNaeStKdi81cz0="
        ),
        "secret": "testsecret",
        "requestID": "REQ-001",
    }

    def _make_device_with_signing_key(self):
        organization = Organization.objects.create(**{
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
        })
        device = Device.objects.create(
            organization=organization,
            asset_id="ASSET-100",
            egs_sw_serial_number="SERIAL-200",
            otp="123456",
            csid_response=self._FAKE_CSID,
        )
        private_key = ec_module.generate_private_key(ec_module.SECP256R1())
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        DeviceKeyMaterial.objects.create(device=device, private_key_pem=encrypt_private_key(pem))
        return device

    def test_acquire_pcsid_runs_all_six_compliance_checks_before_requesting_pcsid(self):
        device = self._make_device_with_signing_key()
        captured_urls = []

        class DummyRequests:
            class HTTPError(Exception):
                pass

            class RequestException(Exception):
                pass

            @staticmethod
            def post(url, headers, json, timeout):
                captured_urls.append(url)

                class DummyResponse:
                    status_code = 200

                    @staticmethod
                    def raise_for_status():
                        return None

                    @staticmethod
                    def json():
                        if url.endswith("/production/csids"):
                            return {"binarySecurityToken": "pcsid-token", "secret": "pcsid-secret"}
                        return {"validationResults": {"status": "PASS"}}

                return DummyResponse()

        with patch("organization.services._get_requests_module", return_value=DummyRequests):
            pcsid_result = acquire_pcsid_for_device(device)

        compliance_calls = [u for u in captured_urls if u.endswith("/compliance/invoices")]
        pcsid_calls = [u for u in captured_urls if u.endswith("/production/csids")]
        self.assertEqual(len(compliance_calls), 6)
        self.assertEqual(len(pcsid_calls), 1)
        self.assertEqual(pcsid_result["binarySecurityToken"], "pcsid-token")
        device.refresh_from_db()
        self.assertEqual(device.pcsid["binarySecurityToken"], "pcsid-token")

    def test_acquire_pcsid_raises_and_skips_pcsid_request_when_a_compliance_check_fails(self):
        device = self._make_device_with_signing_key()
        call_count = {"n": 0}

        def fake_request_compliance_invoice_check(csid, invoice_hash, uuid, encoded_invoice):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return {"status_code": 400, "error": {"message": "standard-credit-note-compliant failed"}}
            return {"validationResults": {"status": "PASS"}}

        with patch(
            "organization.services.request_compliance_invoice_check",
            side_effect=fake_request_compliance_invoice_check,
        ), patch("organization.services.request_pcsid") as mock_request_pcsid:
            with self.assertRaises(ValueError) as ctx:
                acquire_pcsid_for_device(device)

        self.assertIn("standard-credit-note-compliant", str(ctx.exception))
        mock_request_pcsid.assert_not_called()
        device.refresh_from_db()
        self.assertIsNone(device.pcsid)


class DeviceAdminDeleteTests(TestCase):
    """Confirms DeviceAdmin.has_delete_permission blocks deleting a device with
    invoices attached, through both the single-object delete page and the
    built-in "Delete selected" bulk action — closing the gap the app-level
    DeviceDeleteView guard doesn't cover."""

    def _make_superuser(self, email="admin@example.com"):
        return User.objects.create_user(
            username=email, email=email, password="testpass123", is_staff=True, is_superuser=True,
        )

    def test_single_object_delete_blocked_when_device_has_invoice(self):
        organization, _owner = _make_owned_organization()
        device = Device.objects.create(
            organization=organization, asset_id="A1", egs_sw_serial_number="S1", otp="1",
        )
        InvoiceSubmission.objects.create(
            organization=organization, device=device,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
            invoice_number="INV-001", payload={},
        )
        admin = self._make_superuser()
        self.client.force_login(admin)

        response = self.client.get(f"/admin/organization/device/{device.pk}/delete/")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Device.objects.filter(pk=device.pk).exists())

    def test_bulk_delete_selected_refused_when_device_has_invoice(self):
        organization, _owner = _make_owned_organization()
        device = Device.objects.create(
            organization=organization, asset_id="A1", egs_sw_serial_number="S1", otp="1",
        )
        InvoiceSubmission.objects.create(
            organization=organization, device=device,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
            invoice_number="INV-001", payload={},
        )
        admin = self._make_superuser()
        self.client.force_login(admin)

        response = self.client.post(
            "/admin/organization/device/",
            {"action": "delete_selected", "_selected_action": [str(device.pk)]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Device.objects.filter(pk=device.pk).exists())
        self.assertEqual(InvoiceSubmission.objects.filter(device=device).count(), 1)

    def test_single_object_delete_still_works_when_device_has_no_invoices(self):
        organization, _owner = _make_owned_organization()
        device = Device.objects.create(
            organization=organization, asset_id="A1", egs_sw_serial_number="S1", otp="1",
        )
        admin = self._make_superuser()
        self.client.force_login(admin)

        response = self.client.post(f"/admin/organization/device/{device.pk}/delete/", {"post": "yes"})

        self.assertFalse(Device.objects.filter(pk=device.pk).exists())


class LandingPageTests(TestCase):
    def test_anonymous_sees_welcome_page(self):
        response = self.client.get(reverse("organization:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "organization/welcome.html")

    def test_admin_redirected_to_organization_list(self):
        admin = User.objects.create_user(username="admin@example.com", is_staff=True)
        self.client.force_login(admin)

        response = self.client.get(reverse("organization:landing"))

        self.assertRedirects(response, reverse("organization:list"))

    def test_owner_redirected_to_dashboard(self):
        organization, user = _make_owned_organization()
        self.client.force_login(user)

        response = self.client.get(reverse("organization:landing"))

        self.assertRedirects(response, reverse("organization:dashboard", args=[organization.pk]))

    def test_authenticated_user_without_organization_sees_welcome_page(self):
        user = User.objects.create_user(username="noorg@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("organization:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "organization/welcome.html")


class CrossOwnerAccessTests(TestCase):
    def test_dashboard_cross_owner_returns_404(self):
        organization, _owner = _make_owned_organization()
        _other_org, other_user = _make_owned_organization(
            email="other1@example.com", vat_number="399999999900071", cr_number="5555555551",
        )
        self.client.force_login(other_user)

        response = self.client.get(reverse("organization:dashboard", args=[organization.pk]))

        self.assertEqual(response.status_code, 404)

    def test_device_create_cross_owner_returns_404(self):
        organization, _owner = _make_owned_organization(is_active=True)
        _other_org, other_user = _make_owned_organization(
            email="other2@example.com", vat_number="399999999900072", cr_number="5555555552", is_active=True,
        )
        self.client.force_login(other_user)

        response = self.client.get(reverse("organization:device-create", args=[organization.pk]))

        self.assertEqual(response.status_code, 404)

    def test_device_delete_cross_owner_returns_404(self):
        organization, _owner = _make_owned_organization()
        device = Device.objects.create(
            organization=organization, asset_id="A1", egs_sw_serial_number="S1", otp="1",
        )
        _other_org, other_user = _make_owned_organization(
            email="other3@example.com", vat_number="399999999900073", cr_number="5555555553",
        )
        self.client.force_login(other_user)

        response = self.client.get(reverse("organization:device-delete", args=[device.pk]))

        self.assertEqual(response.status_code, 404)

    def test_dashboard_accessible_by_admin_for_any_org(self):
        organization, _owner = _make_owned_organization()
        admin = User.objects.create_user(username="admin3@example.com", is_staff=True)
        self.client.force_login(admin)

        response = self.client.get(reverse("organization:dashboard", args=[organization.pk]))

        self.assertEqual(response.status_code, 200)

    def test_anonymous_redirected_to_login_for_dashboard(self):
        organization, _owner = _make_owned_organization()
        dashboard_url = reverse("organization:dashboard", args=[organization.pk])

        response = self.client.get(dashboard_url)

        self.assertRedirects(response, f"{reverse('login')}?next={dashboard_url}")


class SignupNegativeTests(TestCase):
    BASE_DATA = dict(
        name="New Org",
        branch_name="Branch-1",
        industry_category="Healthcare",
        vat_number="399999999900088",
        country_code="SA",
        national_address_code="RCFA3435",
        street_name="Al Baraqiyah",
        building_number="3435",
        city_sub_division="Al Futah Dist",
        city_name="Riyadh",
        postal_zone="12632",
        cr_number="1010138188",
        invoice_category="1100",
    )

    @patch("captcha.fields.settings.CAPTCHA_TEST_MODE", True)
    def test_password_mismatch_rejected(self):
        data = {
            **self.BASE_DATA,
            "email": "mismatch@example.com",
            "password": "GoodPass!234",
            "password_confirm": "Different!234",
            "captcha_0": "dummy",
            "captcha_1": "PASSED",
        }

        response = self.client.post(reverse("organization:create"), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Organization.objects.count(), 0)

    @patch("captcha.fields.settings.CAPTCHA_TEST_MODE", True)
    def test_duplicate_email_rejected(self):
        _make_owned_organization(
            email="dupe@example.com", vat_number="399999999900089", cr_number="1010138177",
        )
        data = {
            **self.BASE_DATA,
            "vat_number": "399999999900090",
            "cr_number": "1010138166",
            "email": "dupe@example.com",
            "password": "GoodPass!234",
            "password_confirm": "GoodPass!234",
            "captcha_0": "dummy",
            "captcha_1": "PASSED",
        }

        response = self.client.post(reverse("organization:create"), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Organization.objects.count(), 1)

    def test_bad_captcha_rejected(self):
        data = {
            **self.BASE_DATA,
            "email": "badcaptcha@example.com",
            "password": "GoodPass!234",
            "password_confirm": "GoodPass!234",
            "captcha_0": "dummy",
            "captcha_1": "WRONG",
        }

        response = self.client.post(reverse("organization:create"), data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Organization.objects.count(), 0)
