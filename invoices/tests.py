import json
import uuid
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec as ec_module
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from organization.models import Device, DeviceKeyMaterial, Organization
from organization.services import encrypt_private_key

User = get_user_model()

from .hashing import INITIAL_PIH, get_icv_and_pih_atomically, store_invoice_hash
from .models import InvoiceSubmission
from .pipeline import process_invoice_submission
from .serializers import InvoiceSubmissionSerializer
from .services import DuplicateReturnNumberError, create_return_credit_note

SUBMIT_URL = '/api/invoices/submit/'

VALID_PAYLOAD = {
    'device_asset_id': 'ASSET-100',
    'invoice_number': 'INV-001',
    'issue_date': '2026-06-09',
    'issue_time': '10:00:00',
    'invoice_type_code': '388',
    'invoice_type_code_name_attribute': '0100000',
    'customer_name': 'Test Customer',
    'customer_vat': '300000000000003',
    'customer_city': 'Riyadh',
    'customer_country_code': 'SA',
    'items': [
        {
            'slno': 1,
            'code': 'ITEM-001',
            'name': 'Consultation',
            'qty': '1.0000',
            'price': '100.0000',
            'vat_type': 'S',
        }
    ],
}

ORG_DEFAULTS = dict(
    name='Test Org',
    branch_name='Branch-1',
    industry_category='Healthcare',
    vat_number='399999999900003',
    country_code='SA',
    national_address_code='RCFA3435',
    street_name='Main St',
    building_number='1',
    city_sub_division='District',
    city_name='Riyadh',
    postal_zone='12345',
    cr_number='1010138184',
    invoice_category='1100',
    is_active=True,
)

FAKE_CSID = {
    # ZATCA's binarySecurityToken is base64-of-DER, base64-encoded again for
    # transport. This is a real (self-signed, secp256k1) test certificate so
    # signing.py's x509 parsing succeeds the same way it would for a real CSID.
    'binarySecurityToken': (
        'TUlJQkJqQ0JycUFEQWdFQ0FnRUJNQW9HQ0NxR1NNNDlCQU1DTUE4eERUQUxCZ05WQkFNTUJGUkZVMVF3'
        'SGhjTk1qUXdNVEF4TURBd01EQXdXaGNOTXpBd01UQXhNREF3TURBd1dqQVBNUTB3Q3dZRFZRUUREQVJV'
        'UlZOVU1GWXdFQVlIS29aSXpqMENBUVlGSzRFRUFBb0RRZ0FFNEpZSUluT1BaQWQ3eDlKZnFHZVVnVjNN'
        'Y2VDcTVQVW1HNndiL2Q0MkQ0MzZxSlRoRWMvQStZVFk5Z3E3OTJJWWI4QVczcWw3dkVuWllmaUZJVzFt'
        'N2pBS0JnZ3Foa2pPUFFRREFnTkhBREJFQWlCYzI4eWJDK3JNWjlMV3RZZ01KUjBENk9yd3pTU2V4ZzlT'
        'TnhPWEpOakN6QUlnVm1qZGk3MWxTYzdtV25CZHllZ0dzQTJWZW1ENWxRS0xFQkNaeStKdi81cz0='
    ),
    'secret': 'testsecret',
    'requestID': 'REQ-001',
}


def _make_stub_submission(**kwargs):
    stub = MagicMock(spec=InvoiceSubmission)
    stub.pk = 1
    stub.status = 'submitted'
    stub.qr_code_data = 'AQID'
    stub.invoice_uuid = uuid.uuid4()
    stub.zatca_response = {'status_code': 200}
    for k, v in kwargs.items():
        setattr(stub, k, v)
    return stub


