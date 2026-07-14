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
- `views_template.py` — org-scoped template UI: `InvoiceListView` (filterable, paginated list, with a page-wise/all-pages amount summary and an Excel export via `InvoiceExportView`), `ReturnInvoiceFormView` (credit-note return), `InvoiceResubmitView` (retry a legacy `not_submitted` row), `FailedSubmissionListView`/`FailedSubmissionResubmitView` (view and retry ZATCA-rejected attempts — see "Invoice Submission Pipeline" below); all wired from `organization/urls.py`, not `invoices/urls.py` (see "URL Structure")
- `pipeline.py` — `process_invoice_submission()`: orchestrates the full flow (see "Invoice Submission Pipeline" below), persists the `InvoiceSubmission` on success, or raises `InvoiceSubmissionRejected` on ZATCA rejection after rolling back the whole attempt
- `xml_builder.py` — Builds UBL 2.1 XML by hand via `lxml` (parties, tax totals, lines, ICV/PIH/QR placeholders); also builds the compliance sample invoice used during device onboarding
- `hashing.py` — Exclusive-C14N + SHA-256 invoice hashing; atomic ICV increment + PIH read/write scoped to `Organization`
- `signing.py` — ECDSA-SHA256 signing of the invoice hash using the device's decrypted private key; builds the XAdES `ds:Signature` block and injects it into `ext:ExtensionContent`
- `qr.py` — TLV-encodes the 8 ZATCA QR fields and base64-encodes the result
- `submission.py` — POSTs the signed invoice to ZATCA's reporting (simplified) or clearance (standard) endpoint using Basic auth built from the device's CSID/PCSID credential
- `models.py` — `InvoiceSubmission`: persists raw payload, assigned `icv`, generated XML, hash, QR data, ZATCA response, and status lifecycle (`received` → `processing` → `submitted`/`not_submitted`); `InvoiceSubmissionFailure`: a ZATCA-rejected attempt that never consumed an ICV (payload, ZATCA error, `resolved` flag) — created instead of an `InvoiceSubmission` row when ZATCA rejects

### Key Design Decisions

**Authentication**: API key per organization (not per user or device). The `Organization.api_key` field is auto-generated as `secrets.token_hex(32)` on first save. Pass in `Authorization: ApiKey <token>` header. DRF is configured with empty default auth/permission classes — each view declares its own via `authentication_classes` and `permission_classes`.

**Organization activation gate**: Organizations start with `is_active=False`. Admin must activate before devices can be registered or invoices submitted. `DeviceCreateView.dispatch` enforces this with a redirect + flash message. `IsActiveOrganization` permission enforces it on the API.

