# Project Plan

## Overview

This document is the primary reference for what the application does, the main workflows it must support, and how implementation should be organized.

Codex should treat this file as the main source of product and architecture context when making changes in this repository.

The detailed ZATCA terminology and XML/security implementation rules currently available in this repository are stored under `docs/guidelines-from-zatca`. This plan should stay aligned with those files.

## Product Summary

Project name: Zatca E-Invoice Connector

Application type:
Python Django application

Primary purpose:
Provide an API-driven integration platform that receives invoice-related documents in JSON format from external systems, transforms them into ZATCA-compliant UBL 2.1 XML, submits them to ZATCA for Phase 2 integration, and returns the QR code in the same API call.

Primary users:

- organizations using the platform for ZATCA integration
- external software systems that send invoice payloads to the platform
- software owner or administrator responsible for activating organizations

## Core Business Scope

The application must support:

- organization registration with organization details
- activation of registered organizations by the software owner or system administrator
- device registration for activated organizations
- submission of invoice documents using an API
- support for invoice, credit note, and debit note documents
- conversion of incoming JSON documents into ZATCA-compliant UBL XML
- internal handling of keys, CSR generation, certificates, previous invoice hash, invoice counter value, QR payload, and related technical onboarding steps
- online submission of documents to ZATCA
- returning QR code data in the same API response

## Main Workflow

### Organization Onboarding

1. An organization registers its details in the system.
2. The organization record is created in an inactive state.
3. The software owner or system administrator reviews and activates the organization.
4. After activation, the organization can register one or more devices.

### Device Registration

Each activated organization can maintain one or more devices used for invoice generation or submission.

Each device should be associated with:

- the owning organization
- an internal device identifier
- activation or status information
- technical onboarding material where applicable

### Invoice Submission

1. An external system sends a JSON payload to the application API.
2. The payload may include the device identifier used for the invoice.
3. The system validates the request and document type.
4. The JSON payload is transformed into UBL XML according to ZATCA requirements.
5. The system populates mandatory invoice metadata such as invoice number, `UUID`, issue date, issue time, invoice type code, and subtype indicators.
6. The application performs or uses the required key generation, CSR handling, previous invoice hash, invoice counter value, QR handling, and cryptographic stamp workflows.
7. The document is submitted online to ZATCA.
8. The API returns the response, including QR code data, to the calling system.

## Supported Document Types

The system must support:

- invoice
- credit note
- debit note

The domain model and submission logic should be designed so that document-type-specific rules can be applied without duplicating the entire workflow.

Specific guideline implications from the ZATCA data dictionary:

- all supported document types require a `cbc:UUID`
- credit notes and debit notes must carry a billing reference to the original invoice
- credit notes and debit notes may require a reason for issuance through payment instruction fields
- the invoice type code and subtype flags must be modeled explicitly rather than treated as free text

## ZATCA Guideline Alignment

The local ZATCA guideline files indicate that the implementation should account for the following concepts:

- XML structure based on UBL invoice documents
- business process type through `cbc:ProfileID`
- invoice identifier through `cbc:ID`
- unique invoice identifier through `cbc:UUID`
- invoice type code through `cbc:InvoiceTypeCode`
- subtype and transaction flags through the `InvoiceTypeCode` `name` attribute
- additional document references for:
  `PIH` as previous invoice hash
  `ICV` as invoice counter value
  `QR` as QR code payload
- cryptographic stamp embedded through UBL extensions and signature nodes
- seller identification through supplier party nodes and VAT registration fields
- buyer identification through customer party nodes when applicable

The data dictionary also indicates distinctions between tax invoices and simplified tax invoices, including differences in how seller and buyer data is required on human-readable forms. The system should preserve enough source data to generate compliant XML for either case.

## Functional Requirements

### Organization Management

- register organization details
- keep newly registered organizations inactive by default
- allow only the software owner or administrator to activate an organization
- prevent operational use before activation

### Device Management

- allow device registration only for activated organizations
- associate devices with a specific organization
- allow invoice submission with a device identifier
- keep device records auditable and status-aware

### Document Intake

- accept invoice-related payloads in JSON format
- identify the submitted document type
- validate required fields before transformation
- keep the API contract stable for external clients
- require enough structured data to build the ZATCA UBL nodes correctly

### Transformation and Submission

- convert JSON payloads to UBL XML as required by ZATCA
- prepare documents for ZATCA submission
- handle technical artifacts such as keys, CSR documents, previous invoice hashes, invoice counters, signatures, and QR data inside the platform
- submit documents online to ZATCA
- capture submission results and errors

### Response Handling

- return QR code data in the same API call when submission succeeds
- return clear structured errors when validation or submission fails
- preserve traceability between request, transformed document, and ZATCA response

## Suggested Django Structure

Suggested apps:

- `core`
  Shared utilities, base models, constants, common helpers, configuration helpers

- `organizations`
  Organization registration, organization profile, organization activation state, device registration, device ownership, and device lifecycle management

- `transformations`
  JSON-to-XML transformation logic, UBL builders, and field mapping from API payloads to ZATCA XML structures

