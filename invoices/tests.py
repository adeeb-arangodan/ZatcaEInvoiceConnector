import json

from django.test import TestCase

from organization.models import Device, Organization

from .models import InvoiceSubmission

SUBMIT_URL = '/api/invoices/submit/'

VALID_PAYLOAD = {
    'device_asset_id': 'ASSET-100',
    'document_type': 'invoice',
    'invoice_number': 'INV-001',
    'issue_date': '2026-06-06',
    'issue_time': '10:00:00',
    'line_items': [
        {
            'description': 'Consultation',
            'quantity': '1.0000',
            'unit_price': '100.0000',
            'tax_percent': '15.00',
        }
    ],
    'tax_total': '15.00',
    'payable_amount': '115.00',
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

    def test_valid_invoice_returns_201(self):
        org, _ = self._make_org_with_device()
        response = self._post(VALID_PAYLOAD, org)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn('id', body)
        self.assertEqual(body['status'], 'received')
        self.assertEqual(body['message'], 'Invoice received and queued for processing.')

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
        payload = {**VALID_PAYLOAD, 'document_type': 'credit_note'}
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('billing_reference', response.json())

    def test_debit_note_without_billing_reference_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {**VALID_PAYLOAD, 'document_type': 'debit_note'}
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('billing_reference', response.json())

    def test_empty_line_items_returns_400(self):
        org, _ = self._make_org_with_device()
        payload = {**VALID_PAYLOAD, 'line_items': []}
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 400)
        self.assertIn('line_items', response.json())

    def test_submission_creates_db_record(self):
        org, device = self._make_org_with_device()
        self._post(VALID_PAYLOAD, org)
        self.assertEqual(InvoiceSubmission.objects.count(), 1)
        submission = InvoiceSubmission.objects.get()
        self.assertEqual(submission.organization, org)
        self.assertEqual(submission.device, device)
        self.assertEqual(submission.document_type, 'invoice')
        self.assertEqual(submission.status, 'received')

    def test_credit_note_with_billing_reference_returns_201(self):
        org, _ = self._make_org_with_device()
        payload = {**VALID_PAYLOAD, 'document_type': 'credit_note', 'billing_reference': 'INV-001'}
        response = self._post(payload, org)
        self.assertEqual(response.status_code, 201)


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