class InvoiceSubmitViewTests(TestCase):

    def _make_org_with_device(self, **org_overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(org_overrides)
        org = Organization.objects.create(**defaults)
        device = Device.objects.create(
            organization=org,
            asset_id='ASSET-100',
            egs_sw_serial_number='SERIAL-200',
            otp='123456',
            csid_response=FAKE_CSID,
        )
        return org, device

    def _auth_header(self, org):
        return {'HTTP_AUTHORIZATION': f'ApiKey {org.api_key}'}

    def _post(self, payload, org=None, extra_headers=None):
        headers = self._auth_header(org) if org else {}
        if extra_headers:
            headers.update(extra_headers)
        return self.client.post(
            SUBMIT_URL,
            data=json.dumps(payload),
            content_type='application/json',
            **headers,
        )

    @patch('invoices.views.process_invoice_submission')
    def test_valid_invoice_returns_201(self, mock_pipeline):
        org, _ = self._make_org_with_device()
        mock_pipeline.return_value = _make_stub_submission()
        response = self._post(VALID_PAYLOAD, org)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn('id', body)
        self.assertIn('qr_code', body)
        self.assertIn('invoice_uuid', body)
        self.assertEqual(body['status'], 'submitted')

    def test_missing_api_key_returns_401(self):
        response = self.client.post(
            SUBMIT_URL,
            data=json.dumps(VALID_PAYLOAD),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_api_key_returns_401(self):
        response = self.client.post(
            SUBMIT_URL,
            data=json.dumps(VALID_PAYLOAD),
            content_type='application/json',
            HTTP_AUTHORIZATION='ApiKey totally-invalid-key',
        )
        self.assertEqual(response.status_code, 401)

    def test_inactive_org_returns_403(self):
        org, _ = self._make_org_with_device(is_active=False)
        response = self._post(VALID_PAYLOAD, org)
        self.assertEqual(response.status_code, 403)

    def test_missing_invoice_number_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {**VALID_PAYLOAD}
        del payload['invoice_number']
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('invoice_number', response.json())

    def test_device_from_other_org_returns_400(self):
        self._make_org_with_device()
        other_org = Organization.objects.create(
            name='Other Org', branch_name='B', industry_category='IT',
            vat_number='399999999900004', country_code='SA',
            national_address_code='X', street_name='Y', building_number='2',
            city_sub_division='D', city_name='Jeddah', postal_zone='11111',
            cr_number='9999999999', invoice_category='1100', is_active=True,
        )
        response = self._post(VALID_PAYLOAD, other_org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('device_asset_id', response.json())

    def test_credit_note_without_billing_reference_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {**VALID_PAYLOAD, 'invoice_type_code': '381', 'invoice_type_code_name_attribute': '0100000'}
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('billing_reference', response.json())

    def test_debit_note_without_billing_reference_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {**VALID_PAYLOAD, 'invoice_type_code': '383', 'invoice_type_code_name_attribute': '0100000'}
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('billing_reference', response.json())

    def test_credit_note_without_reason_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {
            **VALID_PAYLOAD,
            'invoice_type_code': '381',
            'invoice_type_code_name_attribute': '0100000',
            'billing_reference': 'INV-001',
        }
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('reason', response.json())

    def test_empty_items_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {**VALID_PAYLOAD, 'items': []}
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('items', response.json())

    def test_hea_exemption_without_customer_id_number_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {
            **VALID_PAYLOAD,
            'items': [{
                **VALID_PAYLOAD['items'][0],
                'vat_type': 'Z',
                'VatExceptionReason': 'VATEX-SA-HEA',
            }],
        }
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('customer_id_number', response.json())

    def test_edu_exemption_without_customer_id_number_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {
            **VALID_PAYLOAD,
            'items': [{
                **VALID_PAYLOAD['items'][0],
                'vat_type': 'Z',
                'VatExceptionReason': 'VATEX-SA-EDU',
            }],
        }
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('customer_id_number', response.json())

    @patch('invoices.views.process_invoice_submission')
    def test_hea_exemption_with_customer_id_number_returns_201(self, mock_pipeline):
        org, _ = self._make_org_with_device()
        mock_pipeline.return_value = _make_stub_submission()
        payload = {
            **VALID_PAYLOAD,
            'customer_id_number': '1234567890',
            'items': [{
                **VALID_PAYLOAD['items'][0],
                'vat_type': 'Z',
                'VatExceptionReason': 'VATEX-SA-HEA',
            }],
        }
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 201)

    def test_duplicate_invoice_number_for_same_org_and_type_returns_400(self):
        org, _ = self._make_org_with_device()
        InvoiceSubmission.objects.create(
            organization=org,
            device=Device.objects.get(organization=org),
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
            invoice_number=VALID_PAYLOAD['invoice_number'],
            payload={},
            icv=1,
        )

        response = self._post(VALID_PAYLOAD, org)

        self.assertEqual(response.status_code, 400)
        self.assertIn('invoice_number', response.json())

    def test_same_invoice_number_allowed_for_different_document_types(self):
        org, _ = self._make_org_with_device()
        InvoiceSubmission.objects.create(
            organization=org,
            device=Device.objects.get(organization=org),
            document_type=InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE,
            invoice_number=VALID_PAYLOAD['invoice_number'],
            payload={},
            icv=1,
        )

        with patch('invoices.views.process_invoice_submission') as mock_pipeline:
            mock_pipeline.return_value = _make_stub_submission()
            response = self._post(VALID_PAYLOAD, org)

        self.assertEqual(response.status_code, 201)

    def test_same_invoice_number_allowed_for_different_organizations(self):
        org, _ = self._make_org_with_device()
        other_org = Organization.objects.create(
            name='Other Org', branch_name='B', industry_category='IT',
            vat_number='399999999900066', country_code='SA',
            national_address_code='X', street_name='Y', building_number='2',
            city_sub_division='D', city_name='Jeddah', postal_zone='11111',
            cr_number='9999999996', invoice_category='1100', is_active=True,
        )
        InvoiceSubmission.objects.create(
            organization=other_org,
            device=Device.objects.create(
                organization=other_org, asset_id='OTHER-DEV', egs_sw_serial_number='S', otp='1',
            ),
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
            invoice_number=VALID_PAYLOAD['invoice_number'],
            payload={},
            icv=1,
        )

        with patch('invoices.views.process_invoice_submission') as mock_pipeline:
            mock_pipeline.return_value = _make_stub_submission()
            response = self._post(VALID_PAYLOAD, org)

        self.assertEqual(response.status_code, 201)

    @patch('invoices.views.process_invoice_submission')
    def test_submission_calls_pipeline_with_correct_args(self, mock_pipeline):
        org, device = self._make_org_with_device()
        mock_pipeline.return_value = _make_stub_submission()
        self._post(VALID_PAYLOAD, org)
        self.assertTrue(mock_pipeline.called)
        call_kwargs = mock_pipeline.call_args
        self.assertEqual(call_kwargs.kwargs['organization'], org)
        self.assertEqual(call_kwargs.kwargs['device'], device)

    @patch('invoices.views.process_invoice_submission')
    def test_credit_note_with_billing_reference_returns_201(self, mock_pipeline):
        org, _ = self._make_org_with_device()
        mock_pipeline.return_value = _make_stub_submission()
        payload = {
            **VALID_PAYLOAD,
            'invoice_type_code': '381',
            'invoice_type_code_name_attribute': '0100000',
            'billing_reference': 'INV-001',
            'reason': 'Goods returned',
        }
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 201)

    def test_device_without_csid_returns_422(self):
        org, device = self._make_org_with_device()
        device.csid_response = None
        device.save()
        response = self._post(VALID_PAYLOAD, org)
        self.assertEqual(response.status_code, 422)


class OrganizationApiKeyTests(TestCase):

    def _make_org(self, **overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(overrides)
        return Organization.objects.create(**defaults)

    def test_api_key_auto_generated_on_create(self):
        org = self._make_org()
        self.assertTrue(org.api_key)
        self.assertEqual(len(org.api_key), 64)

    def test_api_key_not_regenerated_on_update(self):
        org = self._make_org()
        original_key = org.api_key
        org.city_name = 'Jeddah'
        org.save()
        org.refresh_from_db()
        self.assertEqual(org.api_key, original_key)

    def test_api_key_is_unique_across_orgs(self):
        org1 = self._make_org()
        org2 = self._make_org(vat_number='399999999900004', cr_number='9999999999')
        self.assertNotEqual(org1.api_key, org2.api_key)


class InvoiceHashingTests(TestCase):

    def _make_org(self, **overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(overrides)
        return Organization.objects.create(**defaults)

    def test_first_call_returns_icv_one_and_initial_pih(self):
        org = self._make_org()

        icv, pih = get_icv_and_pih_atomically(org)

        self.assertEqual(icv, 1)
        self.assertEqual(pih, INITIAL_PIH)

    def test_second_call_returns_icv_two_and_stored_hash(self):
        org = self._make_org()

        get_icv_and_pih_atomically(org)
        store_invoice_hash(org, 'first-invoice-hash')
        icv, pih = get_icv_and_pih_atomically(org)

        self.assertEqual(icv, 2)
        self.assertEqual(pih, 'first-invoice-hash')

    def test_counter_is_shared_across_devices_in_same_organization(self):
        org = self._make_org()
        device_a = Device.objects.create(
            organization=org,
            asset_id='ASSET-A',
            egs_sw_serial_number='SERIAL-A',
            otp='111111',
        )
        device_b = Device.objects.create(
            organization=org,
            asset_id='ASSET-B',
            egs_sw_serial_number='SERIAL-B',
            otp='222222',
        )

        icv_a, pih_a = get_icv_and_pih_atomically(device_a.organization)
        store_invoice_hash(device_a.organization, 'hash-from-device-a')
        icv_b, pih_b = get_icv_and_pih_atomically(device_b.organization)

        self.assertEqual(icv_a, 1)
        self.assertEqual(pih_a, INITIAL_PIH)
        self.assertEqual(icv_b, 2)
        self.assertEqual(pih_b, 'hash-from-device-a')

    def test_store_invoice_hash_persists_on_organization(self):
        org = self._make_org()

        store_invoice_hash(org, 'some-hash')
        org.refresh_from_db()

        self.assertEqual(org.last_invoice_hash, 'some-hash')


@override_settings(DEVICE_KEY_ENCRYPTION_KEY=Fernet.generate_key().decode())
class InvoicePipelineTests(TestCase):
    """Exercises process_invoice_submission() end-to-end (real XML build/hash/sign), mocking only submit_to_zatca."""

    def _make_org_with_signing_device(self, **org_overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(org_overrides)
        org = Organization.objects.create(**defaults)
        device = Device.objects.create(
            organization=org,
            asset_id='ASSET-100',
            egs_sw_serial_number='SERIAL-200',
            otp='123456',
            csid_response=FAKE_CSID,
        )
        private_key = ec_module.generate_private_key(ec_module.SECP256R1())
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode('ascii')
        DeviceKeyMaterial.objects.create(device=device, private_key_pem=encrypt_private_key(pem))
        return org, device

    def _validated(self, payload, org):
        serializer = InvoiceSubmissionSerializer(data=payload, organization=org)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data, serializer.get_resolved_device()

    @patch('invoices.pipeline.submit_to_zatca')
    def test_chain_advances_even_when_zatca_rejects(self, mock_submit):
        org, device = self._make_org_with_signing_device()
        mock_submit.return_value = {'status_code': 422, 'error': {'message': 'invalid'}}
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)

        submission = process_invoice_submission(org, resolved_device, validated_data)

        org.refresh_from_db()
        self.assertEqual(submission.status, InvoiceSubmission.STATUS_NOT_SUBMITTED)
        self.assertEqual(submission.icv, 1)
        self.assertTrue(submission.invoice_hash)
        self.assertEqual(org.last_invoice_hash, submission.invoice_hash)
        self.assertEqual(org.invoice_counter, 1)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_chain_advances_on_zatca_acceptance(self, mock_submit):
        org, device = self._make_org_with_signing_device()
        mock_submit.return_value = {'status_code': 200}
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)

        submission = process_invoice_submission(org, resolved_device, validated_data)

        self.assertEqual(submission.status, InvoiceSubmission.STATUS_SUBMITTED)
        self.assertIsNotNone(submission.submitted_at)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_pih_is_committed_before_zatca_is_contacted(self, mock_submit):
        """Regression test: the org row lock used to be released (and last_invoice_hash
        stored) only *after* the ZATCA round-trip, so two concurrent submissions for the
        same org could read the same stale PIH. The fix commits the local hash and
        releases the lock before ZATCA is ever contacted."""
        org, device = self._make_org_with_signing_device()
        seen = {}

        def fake_submit(*args, **kwargs):
            seen['last_invoice_hash'] = Organization.objects.get(pk=org.pk).last_invoice_hash
            return {'status_code': 200}

        mock_submit.side_effect = fake_submit
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)

        submission = process_invoice_submission(org, resolved_device, validated_data)

        self.assertEqual(seen['last_invoice_hash'], submission.invoice_hash)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_build_failure_rolls_back_icv_and_leaves_no_row(self, mock_submit):
        org, device = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)

        with patch('invoices.pipeline.build_invoice_xml', side_effect=ValueError('boom')):
            with self.assertRaises(ValueError):
                process_invoice_submission(org, resolved_device, validated_data)

        org.refresh_from_db()
        self.assertEqual(org.invoice_counter, 0)
        self.assertEqual(org.last_invoice_hash, '')
        self.assertEqual(InvoiceSubmission.objects.count(), 0)
        mock_submit.assert_not_called()


