# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Django application that acts as a middleware connector between external ERP/accounting systems and Saudi Arabia's ZATCA Phase 2 e-invoicing platform. External systems POST invoice JSON → this app transforms it to UBL 2.1 XML, signs it, submits to ZATCA, and returns a QR code.

## Commands

All commands assume the `.venv` is activated. On Windows use `.venv\Scripts\activate`.

```bash
# Run dev server
python manage.py runserver

# Run all tests
python manage.py test

# Run tests for a specific app
python manage.py test invoices
python manage.py test organization

# Run a single test
python manage.py test invoices.tests.InvoiceSubmitViewTests.test_valid_invoice_returns_201

# Create and apply migrations
python manage.py makemigrations <app_name>
python manage.py migrate

# Create superuser (needed to access /admin/ and activate organizations)
python manage.py createsuperuser
```

## Required Environment Variables

```
DEVICE_KEY_ENCRYPTION_KEY   # Fernet key — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ZATCA_SERVER_URL             # Default: https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal
ZATCA_COMPLIANCE_API_ENDPOINT # Default: /compliance
ZATCA_API_ACCEPT_VERSION     # Default: V2
ZATCA_API_TIMEOUT_SECONDS    # Default: 30
```

`openssl` must also be on PATH — used to generate EC keypairs and CSR documents for devices.

## Architecture

### Apps

**`organization/`** — Organization and device lifecycle management (UI + business rules)
- `models.py` — `Organization`, `Device`, `DeviceKeyMaterial`
- `services.py` — All crypto/ZATCA onboarding logic: EC keypair generation via OpenSSL subprocess, CSR building with ZATCA-specific X.509 extensions, private key encryption at rest (Fernet), compliance CSID registration against ZATCA API
- `views.py` — Template-based CBVs for CRUD; device creation triggers CSR generation + ZATCA registration
- `admin.py` — Admin actions: activate/deactivate orgs, regenerate API keys

**`invoices/`** — REST API for invoice submission
- `authentication.py` — `OrganizationApiKeyAuthentication`: reads `Authorization: ApiKey <token>`, sets `request.user` to the matching `Organization` instance
- `permissions.py` — `IsActiveOrganization`: gates all API access to active orgs
- `serializers.py` — `InvoiceSubmissionSerializer`: validates device ownership, billing reference rules for credit/debit notes, line items
- `views.py` — `InvoiceSubmitView` (`POST /api/invoices/submit/`): validates, persists `InvoiceSubmission`, returns stub 201 response
- `models.py` — `InvoiceSubmission`: persists raw payload + status lifecycle (`received` → `processing` → `submitted`/`rejected`)

### Key Design Decisions

**Authentication**: API key per organization (not per user or device). The `Organization.api_key` field is auto-generated as `secrets.token_hex(32)` on first save. Pass in `Authorization: ApiKey <token>` header. DRF is configured with empty default auth/permission classes — each view declares its own via `authentication_classes` and `permission_classes`.

**Organization activation gate**: Organizations start with `is_active=False`. Admin must activate before devices can be registered or invoices submitted. `DeviceCreateView.dispatch` enforces this with a redirect + flash message. `IsActiveOrganization` permission enforces it on the API.

**Device keys**: EC private keys (prime256v1) are encrypted at rest using Fernet before storage in `DeviceKeyMaterial.private_key_pem`. Use `services.decrypt_private_key()` when the raw PEM is needed (e.g. for signing).

**ZATCA onboarding flow** (already implemented): `ensure_device_keys()` → `generate_device_csr()` → `register_device_in_zatca()` — called automatically when a device is created through the UI. The resulting CSID response is stored in `Device.csid_response`.

### URL Structure

```
/admin/                                         Django admin
/                                               Organization list (template UI)
/organizations/add/                             Create org
/organizations/<pk>/edit/                       Edit org (blocked if devices exist)
/organizations/<pk>/devices/add/                Add device (blocked if org inactive)
POST /api/invoices/submit/                      Invoice submission API endpoint
```

### What Is Not Yet Implemented (Phase 4+)

- JSON → UBL 2.1 XML transformation
- Previous invoice hash (PIH) chaining
- Invoice counter (ICV) per device
- QR code generation (TLV-encoded)
- Cryptographic stamp + XML signature using device certificate
- Submission to ZATCA reporting/clearance endpoint

The `InvoiceSubmission.status` field will drive this pipeline. Currently all submissions land in `received` status as a stub.

### Test Patterns

Tests use `django.test.TestCase` and `unittest.mock.patch`. There are no shared fixtures — each test creates its own objects inline. API tests always pass `content_type='application/json'` with `json.dumps(payload)` to the test client. See `invoices/tests.py` for the API test helper pattern (`_make_org_with_device`, `_auth_header`).

ZATCA API calls and OpenSSL subprocess calls are mocked in `organization/tests.py` — follow the same approach for any new external calls.