**Device keys**: EC private keys (secp256k1, per ZATCA's required curve) are encrypted at rest using Fernet before storage in `DeviceKeyMaterial.private_key_pem`. Use `services.decrypt_private_key()` when the raw PEM is needed (e.g. for signing).

**ZATCA onboarding flow**: `ensure_device_keys()` → `generate_device_csr()` → `register_device_in_zatca()` — called automatically when a device is created through the UI. The resulting CSID response is stored in `Device.csid_response`. `acquire_pcsid_for_device()` runs a compliance invoice check against the CSID and, on success, stores the upgraded production credential in `Device.pcsid`.

**Credential precedence**: Both `signing.py` and `submission.py` prefer `device.pcsid` when it contains a `binarySecurityToken`, falling back to `device.csid_response` otherwise. A device can submit real invoices with just a CSID, but PCSID is the production-grade credential once acquired.

**ICV/PIH chain is per-Organization, not per-Device**: `hashing.get_icv_and_pih_atomically()` locks the `Organization` row (`select_for_update`) and increments `Organization.invoice_counter`/reads `Organization.last_invoice_hash`. This means all devices under one organization (branch) share a single invoice counter chain — and it also means all document types (invoices, credit notes, debit notes) share one chain, not separate ones per type (confirmed intentional).

`last_invoice_hash` only advances once **ZATCA has accepted** the invoice, not merely once it's locally generated. This is deliberate and non-obvious: ZATCA tracks the last ICV/hash it *accepted* on its own side. If our chain advanced on an invoice ZATCA went on to reject, every invoice submitted afterward would carry an ICV/PIH built on a hash ZATCA never accepted — an unreconcilable gap that gets every subsequent invoice rejected too, cascading indefinitely until the original gap is somehow fixed. So `process_invoice_submission()` holds the `Organization` row lock for the *entire* attempt now — local XML build/hash/sign **and** the ZATCA network call — inside one `transaction.atomic()`. If ZATCA rejects, `transaction.set_rollback(True)` undoes everything (the ICV increment, the `InvoiceSubmission` row); nothing was consumed, so a corrected retry gets the exact same ICV. See "Invoice Submission Pipeline" below.

**Accepted tradeoff**: the lock now spans a network call (up to `ZATCA_API_TIMEOUT_SECONDS`, though real calls are far faster), not just milliseconds of local work, so concurrent submissions for the same organization serialize behind whichever one is mid-flight. On SQLite this is felt as a whole-database-file write lock for that duration (not just the one row), not just this one organization's traffic — accepted for now given current volume; revisit if this becomes a bottleneck, and see `docs/Deployment Docs/postgresql-migration.md` for the row-level-locking alternative.

### URL Structure

```
/admin/                                         Django admin
/                                               Organization list (template UI)
/organizations/add/                             Create org
/organizations/<pk>/edit/                       Edit org (blocked if devices exist)
/organizations/<pk>/devices/add/                Add device (blocked if org inactive)
/organizations/<pk>/invoices/                   Invoice list (filterable, paginated) — organization:invoice-list
/organizations/<pk>/invoices/<id>/return/        Return an invoice as a credit note — organization:invoice-return
/organizations/<pk>/invoices/<id>/resubmit/      Retry ZATCA delivery for a legacy not_submitted row — organization:invoice-resubmit
/organizations/<pk>/invoices/export/            Export the filtered invoice list to Excel — organization:invoice-export
/organizations/<pk>/invoices/failed/            Failed Submissions list (ZATCA-rejected, ICV never consumed) — organization:failed-submission-list
/organizations/<pk>/invoices/failed/<id>/resubmit/  Correct + resubmit a failed submission — organization:failed-submission-resubmit
POST /api/invoices/submit/                      Invoice submission API endpoint
```

### Invoice Submission Pipeline (Phase 4, implemented)

`process_invoice_submission()` in `invoices/pipeline.py` runs the whole attempt — local generation *and* ZATCA submission — inside one `transaction.atomic()` holding the `Organization` row lock (see "ICV/PIH chain" above for why):

1. `hashing.get_icv_and_pih_atomically(organization)` — atomically bump ICV and fetch PIH.
2. Create the `InvoiceSubmission` row (`payload`, `device`, `icv`, status `processing`).
3. `xml_builder.build_invoice_xml()` — build the UBL 2.1 XML with ICV/PIH/QR placeholders.
4. `hashing.hash_invoice_xml()` — exclusive C14N canonicalization + SHA-256, base64-encoded.
5. `signing.sign_invoice_xml()` — ECDSA-SHA256 signature over the hash, embedded as an XAdES block.
6. `qr.generate_qr_tlv()` + `xml_builder.embed_qr_in_xml()` — TLV-encode the 8 ZATCA QR fields and patch them into the XML.
7. Save `xml_document`/`invoice_hash`/`qr_code_data` onto the row.
8. `submission.submit_to_zatca()` — POST to the reporting (simplified) or clearance (standard) endpoint, chosen by whether `invoice_type_code_name_attribute` starts with `0`.
9. **If ZATCA accepts**: set `status=submitted`, save `zatca_response`/`submitted_at`, then `hashing.store_invoice_hash()` to advance `Organization.last_invoice_hash`. Return the `InvoiceSubmission`.
10. **If ZATCA rejects** (or the call errors/times out): `transaction.set_rollback(True)` — undoes the ICV increment and the `InvoiceSubmission` row created in step 2, as if the attempt never happened. Outside the (now rolled-back) transaction, an `InvoiceSubmissionFailure` row is created instead (org, device, document_type, payload, ZATCA error), and `InvoiceSubmissionRejected(failure)` is raised to the caller. A retry — even seconds later — gets the exact same ICV, since nothing was consumed.

Callers that invoke this directly (`InvoiceSubmitView`, `InvoiceReturnView`, `ReturnInvoiceFormView`, `create_return_credit_note()`) must catch `InvoiceSubmissionRejected` and handle `exc.failure` — there is no longer a "submission with not_submitted status" to fall back to for a *new* rejection.

**Fixing a rejection**: correct `InvoiceSubmissionFailure.payload` (currently via Django admin — `payload`/`invoice_number` are editable there by design) and click Resubmit on the org-scoped Failed Submissions page (`FailedSubmissionListView`/`FailedSubmissionResubmitView`, wired at `organizations/<pk>/invoices/failed/`). Resubmitting re-validates the payload through `InvoiceSubmissionSerializer` and calls `process_invoice_submission()` fresh — a normal new attempt, not a special-cased retry, so it naturally lands on whatever ICV is next. On success the failure row is marked `resolved` and linked to the resulting `InvoiceSubmission` via `resolved_submission`.

**Legacy `not_submitted` rows**: `InvoiceSubmission` rows with `status=not_submitted` created *before* this design (when Phase A/B were split and the chain advanced regardless of ZATCA's response) still exist and still work via the original path — `pipeline.deliver_to_zatca(submission)` re-POSTs the already-signed `xml_document`/`invoice_hash` unchanged, exposed as the "Resubmit" button (`InvoiceResubmitView`, `organization:invoice-resubmit`) on the invoice list for any row with that status. This is untouched by the above; it's not fed by new rejections going forward, since those now become `InvoiceSubmissionFailure` rows instead of `not_submitted` ones.

What's still missing: general hardening (retry/backoff on ZATCA timeouts, more granular validation errors).

### Invoice List Filtering & Pagination

`InvoiceListView` (`invoices/views_template.py`) filters via GET query params — `invoice_number`, `customer_name` (both `icontains`), `icv`, `document_type`, `status` (exact match), and an `issue_date_from`/`issue_date_to` inclusive range. The date range and `customer_name` filters query into the JSON `payload` field (`payload__issue_date__gte`, `payload__customer_name__icontains`) since those aren't dedicated columns on `InvoiceSubmission`.

On a cold page load with **no query string at all** (e.g. the "View Invoices" dashboard link), `issue_date_from`/`issue_date_to` both default to today — this avoids loading an organization's entire invoice history by default as volume grows over time. Submitting the filter form (even filtering by an unrelated field like `invoice_number` with the date fields left blank) is treated as an explicit choice and does **not** get an implicit today-only constraint bolted on. The list is paginated at 25/page (`paginate_by`), and pagination happens before the per-row totals/remarks computation (`_attach_totals`/`_attach_remarks`) so that work only runs for the current page's rows, not the full filtered set.

### Test Patterns

Tests use `django.test.TestCase` and `unittest.mock.patch`. There are no shared fixtures — each test creates its own objects inline. API tests always pass `content_type='application/json'` with `json.dumps(payload)` to the test client. See `invoices/tests.py` for the API test helper pattern (`_make_org_with_device`, `_auth_header`).

ZATCA API calls and OpenSSL subprocess calls are mocked in `organization/tests.py` — follow the same approach for any new external calls.
