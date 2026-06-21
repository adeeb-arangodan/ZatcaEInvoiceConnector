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
ZATCA_COMPLIANCE_INVOICE_CHECK_API_ENDPOINT # Default: /compliance/invoices/reporting/single
ZATCA_PRODUCTION_CSID_API_ENDPOINT          # Default: /production/csids
ZATCA_REPORTING_API_ENDPOINT                # Default: /invoices/reporting/single
ZATCA_CLEARANCE_API_ENDPOINT                # Default: /invoices/clearance/single
```

`openssl` must also be on PATH — used to generate EC keypairs and CSR documents for devices.

## Architecture

### Apps

**`organization/`** — Organization and device lifecycle management (UI + business rules)
- `models.py` — `Organization` (also owns the ICV/PIH invoice counter chain: `invoice_counter`, `last_invoice_hash`), `Device` (`csid_response`, `pcsid`), `DeviceKeyMaterial`
- `services.py` — All crypto/ZATCA onboarding logic: EC keypair generation via OpenSSL subprocess, CSR building with ZATCA-specific X.509 extensions, private key encryption at rest (Fernet), compliance CSID registration, compliance invoice check, and `acquire_pcsid_for_device()` for production CSID (PCSID) issuance
- `views.py` — Template-based CBVs for CRUD; device creation triggers CSR generation + ZATCA registration
- `admin.py` — Admin actions: activate/deactivate orgs, regenerate API keys

**`invoices/`** — REST API + full invoice submission pipeline
- `authentication.py` — `OrganizationApiKeyAuthentication`: reads `Authorization: ApiKey <token>`, sets `request.user` to the matching `Organization` instance
- `permissions.py` — `IsActiveOrganization`: gates all API access to active orgs
- `serializers.py` — `InvoiceSubmissionSerializer`: validates device ownership, billing reference rules for credit/debit notes, line items
- `views.py` — `InvoiceSubmitView` (`POST /api/invoices/submit/`): validates, resolves device, runs the pipeline, returns the ZATCA result
- `pipeline.py` — `process_invoice_submission()`: orchestrates the full flow (see "Invoice Submission Pipeline" below) and persists the `InvoiceSubmission`
- `xml_builder.py` — Builds UBL 2.1 XML by hand via `lxml` (parties, tax totals, lines, ICV/PIH/QR placeholders); also builds the compliance sample invoice used during device onboarding
- `hashing.py` — Exclusive-C14N + SHA-256 invoice hashing; atomic ICV increment + PIH read/write scoped to `Organization`
- `signing.py` — ECDSA-SHA256 signing of the invoice hash using the device's decrypted private key; builds the XAdES `ds:Signature` block and injects it into `ext:ExtensionContent`
- `qr.py` — TLV-encodes the 8 ZATCA QR fields and base64-encodes the result
- `submission.py` — POSTs the signed invoice to ZATCA's reporting (simplified) or clearance (standard) endpoint using Basic auth built from the device's CSID/PCSID credential
- `models.py` — `InvoiceSubmission`: persists raw payload, generated XML, hash, QR data, ZATCA response, and status lifecycle (`received` → `processing` → `submitted`/`rejected`)

### Key Design Decisions

**Authentication**: API key per organization (not per user or device). The `Organization.api_key` field is auto-generated as `secrets.token_hex(32)` on first save. Pass in `Authorization: ApiKey <token>` header. DRF is configured with empty default auth/permission classes — each view declares its own via `authentication_classes` and `permission_classes`.

**Organization activation gate**: Organizations start with `is_active=False`. Admin must activate before devices can be registered or invoices submitted. `DeviceCreateView.dispatch` enforces this with a redirect + flash message. `IsActiveOrganization` permission enforces it on the API.

**Device keys**: EC private keys (prime256v1) are encrypted at rest using Fernet before storage in `DeviceKeyMaterial.private_key_pem`. Use `services.decrypt_private_key()` when the raw PEM is needed (e.g. for signing).

**ZATCA onboarding flow**: `ensure_device_keys()` → `generate_device_csr()` → `register_device_in_zatca()` — called automatically when a device is created through the UI. The resulting CSID response is stored in `Device.csid_response`. `acquire_pcsid_for_device()` runs a compliance invoice check against the CSID and, on success, stores the upgraded production credential in `Device.pcsid`.

**Credential precedence**: Both `signing.py` and `submission.py` prefer `device.pcsid` when it contains a `binarySecurityToken`, falling back to `device.csid_response` otherwise. A device can submit real invoices with just a CSID, but PCSID is the production-grade credential once acquired.

**ICV/PIH chain is per-Organization, not per-Device**: `hashing.get_icv_and_pih_atomically()` locks the `Organization` row (`select_for_update`) and increments `Organization.invoice_counter`/reads `Organization.last_invoice_hash`. This means all devices under one organization (branch) share a single invoice counter chain. `last_invoice_hash` only advances when ZATCA accepts the submission — a rejected invoice doesn't poison the chain for the next one.

### URL Structure

```
/admin/                                         Django admin
/                                               Organization list (template UI)
/organizations/add/                             Create org
/organizations/<pk>/edit/                       Edit org (blocked if devices exist)
/organizations/<pk>/devices/add/                Add device (blocked if org inactive)
POST /api/invoices/submit/                      Invoice submission API endpoint
```

### Invoice Submission Pipeline (Phase 4, implemented)

`process_invoice_submission()` in `invoices/pipeline.py` runs, per request:

1. `hashing.get_icv_and_pih_atomically(organization)` — atomically bump ICV and fetch PIH (see "ICV/PIH chain" above).
2. `xml_builder.build_invoice_xml()` — build the UBL 2.1 XML with ICV/PIH/QR placeholders.
3. `hashing.hash_invoice_xml()` — exclusive C14N canonicalization + SHA-256, base64-encoded.
4. `signing.sign_invoice_xml()` — ECDSA-SHA256 signature over the hash, embedded as an XAdES block.
5. `qr.generate_qr_tlv()` — TLV-encode the 8 ZATCA QR fields.
6. `xml_builder.embed_qr_in_xml()` — patch the QR placeholder with the real TLV data.
7. `submission.submit_to_zatca()` — POST to the reporting (simplified) or clearance (standard) endpoint, chosen by whether `invoice_type_code_name_attribute` starts with `0`.
8. Persist the `InvoiceSubmission` with status `submitted` or `rejected`; only advance `last_invoice_hash` on acceptance.

What's still missing: nothing structural — this is the full Phase 4 pipeline. Future work would be around hardening (retry/backoff on ZATCA timeouts, more granular validation errors) rather than new pipeline stages.

### Test Patterns

Tests use `django.test.TestCase` and `unittest.mock.patch`. There are no shared fixtures — each test creates its own objects inline. API tests always pass `content_type='application/json'` with `json.dumps(payload)` to the test client. See `invoices/tests.py` for the API test helper pattern (`_make_org_with_device`, `_auth_header`).

ZATCA API calls and OpenSSL subprocess calls are mocked in `organization/tests.py` — follow the same approach for any new external calls.
