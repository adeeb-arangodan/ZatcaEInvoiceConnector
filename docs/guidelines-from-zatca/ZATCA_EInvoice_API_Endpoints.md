# ZATCA E-Invoice API Endpoints Reference

## Overview
ZATCA (Zakat, Tax and Customs Authority) provides two environments for E-Invoice Phase 2 integration: **Simulation** (for testing) and **Production** (for live invoicing).

---

## 1. Simulation Environment

### Base URL
```
https://apesrv.zatca.gov.sa
```

### Key Endpoints

#### 1.1 Onboarding Phase 1: Request OTP
**Endpoint:** `POST /v1/compliance/otp`

Requests a One-Time Password (OTP) for onboarding.

**Headers:**
```
Content-Type: application/json
```

**Request Body:**
```json
{
  "otp": "123456"
}
```

**Response:** OTP sent to registered mobile/email

---

#### 1.2 Onboarding Phase 2: Submit CSR (Certificate Signing Request)
**Endpoint:** `POST /v1/compliance/csrs`

Submits a PKCS#10 CSR to get the compliance certificate.

**Headers:**
```
Content-Type: application/json
```

**Request Body:**
```json
{
  "csr": "-----BEGIN CERTIFICATE REQUEST-----\n...\n-----END CERTIFICATE REQUEST-----"
}
```

**Response:**
```json
{
  "requestId": "request-id-uuid",
  "status": "ACCEPTED"
}
```

---

#### 1.3 Get CSR Status / Retrieve Certificate
**Endpoint:** `GET /v1/compliance/csrs/{requestId}`

Retrieves the status of CSR submission and the issued certificate.

**Response (Success):**
```json
{
  "requestId": "request-id-uuid",
  "status": "ISSUED",
  "certificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
}
```

---

#### 1.4 Submit Compliance Invoice
**Endpoint:** `POST /v1/compliance/invoices`

Submits an invoice for compliance check during Phase 1.

**Headers:**
```
Content-Type: application/json
Authorization: Bearer {accessToken}
```

**Request Body:**
```json
{
  "invoiceHash": "NWZlY2M2NmZmM2NhNTNmNTdkYTkzNzMyZTgwNTBkMDI=",
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "invoice": "-----BEGIN INVOICE-----\n...\n-----END INVOICE-----"
}
```

**Response:**
```json
{
  "reportingStatus": "COMPLIANT",
  "clearanceStatus": "NOT_CLEARED",
  "warnings": []
}
```

---

#### 1.5 Get Invoice Details
**Endpoint:** `GET /v1/compliance/invoices/{uuid}`

Retrieves the compliance status of a submitted invoice.

**Response:**
```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "reportingStatus": "COMPLIANT",
  "clearanceStatus": "NOT_CLEARED",
  "warnings": [],
  "invoiceHash": "NWZlY2M2NmZmM2NhNTNmNTdkYTkzNzMyZTgwNTBkMDI="
}
```

---

#### 1.6 Report Debit/Credit Memo
**Endpoint:** `POST /v1/compliance/debit-credit-notes`

Submits debit or credit memos for compliance.

**Headers:**
```
Content-Type: application/json
Authorization: Bearer {accessToken}
```

**Request Body:**
```json
{
  "debitCreditNoteHash": "...",
  "uuid": "...",
  "invoice": "..."
}
```

---

#### 1.7 Submit Standard Invoice (Clearance)
**Endpoint:** `POST /v1/invoices/clearance/single`

Submits a standard invoice for reporting and clearance.

**Headers:**
```
Content-Type: application/json
Authorization: Bearer {accessToken}
Digest: SHA-256={base64EncodedHash}
Signature: {base64EncodedSignature}
```

**Request Body:**
```json
{
  "invoiceHash": "NWZlY2M2NmZmM2NhNTNmNTdkYTkzNzMyZTgwNTBkMDI=",
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "invoice": "-----BEGIN INVOICE-----\n...\n-----END INVOICE-----"
}
```

**Response:**
```json
{
  "reportingStatus": "REPORTED",
  "clearanceStatus": "CLEARED",
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "warnings": []
}
```

---

#### 1.8 Get Invoice Status
**Endpoint:** `GET /v1/invoices/clearance/single/{uuid}`

Retrieves the reporting and clearance status of an invoice.

**Response:**
```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "reportingStatus": "REPORTED",
  "clearanceStatus": "CLEARED",
  "warnings": []
}
```

---

#### 1.9 Get Invoice PDF
**Endpoint:** `GET /v1/invoices/clearance/single/{uuid}/pdf`

Downloads the PDF of a reported/cleared invoice.

**Response:** Binary PDF file

---

#### 1.10 Check Invoice Status (Batch)
**Endpoint:** `POST /v1/invoices/clearance/status`

Checks the status of multiple invoices at once.

**Headers:**
```
Content-Type: application/json
Authorization: Bearer {accessToken}
```

