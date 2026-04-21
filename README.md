# Zatca E-Invoice Connector

This repository contains a Python Django application that acts as a connector between external business systems and ZATCA Phase 2 e-invoicing services.

Other applications or organizations send invoice data to this system in JSON format. The application converts that JSON payload into a ZATCA-compliant XML invoice, submits it online to ZATCA, and returns the QR code in the same API response.

The implementation in this repository should follow the ZATCA reference material stored in [docs/guidelines-from-zatca](docs/guidelines-from-zatca), especially:

- `20220624_ZATCA_Electronic_Invoice_XML_Implementation_Standard_vF.pdf`
- `20220624_ZATCA_Electronic_Invoice_Security_Features_Implementation_Standards.pdf`
- `EInvoice_Data_Dictionary.xlsx`

## What The Application Does

The application is designed to:

- accept invoice data from external systems through an API
- support invoice, credit note, and debit note documents
- convert incoming JSON documents into ZATCA-compliant UBL 2.1 XML
- handle key generation, CSR creation, certificates, hashes, and related onboarding artifacts
- submit documents to ZATCA services
- return the generated QR code back through the API response
- manage organization registration, activation, and device registration

## Business Flow

The intended flow is:

1. An organization registers its details in the platform.
2. The organization remains inactive until approved by the software owner or system administrator.
3. Once activated, the organization can register one or more devices that are used to issue invoices.
4. An external system submits an invoice payload in JSON format and may include the device identifier.
5. The application validates the request, transforms it into ZATCA-compliant UBL XML, and builds the required fields such as `UUID`, invoice type code, and other mandatory business terms.
6. The application handles the cryptographic and onboarding steps required by ZATCA, including key material, CSR-related workflows, previous invoice hash, invoice counter value, QR data, and cryptographic stamp handling.
7. The document is submitted to ZATCA.
8. The application returns the QR code and submission result through the same API call.

## Main Capabilities

- organization registration and activation workflow
- device registration per activated organization
- support for multiple fiscal document types
- JSON-to-UBL-XML transformation for ZATCA submission
- internal handling of keys, CSR generation, certificates, hashes, and related technical setup
- online submission to ZATCA
- synchronous API response containing QR code data

## ZATCA-Aligned Document Rules

Based on the ZATCA guideline files currently stored in the repository, the implementation should account for at least the following:

- XML output should follow UBL invoice structure and ZATCA-specific business rules
- every document requires a unique invoice identifier using `cbc:UUID`
- invoice, debit note, and credit note flows must preserve document-type-specific rules
- credit note and debit note submissions must reference the original invoice through billing reference fields
- the XML payload needs ZATCA-specific additional document references such as `ICV`, `PIH`, and `QR`
- QR content is part of the compliant payload and depends on the XML invoice hash and issue details
- cryptographic stamp handling must align with the ZATCA security standard and UBL signature extensions
- seller and buyer identification and address fields must be captured with enough structure to populate the required XML nodes

## Data Points That Matter Early

From the ZATCA data dictionary, the application will need to model and transform fields such as:

- invoice number
- invoice UUID
- issue date and time
- invoice type code and subtype flags
- seller VAT number, registration name, and address
- buyer identification and address details where applicable
- invoice counter value (`ICV`)
- previous invoice hash (`PIH`)
- QR code payload
- cryptographic stamp and signature data
- billing reference for credit and debit notes
- reason for issuing a credit note or debit note

## Tech Stack

- Python
- Django
- SQLite for initial local development

## Local Development

1. Create and activate a virtual environment
2. Install project dependencies
3. Run migrations
4. Start the development server

Example commands:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install django
python manage.py migrate
python manage.py runserver
```

## Project Documentation

The main planning and reference document for this project is:

- [docs/project-plan.md](docs/project-plan.md)

Use that file for:

- functional scope
- domain entities
- architecture direction
- workflow details
- phased implementation planning
- ZATCA guideline alignment notes

## Current Status

- Django project scaffold created
- baseline project documentation added
- domain implementation still to be built

## Notes For Development

- external clients will integrate with this system through API calls
- the platform must separate organization activation from organization registration
- device-level context is part of invoice submission
- ZATCA technical onboarding artifacts are generated and managed by this application
- the `docs/guidelines-from-zatca` folder is the local source of truth for XML and security terminology used in implementation

-Add environment variable DEVICE_KEY_ENCRYPTION_KEY
-Add environment variable openssl