- `integrations`
  ZATCA API communication, request/response orchestration, submission services

- `crypto`
  Key creation, CSR generation, certificate-related workflows, invoice hashing, signature generation, and signing support

- `audit`
  Audit events, request logs, submission tracking, operational traceability

- `accounts`
  Admin or owner access control if a dedicated authentication layer is needed

## Architecture Direction

Implementation should follow these principles:

- keep API layer, domain logic, transformation logic, and ZATCA integration logic separated
- keep models focused on persisted state and invariants
- use service modules for orchestration and external calls
- isolate cryptographic and onboarding operations into dedicated modules
- make document transformation extensible for invoice, credit note, and debit note variants
- ensure every submission can be traced by organization, device, request payload, XML output, and ZATCA response
- model ZATCA-specific values such as `UUID`, `ICV`, `PIH`, QR payload, and billing references explicitly
- structure XML generation around UBL nodes instead of ad hoc string templates
- avoid hardcoding secrets or certificates in source code

## Data Model Direction

Key entities likely required:

- Organization
- OrganizationActivation
- Device
- DocumentSubmission
- DocumentType
- InvoiceDocument
- CreditNoteDocument
- DebitNoteDocument
- XmlArtifact
- KeyMaterial
- CSRRequest
- PreviousInvoiceHash
- InvoiceCounter
- QRArtifact
- BillingReference
- SubmissionResult
- AuditEvent

The exact shape can be refined during implementation, but the model must support traceability and operational audit.

## API Direction

Expected API responsibilities:

- register organization details
- activate an organization through privileged admin actions
- register devices for an activated organization
- receive JSON invoice payloads
- submit invoice-related documents to ZATCA
- return QR code and submission status in the response

API design notes:

- external clients are other apps or organizations, so the API should be stable and clearly documented
- request and response formats should be explicit and versionable
- validation errors should be predictable and structured
- request schemas should collect enough structured seller, buyer, invoice, tax, and reference data to produce valid UBL XML

## Security and Access Notes

- only the software owner or authorized administrator can activate organizations
- organization and device operations should be permission-aware
- cryptographic materials must be stored and handled securely
- onboarding and submission events should be auditable
- invoice hashes, certificates, and signature material require careful storage and lifecycle handling

## Development Plan

### Phase 1: Foundation

- set up project configuration and dependency management
- create core Django apps aligned with the domain
- establish environment-based settings
- add baseline models for organization and device management in the same app
- define API conventions and error response format

### Phase 2: Onboarding And Registration

- implement organization registration flow
- implement admin activation flow
- implement device registration flow
- add admin interfaces or internal management endpoints
- store onboarding and status data

### Phase 3: Document Intake And Transformation

- implement document intake API
- support invoice, credit note, and debit note payloads
- add request validation
- implement JSON-to-UBL-XML transformation layer
- map incoming fields to ZATCA data dictionary terms
- implement billing reference and note-reason handling for credit and debit notes
- persist submission requests and generated XML artifacts

### Phase 4: ZATCA Integration

- implement key generation and CSR workflows
- implement previous invoice hash and invoice counter workflows
- implement QR payload generation and persistence
- implement cryptographic stamp and signature workflows
- integrate with ZATCA endpoints
- submit transformed XML documents
- capture response data including QR code details
- add robust error handling and logging

### Phase 5: Hardening

- improve automated test coverage
- add audit and operational reporting
- review security and secret handling
- prepare deployment configuration
- optimize reliability and observability

## Environment and Configuration Notes

Current state:

- Django default project scaffold
- SQLite configured for local development
- generated settings still need production-oriented review

Planned improvements:

- move secrets to environment variables
- review timezone and localization settings
- split settings by environment if needed
- add production-ready database and deployment configuration
- add secure storage approach for keys and certificate-related data
- add configuration for XML schemas, certificates, and environment-specific ZATCA endpoints

## Open Questions

- what exact ZATCA endpoints and onboarding sequence will be used first?
- should invoice submission be fully synchronous in all cases, or should some operations become asynchronous later?
- what organization fields are mandatory for registration?
- what device metadata is required for successful submission?
- what QR code format should the API return?
- what authentication mechanism will external client systems use?
- will the API accept a normalized internal JSON schema or a schema that mirrors ZATCA data dictionary terms directly?
- how will standard tax invoices versus simplified tax invoices be selected in the API contract?

## Implementation Notes For Codex

When making changes in this repository:

- treat this file as the authoritative project reference
- align code changes to the organization activation, device registration, and invoice submission workflow
- assume the system is API-first
- preserve support for invoice, credit note, and debit note flows
- keep transformation, integration, and cryptographic concerns separated
- consult `docs/guidelines-from-zatca` when implementing XML field mappings, signatures, hashes, QR payloads, or note-specific rules
- update this file when product scope or workflow changes
- Also consult https://zatca1.discourse.group/docs 

## Change Log

- 2026-04-15: Initial project plan created
- 2026-04-15: Updated with actual product scope for ZATCA Phase 2 integration workflow
- 2026-04-15: Updated with terminology and requirements derived from the local ZATCA guideline files