**Request Body:**
```json
{
  "invoiceHashes": [
    "NWZlY2M2NmZmM2NhNTNmNTdkYTkzNzMyZTgwNTBkMDI=",
    "..."
  ]
}
```

**Response:**
```json
{
  "invoices": [
    {
      "invoiceHash": "NWZlY2M2NmZmM2NhNTNmNTdkYTkzNzMyZTgwNTBkMDI=",
      "uuid": "550e8400-e29b-41d4-a716-446655440000",
      "reportingStatus": "REPORTED",
      "clearanceStatus": "CLEARED"
    }
  ]
}
```

---

## 2. Production Environment

### Base URL
```
https://api.zatca.gov.sa
```

### Key Endpoints

All endpoints follow the **same structure** as the simulation environment, with the following path mappings:

| Endpoint | Production URL |
|----------|---|
| OTP Request | `POST /v1/compliance/otp` |
| CSR Submission | `POST /v1/compliance/csrs` |
| Get CSR Status | `GET /v1/compliance/csrs/{requestId}` |
| Compliance Invoice | `POST /v1/compliance/invoices` |
| Get Invoice Details | `GET /v1/compliance/invoices/{uuid}` |
| Debit/Credit Memo | `POST /v1/compliance/debit-credit-notes` |
| Submit Invoice (Clearance) | `POST /v1/invoices/clearance/single` |
| Get Invoice Status | `GET /v1/invoices/clearance/single/{uuid}` |
| Get Invoice PDF | `GET /v1/invoices/clearance/single/{uuid}/pdf` |
| Batch Status Check | `POST /v1/invoices/clearance/status` |

---

## 3. Environment Comparison

| Feature | Simulation | Production |
|---------|-----------|-----------|
| **Base URL** | `https://apesrv.zatca.gov.sa` | `https://api.zatca.gov.sa` |
| **Purpose** | Testing & Development | Live Invoicing |
| **Data Persistence** | Short-term (Test data) | Permanent (Official Records) |
| **Certificate** | Test Certificate | Production Certificate |
| **Compliance Check** | Simulated Validation | Actual Regulatory Validation |
| **Warnings/Errors** | Test scenarios | Real regulatory issues |

---

## 4. Common Request/Response Patterns

### Authentication
Both environments use **Bearer Token** authentication:
```
Authorization: Bearer {accessToken}
```

The access token is obtained during the CSR approval phase.

---

### Invoice Hash Calculation
Invoice hashes are calculated using **SHA-256** of the canonical XML invoice representation:

```
invoiceHash = Base64(SHA256(canonicalInvoiceXML))
```

---

### Signature Requirements
For clearance submission, requests must include:
```
Digest: SHA-256={base64EncodedHash}
Signature: {base64EncodedSignature}
```

The signature is created using the private key associated with your compliance certificate.

---

### Standard Response Codes

| Status | Code | Meaning |
|--------|------|---------|
| Success | 200 | Request processed successfully |
| Created | 201 | Resource created |
| Bad Request | 400 | Invalid request format/data |
| Unauthorized | 401 | Missing/invalid authentication |
| Forbidden | 403 | Access denied (insufficient permissions) |
| Not Found | 404 | Resource not found |
| Conflict | 409 | Request conflicts with existing resource |
| Server Error | 500 | Internal server error |

---

## 5. Workflow Summary

### Phase 1: Onboarding (Compliance)
1. **Request OTP** → `POST /v1/compliance/otp`
2. **Submit CSR** → `POST /v1/compliance/csrs`
3. **Retrieve Certificate** → `GET /v1/compliance/csrs/{requestId}`
4. **Submit Test Invoices** → `POST /v1/compliance/invoices` (multiple times)
5. **Verify Compliance** → `GET /v1/compliance/invoices/{uuid}`

### Phase 2: Live Invoicing (Clearance)
1. **Submit Invoice** → `POST /v1/invoices/clearance/single`
2. **Check Status** → `GET /v1/invoices/clearance/single/{uuid}`
3. **Download PDF** → `GET /v1/invoices/clearance/single/{uuid}/pdf`
4. **Batch Status** → `POST /v1/invoices/clearance/status`

---

## 6. Important Notes

- **URL Encoding**: All UUIDs and request IDs in paths must be URL-encoded if they contain special characters
- **Rate Limiting**: Be mindful of ZATCA rate limits (typically 100 requests/minute)
- **Certificate Expiry**: Monitor your compliance certificate expiration and plan renewals
- **Invoice Uniqueness**: Each invoice must have a unique UUID per company
- **Signature Validation**: ZATCA validates all signatures cryptographically
- **Error Details**: Response bodies include detailed error messages and warning codes for debugging

---

## 7. Testing Tips for Simulation

- Use test/dummy invoice data with realistic values
- Test edge cases: zero-amount invoices, negative discounts, complex tax scenarios
- Verify invoice hash calculations match ZATCA expectations
- Test signature generation and validation
- Validate response warnings before moving to production

