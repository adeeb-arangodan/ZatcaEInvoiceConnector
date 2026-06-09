import json
import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase

from organization.models import Device, Organization

from .models import InvoiceSubmission

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
    'binarySecurityToken': 'dGVzdHRva2Vu',
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

    def test_empty_items_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {**VALID_PAYLOAD, 'items': []}
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('items', response.json())

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