@override_settings(DEVICE_KEY_ENCRYPTION_KEY=Fernet.generate_key().decode())
class DocumentRoutingTests(TestCase):
    """Confirms invoice_type_code sets the correct document_type on the shared table."""

    def _make_org_with_signing_device(self, **org_overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(org_overrides)
        org = Organization.objects.create(**defaults)
        device = Device.objects.create(
            organization=org,
            asset_id='ASSET-100',
            egs_sw_serial_number='SERIAL-200',
            otp='123456',
            csid_response=FAKE_CSID,
        )
        private_key = ec_module.generate_private_key(ec_module.SECP256R1())
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode('ascii')
        DeviceKeyMaterial.objects.create(device=device, private_key_pem=encrypt_private_key(pem))
        return org, device

    def _validated(self, payload, org):
        serializer = InvoiceSubmissionSerializer(data=payload, organization=org)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data, serializer.get_resolved_device()

    @patch('invoices.pipeline.submit_to_zatca')
    def test_invoice_type_code_388_sets_document_type_invoice(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)

        submission = process_invoice_submission(org, resolved_device, validated_data)

        self.assertEqual(submission.document_type, InvoiceSubmission.DOCUMENT_TYPE_INVOICE)
        self.assertEqual(InvoiceSubmission.objects.count(), 1)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_invoice_type_code_381_sets_document_type_credit_note(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        payload = {
            **VALID_PAYLOAD, 'invoice_type_code': '381', 'billing_reference': 'INV-001',
            'reason': 'Goods returned',
        }
        validated_data, resolved_device = self._validated(payload, org)

        submission = process_invoice_submission(org, resolved_device, validated_data)

        self.assertEqual(submission.document_type, InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE)
        self.assertEqual(InvoiceSubmission.objects.count(), 1)
        self.assertIn('<cbc:InstructionNote>Goods returned</cbc:InstructionNote>', submission.xml_document)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_invoice_type_code_383_sets_document_type_debit_note(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        payload = {
            **VALID_PAYLOAD, 'invoice_type_code': '383', 'billing_reference': 'INV-001',
            'reason': 'Additional charges',
        }
        validated_data, resolved_device = self._validated(payload, org)

        submission = process_invoice_submission(org, resolved_device, validated_data)

        self.assertEqual(submission.document_type, InvoiceSubmission.DOCUMENT_TYPE_DEBIT_NOTE)
        self.assertEqual(InvoiceSubmission.objects.count(), 1)


@override_settings(DEVICE_KEY_ENCRYPTION_KEY=Fernet.generate_key().decode())
class ReturnInvoiceFlowTests(TestCase):
    """Exercises the return-invoice (credit note) flow, both via services.py directly and via the API."""

    def _make_org_with_signing_device(self, **org_overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(org_overrides)
        org = Organization.objects.create(**defaults)
        device = Device.objects.create(
            organization=org,
            asset_id='ASSET-100',
            egs_sw_serial_number='SERIAL-200',
            otp='123456',
            csid_response=FAKE_CSID,
        )
        private_key = ec_module.generate_private_key(ec_module.SECP256R1())
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode('ascii')
        DeviceKeyMaterial.objects.create(device=device, private_key_pem=encrypt_private_key(pem))
        return org, device

    def _validated(self, payload, org):
        serializer = InvoiceSubmissionSerializer(data=payload, organization=org)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data, serializer.get_resolved_device()

    def _auth_header(self, org):
        return {'HTTP_AUTHORIZATION': f'ApiKey {org.api_key}'}

    @patch('invoices.pipeline.submit_to_zatca')
    def test_return_without_system_return_number_auto_generates_cn_number(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)
        self.assertEqual(invoice.icv, 1)

        credit_note = create_return_credit_note(org, device, invoice, reason='damaged goods')

        self.assertEqual(credit_note.icv, 2)
        self.assertEqual(credit_note.document_type, InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE)
        self.assertEqual(credit_note.original_invoice_id, invoice.pk)
        self.assertEqual(credit_note.system_return_number, '')
        self.assertEqual(credit_note.invoice_number, f'CN-{credit_note.icv}')
        self.assertEqual(credit_note.payload['invoice_number'], f'CN-{credit_note.icv}')
        self.assertEqual(credit_note.payload['billing_reference'], invoice.payload['invoice_number'])
        self.assertEqual(credit_note.status, InvoiceSubmission.STATUS_SUBMITTED)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_return_with_system_return_number_uses_it_as_invoice_number(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)

        credit_note = create_return_credit_note(
            org, device, invoice, system_return_number='SYS-99', reason='damaged goods',
        )

        self.assertEqual(credit_note.system_return_number, 'SYS-99')
        self.assertEqual(credit_note.invoice_number, 'SYS-99')
        self.assertEqual(credit_note.payload['invoice_number'], 'SYS-99')
        self.assertEqual(credit_note.payload['billing_reference'], invoice.payload['invoice_number'])
        self.assertEqual(credit_note.status, InvoiceSubmission.STATUS_SUBMITTED)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_return_with_duplicate_system_return_number_raises(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)
        create_return_credit_note(org, device, invoice, system_return_number='SYS-1')

        with self.assertRaises(DuplicateReturnNumberError):
            create_return_credit_note(org, device, invoice, system_return_number='SYS-1')

    @patch('invoices.pipeline.submit_to_zatca')
    def test_return_via_api_creates_credit_note(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)

        response = self.client.post(
            f'/api/invoices/{invoice.pk}/return/',
            data=json.dumps({'system_return_number': 'SYS-1', 'reason': 'test'}),
            content_type='application/json',
            **self._auth_header(org),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            InvoiceSubmission.objects.filter(document_type=InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE).count(), 1,
        )
        credit_note = InvoiceSubmission.objects.get(document_type=InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE)
        self.assertEqual(credit_note.original_invoice_id, invoice.pk)
        self.assertEqual(credit_note.system_return_number, 'SYS-1')
        self.assertEqual(credit_note.invoice_number, 'SYS-1')

    @patch('invoices.pipeline.submit_to_zatca')
    def test_return_via_api_with_duplicate_system_return_number_returns_400(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)
        create_return_credit_note(org, device, invoice, system_return_number='SYS-1')

        response = self.client.post(
            f'/api/invoices/{invoice.pk}/return/',
            data=json.dumps({'system_return_number': 'SYS-1'}),
            content_type='application/json',
            **self._auth_header(org),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('system_return_number', response.json())

    @patch('invoices.pipeline.submit_to_zatca')
    def test_return_via_api_cross_org_returns_404(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)

        other_org = Organization.objects.create(
            name='Other Org', branch_name='B', industry_category='IT',
            vat_number='399999999900044', country_code='SA',
            national_address_code='X', street_name='Y', building_number='2',
            city_sub_division='D', city_name='Jeddah', postal_zone='11111',
            cr_number='9999999998', invoice_category='1100', is_active=True,
        )

        response = self.client.post(
            f'/api/invoices/{invoice.pk}/return/',
            data=json.dumps({}),
            content_type='application/json',
            **self._auth_header(other_org),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            InvoiceSubmission.objects.filter(document_type=InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE).count(), 0,
        )


class InvoiceNumbersByDateViewTests(TestCase):

    def _make_org_with_device(self, **org_overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(org_overrides)
        org = Organization.objects.create(**defaults)
        device = Device.objects.create(
            organization=org,
            asset_id='ASSET-100',
            egs_sw_serial_number='SERIAL-200',
            otp='123456',
            csid_response=FAKE_CSID,
        )
        return org, device

    def _auth_header(self, org):
        return {'HTTP_AUTHORIZATION': f'ApiKey {org.api_key}'}

    def _make_submission(self, org, device, document_type, invoice_number, issue_date, icv):
        return InvoiceSubmission.objects.create(
            organization=org,
            device=device,
            document_type=document_type,
            invoice_number=invoice_number,
            payload={'invoice_number': invoice_number, 'issue_date': issue_date},
            status=InvoiceSubmission.STATUS_SUBMITTED,
            icv=icv,
        )

    def test_returns_all_document_types_when_no_filter_given(self):
        org, device = self._make_org_with_device()
        self._make_submission(org, device, 'invoice', 'INV-001', '2026-06-24', 1)
        self._make_submission(org, device, 'credit_note', 'CN-2', '2026-06-24', 2)
        self._make_submission(org, device, 'debit_note', 'DN-3', '2026-06-24', 3)
        self._make_submission(org, device, 'invoice', 'INV-OTHER-DAY', '2026-06-23', 4)

        response = self.client.get(
            '/api/invoices/numbers/', {'date': '2026-06-24'}, **self._auth_header(org),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['document_type'], 'all')
        self.assertEqual(body['count'], 3)
        self.assertEqual(set(body['invoice_numbers']), {'INV-001', 'CN-2', 'DN-3'})

    def test_filters_by_document_type(self):
        org, device = self._make_org_with_device()
        self._make_submission(org, device, 'invoice', 'INV-001', '2026-06-24', 1)
        self._make_submission(org, device, 'credit_note', 'CN-2', '2026-06-24', 2)

        response = self.client.get(
            '/api/invoices/numbers/', {'date': '2026-06-24', 'document_type': 'credit_note'},
            **self._auth_header(org),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['document_type'], 'credit_note')
        self.assertEqual(body['invoice_numbers'], ['CN-2'])

    def test_returns_empty_list_for_date_with_no_submissions(self):
        org, device = self._make_org_with_device()
        self._make_submission(org, device, 'invoice', 'INV-001', '2026-06-24', 1)

        response = self.client.get(
            '/api/invoices/numbers/', {'date': '2026-01-01'}, **self._auth_header(org),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['count'], 0)
        self.assertEqual(body['invoice_numbers'], [])

    def test_missing_date_returns_400(self):
        org, _ = self._make_org_with_device()

        response = self.client.get('/api/invoices/numbers/', **self._auth_header(org))

        self.assertEqual(response.status_code, 400)
        self.assertIn('date', response.json())

    def test_invalid_document_type_returns_400(self):
        org, _ = self._make_org_with_device()

        response = self.client.get(
            '/api/invoices/numbers/', {'date': '2026-06-24', 'document_type': 'bogus'},
            **self._auth_header(org),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('document_type', response.json())

    def test_does_not_leak_other_organizations_invoices(self):
        org, device = self._make_org_with_device()
        other_org, other_device = self._make_org_with_device(
            vat_number='399999999900055', cr_number='9999999955',
        )
        self._make_submission(org, device, 'invoice', 'INV-MINE', '2026-06-24', 1)
        self._make_submission(other_org, other_device, 'invoice', 'INV-OTHER', '2026-06-24', 1)

        response = self.client.get(
            '/api/invoices/numbers/', {'date': '2026-06-24'}, **self._auth_header(org),
        )

        self.assertEqual(response.json()['invoice_numbers'], ['INV-MINE'])

    def test_missing_api_key_returns_401(self):
        response = self.client.get('/api/invoices/numbers/', {'date': '2026-06-24'})

        self.assertEqual(response.status_code, 401)


class InvoiceResubmitViewTests(TestCase):

    def _make_org_with_signing_device(self, email='owner@example.com', **org_overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(org_overrides)
        user = User.objects.create_user(username=email, email=email, password='testpass123')
        org = Organization.objects.create(email=email, owner_user=user, **defaults)
        device = Device.objects.create(
            organization=org,
            asset_id='ASSET-100',
            egs_sw_serial_number='SERIAL-200',
            otp='123456',
            csid_response=FAKE_CSID,
        )
        private_key = ec_module.generate_private_key(ec_module.SECP256R1())
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode('ascii')
        DeviceKeyMaterial.objects.create(device=device, private_key_pem=encrypt_private_key(pem))
        return org, device, user

    def _validated(self, payload, org):
        serializer = InvoiceSubmissionSerializer(data=payload, organization=org)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data, serializer.get_resolved_device()

    @patch('invoices.pipeline.submit_to_zatca')
    def test_resubmit_not_submitted_invoice_marks_submitted(self, mock_submit):
        mock_submit.return_value = {'status_code': 400, 'error': 'boom'}
        org, device, user = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)
        self.assertEqual(invoice.status, InvoiceSubmission.STATUS_NOT_SUBMITTED)

        mock_submit.return_value = {'status_code': 200}
        self.client.force_login(user)
        response = self.client.post(reverse('organization:invoice-resubmit', args=[org.pk, invoice.pk]))

        self.assertRedirects(response, reverse('organization:invoice-list', args=[org.pk]))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceSubmission.STATUS_SUBMITTED)
        self.assertIsNotNone(invoice.submitted_at)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_resubmit_keeps_not_submitted_on_repeated_failure(self, mock_submit):
        mock_submit.return_value = {'status_code': 400, 'error': 'boom'}
        org, device, user = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)

        self.client.force_login(user)
        response = self.client.post(reverse('organization:invoice-resubmit', args=[org.pk, invoice.pk]))

        self.assertRedirects(response, reverse('organization:invoice-list', args=[org.pk]))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceSubmission.STATUS_NOT_SUBMITTED)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_resubmit_already_submitted_invoice_does_not_repost(self, mock_submit):
        mock_submit.return_value = {'status_code': 200}
        org, device, user = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)
        self.assertEqual(invoice.status, InvoiceSubmission.STATUS_SUBMITTED)
        mock_submit.reset_mock()

        self.client.force_login(user)
        response = self.client.post(reverse('organization:invoice-resubmit', args=[org.pk, invoice.pk]))

        self.assertRedirects(response, reverse('organization:invoice-list', args=[org.pk]))
        mock_submit.assert_not_called()

    @patch('invoices.pipeline.submit_to_zatca')
    def test_resubmit_cross_owner_returns_404(self, mock_submit):
        mock_submit.return_value = {'status_code': 400}
        org, device, _user = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)

        _other_org, _other_device, other_user = self._make_org_with_signing_device(
            email='other@example.com', vat_number='399999999900099', cr_number='9999999997',
        )
        self.client.force_login(other_user)

        response = self.client.post(reverse('organization:invoice-resubmit', args=[org.pk, invoice.pk]))

        self.assertEqual(response.status_code, 404)

    @patch('invoices.pipeline.submit_to_zatca')
    def test_resubmit_anonymous_redirected_to_login(self, mock_submit):
        mock_submit.return_value = {'status_code': 400}
        org, device, _user = self._make_org_with_signing_device()
        validated_data, resolved_device = self._validated(VALID_PAYLOAD, org)
        invoice = process_invoice_submission(org, resolved_device, validated_data)

        response = self.client.post(reverse('organization:invoice-resubmit', args=[org.pk, invoice.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)


class InvoiceListViewTests(TestCase):

    def _make_org_with_device(self, email='owner@example.com', **org_overrides):
        defaults = {**ORG_DEFAULTS}
        defaults.update(org_overrides)
        user = User.objects.create_user(username=email, email=email, password='testpass123')
        org = Organization.objects.create(email=email, owner_user=user, **defaults)
        device = Device.objects.create(
            organization=org,
            asset_id='ASSET-100',
            egs_sw_serial_number='SERIAL-200',
            otp='123456',
            csid_response=FAKE_CSID,
        )
        return org, device, user

    def _make_submission(self, org, device, icv, **payload_overrides):
        payload = {
            'invoice_number': f'INV-{icv:03d}',
            'issue_date': '2026-06-24',
            'customer_name': 'Test Customer',
        }
        payload.update(payload_overrides)
        return InvoiceSubmission.objects.create(
            organization=org,
            device=device,
            document_type=payload_overrides.get('document_type', InvoiceSubmission.DOCUMENT_TYPE_INVOICE),
            invoice_number=payload['invoice_number'],
            payload=payload,
            status=payload_overrides.get('status', InvoiceSubmission.STATUS_SUBMITTED),
            icv=icv,
        )

    def test_filters_by_invoice_number(self):
        org, device, user = self._make_org_with_device()
        self._make_submission(org, device, 1, invoice_number='INV-AAA')
        self._make_submission(org, device, 2, invoice_number='INV-BBB')
        self.client.force_login(user)

        response = self.client.get(
            reverse('organization:invoice-list', args=[org.pk]), {'invoice_number': 'AAA'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([i.icv for i in response.context['invoices']], [1])

    def test_filters_by_customer_name(self):
        org, device, user = self._make_org_with_device()
        self._make_submission(org, device, 1, customer_name='Acme Corp')
        self._make_submission(org, device, 2, customer_name='Beta LLC')
        self.client.force_login(user)

        response = self.client.get(
            reverse('organization:invoice-list', args=[org.pk]), {'customer_name': 'acme'},
        )

        self.assertEqual([i.icv for i in response.context['invoices']], [1])

    def test_filters_by_issue_date(self):
        org, device, user = self._make_org_with_device()
        self._make_submission(org, device, 1, issue_date='2026-06-24')
        self._make_submission(org, device, 2, issue_date='2026-06-25')
        self.client.force_login(user)

        response = self.client.get(
            reverse('organization:invoice-list', args=[org.pk]), {'issue_date': '2026-06-25'},
        )

        self.assertEqual([i.icv for i in response.context['invoices']], [2])

    def test_filters_by_icv(self):
        org, device, user = self._make_org_with_device()
        self._make_submission(org, device, 1)
        self._make_submission(org, device, 2)
        self.client.force_login(user)

        response = self.client.get(reverse('organization:invoice-list', args=[org.pk]), {'icv': '2'})

        self.assertEqual([i.icv for i in response.context['invoices']], [2])

    def test_filters_by_document_type(self):
        org, device, user = self._make_org_with_device()
        self._make_submission(org, device, 1, document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE)
        self._make_submission(org, device, 2, document_type=InvoiceSubmission.DOCUMENT_TYPE_CREDIT_NOTE)
        self.client.force_login(user)

        response = self.client.get(
            reverse('organization:invoice-list', args=[org.pk]), {'document_type': 'credit_note'},
        )

        self.assertEqual([i.icv for i in response.context['invoices']], [2])

    def test_filters_by_status(self):
        org, device, user = self._make_org_with_device()
        self._make_submission(org, device, 1, status=InvoiceSubmission.STATUS_SUBMITTED)
        self._make_submission(org, device, 2, status=InvoiceSubmission.STATUS_NOT_SUBMITTED)
        self.client.force_login(user)

        response = self.client.get(
            reverse('organization:invoice-list', args=[org.pk]), {'status': 'not_submitted'},
        )

        self.assertEqual([i.icv for i in response.context['invoices']], [2])

    def test_pagination_splits_across_pages(self):
        org, device, user = self._make_org_with_device()
        for icv in range(1, 31):
            self._make_submission(org, device, icv)
        self.client.force_login(user)

        page1 = self.client.get(reverse('organization:invoice-list', args=[org.pk]))
        page2 = self.client.get(reverse('organization:invoice-list', args=[org.pk]), {'page': 2})

        self.assertEqual(len(page1.context['invoices']), 25)
        self.assertTrue(page1.context['is_paginated'])
        self.assertEqual(len(page2.context['invoices']), 5)

    def test_does_not_leak_other_organizations_invoices(self):
        org, device, user = self._make_org_with_device()
        other_org, other_device, _other_user = self._make_org_with_device(
            email='other@example.com', vat_number='399999999900098', cr_number='9999999996',
        )
        self._make_submission(org, device, 1)
        self._make_submission(other_org, other_device, 1)
        self.client.force_login(user)

        response = self.client.get(reverse('organization:invoice-list', args=[org.pk]))

        self.assertEqual(len(response.context['invoices']), 1)
