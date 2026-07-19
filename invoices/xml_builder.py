import uuid
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree

from invoices.hashing import INITIAL_PIH

NSMAP = {
    None: 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2',
}

CAC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
CBC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
EXT = 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'

VAT_CATEGORY_SCHEME = 'UN/ECE 5305'
VAT_SCHEME = 'VAT'

VAT_RATE = Decimal('0.15')

_VAT_CATEGORY_ID = {
    'S': 'S',
    'Z': 'Z',
    'E': 'E',
    'O': 'O',
}

_VAT_EXEMPTION_REASON = {
    'Z': 'Zero rated goods',
    'E': 'Exempt from Tax',
    'O': 'Services outside scope of tax',
}


def _sub(parent, ns, tag, text=None, **attrib):
    el = etree.SubElement(parent, f'{{{ns}}}{tag}', **attrib)
    if text is not None:
        el.text = str(text)
    return el


def _compute_totals(items, doc_level_discount_vat=0, doc_level_discount_novat=0, advance_paid=0):
    def q(value):
        return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    line_extension_amount = Decimal('0')
    standard_taxable = Decimal('0')
    discount_vat = Decimal(str(doc_level_discount_vat))
    discount_novat = Decimal(str(doc_level_discount_novat))
    discount_total = discount_vat + discount_novat
    advance = q(Decimal(str(advance_paid)))

    for item in items:
        qty = Decimal(str(item['qty']))
        price = Decimal(str(item['price']))
        line_amount = qty * price
        line_extension_amount += line_amount
        if item['vat_type'] == 'S':
            standard_taxable += line_amount

    # BR-S-08: the standard-rated VAT category's taxable amount must equal
    # line net amounts minus document-level allowances (the doc-level VAT
    # discount is modeled as an allowance against the 'S' category), so the
    # VAT amount itself must be computed on that discounted base.
    tax_exclusive = q(line_extension_amount - discount_total)
    vat_total = q((standard_taxable - discount_vat) * VAT_RATE)
    # BR-CO-15: BT-112 (TaxInclusiveAmount) must equal the *already-rounded*
    # BT-109 (TaxExclusiveAmount) + BT-110 (TaxAmount) exactly — summing the
    # unrounded components and rounding that sum independently can drift by a
    # cent when the two component roundings land on opposite sides of their
    # own boundary. Deriving tax_inclusive/payable from the rounded parts
    # instead guarantees the identity ZATCA checks.
    tax_inclusive = tax_exclusive + vat_total
    payable = tax_inclusive - advance

    return {
        'line_extension': q(line_extension_amount),
        'discount_total': q(discount_total),
        'tax_exclusive': tax_exclusive,
        'vat_total': vat_total,
        'tax_inclusive': tax_inclusive,
        'advance': advance,
        'payable': payable,
    }


def build_invoice_xml(validated_data, organization, device, icv, pih):
    invoice_uuid = uuid.uuid4()
    items = validated_data['items']
    totals = _compute_totals(
        items,
        validated_data.get('doc_level_discount_vat', 0),
        validated_data.get('doc_level_discount_novat', 0),
        validated_data.get('advance_paid', 0),
    )

    root = etree.Element(
        f'{{{list(NSMAP.values())[0]}}}Invoice',
        nsmap=NSMAP,
    )

    # UBL Extensions (signature placeholder)
    ubl_exts = _sub(root, EXT, 'UBLExtensions')
    ubl_ext = _sub(ubl_exts, EXT, 'UBLExtension')
    _sub(ubl_ext, EXT, 'ExtensionContent')

    _sub(root, CBC, 'UBLVersionID', '2.1')
    _sub(root, CBC, 'ProfileID', 'reporting:1.0')
    _sub(root, CBC, 'ID', validated_data['invoice_number'])
    _sub(root, CBC, 'UUID', str(invoice_uuid))
    _sub(root, CBC, 'IssueDate', str(validated_data['issue_date']))
    _sub(root, CBC, 'IssueTime', str(validated_data['issue_time'])[:8])

    type_code_el = _sub(root, CBC, 'InvoiceTypeCode', validated_data['invoice_type_code'])
    type_code_el.set('name', validated_data['invoice_type_code_name_attribute'])

    if validated_data.get('notes'):
        _sub(root, CBC, 'Note', validated_data['notes'])

    _sub(root, CBC, 'DocumentCurrencyCode', 'SAR')
    _sub(root, CBC, 'TaxCurrencyCode', 'SAR')

    # Billing reference for credit/debit notes
    if validated_data.get('billing_reference'):
        billing_ref = _sub(root, CAC, 'BillingReference')
        inv_doc_ref = _sub(billing_ref, CAC, 'InvoiceDocumentReference')
        _sub(inv_doc_ref, CBC, 'ID', validated_data['billing_reference'])

    # AdditionalDocumentReference: ICV
    icv_ref = _sub(root, CAC, 'AdditionalDocumentReference')
    _sub(icv_ref, CBC, 'ID', 'ICV')
    _sub(icv_ref, CBC, 'UUID', str(icv))

    # AdditionalDocumentReference: PIH
    pih_ref = _sub(root, CAC, 'AdditionalDocumentReference')
    _sub(pih_ref, CBC, 'ID', 'PIH')
    pih_att = _sub(pih_ref, CAC, 'Attachment')
    pih_doc = _sub(pih_att, CBC, 'EmbeddedDocumentBinaryObject', pih)
    pih_doc.set('mimeCode', 'text/plain')

    # AdditionalDocumentReference: QR (empty placeholder)
    qr_ref = _sub(root, CAC, 'AdditionalDocumentReference')
    _sub(qr_ref, CBC, 'ID', 'QR')
    qr_att = _sub(qr_ref, CAC, 'Attachment')
    qr_doc = _sub(qr_att, CBC, 'EmbeddedDocumentBinaryObject', '')
    qr_doc.set('mimeCode', 'text/plain')

    # Signature (placeholder referenced by the XAdES signature embedded later)
    signature = _sub(root, CAC, 'Signature')
    _sub(signature, CBC, 'ID', 'urn:oasis:names:specification:ubl:signature:Invoice')
    _sub(signature, CBC, 'SignatureMethod', 'urn:oasis:names:specification:ubl:dsig:enveloped:xades')

    # Seller party
    supplier_party = _sub(root, CAC, 'AccountingSupplierParty')
    supplier = _sub(supplier_party, CAC, 'Party')
    seller_id = _sub(supplier, CAC, 'PartyIdentification')
    seller_id_val = _sub(seller_id, CBC, 'ID', organization.cr_number)
    seller_id_val.set('schemeID', 'CRN')
    seller_addr = _sub(supplier, CAC, 'PostalAddress')
    _sub(seller_addr, CBC, 'StreetName', organization.street_name)
    _sub(seller_addr, CBC, 'BuildingNumber', organization.building_number)
    _sub(seller_addr, CBC, 'CitySubdivisionName', organization.city_sub_division)
    _sub(seller_addr, CBC, 'CityName', organization.city_name)
    _sub(seller_addr, CBC, 'PostalZone', organization.postal_zone)
    seller_country = _sub(seller_addr, CAC, 'Country')
    _sub(seller_country, CBC, 'IdentificationCode', organization.country_code)
    seller_tax_scheme = _sub(supplier, CAC, 'PartyTaxScheme')
    _sub(seller_tax_scheme, CBC, 'CompanyID', organization.vat_number)
    tax_scheme = _sub(seller_tax_scheme, CAC, 'TaxScheme')
    _sub(tax_scheme, CBC, 'ID', VAT_SCHEME)
    seller_legal = _sub(supplier, CAC, 'PartyLegalEntity')
    _sub(seller_legal, CBC, 'RegistrationName', organization.name)

    # Customer party
    customer_party = _sub(root, CAC, 'AccountingCustomerParty')
    customer = _sub(customer_party, CAC, 'Party')
    if validated_data.get('customer_id_number'):
        cust_id = _sub(customer, CAC, 'PartyIdentification')
        cust_id_val = _sub(cust_id, CBC, 'ID', validated_data['customer_id_number'])
        cust_id_val.set('schemeID', validated_data.get('customer_id_type') or 'NAT')
    cust_addr = _sub(customer, CAC, 'PostalAddress')
    if validated_data.get('customer_street'):
        _sub(cust_addr, CBC, 'StreetName', validated_data['customer_street'])
    if validated_data.get('customer_building_number'):
        _sub(cust_addr, CBC, 'BuildingNumber', validated_data['customer_building_number'])
    if validated_data.get('customer_district'):
        _sub(cust_addr, CBC, 'CitySubdivisionName', validated_data['customer_district'])
    if validated_data.get('customer_city'):
        _sub(cust_addr, CBC, 'CityName', validated_data['customer_city'])
    if validated_data.get('customer_postal_zone'):
        _sub(cust_addr, CBC, 'PostalZone', validated_data['customer_postal_zone'])
    cust_country = _sub(cust_addr, CAC, 'Country')
    _sub(cust_country, CBC, 'IdentificationCode', validated_data.get('customer_country_code') or 'SA')
    if validated_data.get('customer_vat'):
        cust_tax = _sub(customer, CAC, 'PartyTaxScheme')
        _sub(cust_tax, CBC, 'CompanyID', validated_data['customer_vat'])
        cust_tax_scheme = _sub(cust_tax, CAC, 'TaxScheme')
        _sub(cust_tax_scheme, CBC, 'ID', VAT_SCHEME)
    cust_legal = _sub(customer, CAC, 'PartyLegalEntity')
    _sub(cust_legal, CBC, 'RegistrationName', validated_data['customer_name'])

    # PaymentMeans. Also carries the KSA-10 "reason for issuance" (BR-KSA-17),
    # required for credit/debit notes — ZATCA repurposes the standard UBL
    # PaymentMeans/InstructionNote field for this rather than a KSA extension.
    # PaymentMeansCode is mandatory if PaymentMeans is present at all, so a
    # neutral UNTDID 4461 default ("1" = instrument not defined) is used when
    # no real payment_mode was supplied.
    payment_mode = validated_data.get('payment_mode')
    reason = validated_data.get('reason')
    if payment_mode or reason:
        pm = _sub(root, CAC, 'PaymentMeans')
        _sub(pm, CBC, 'PaymentMeansCode', payment_mode or '1')
        if reason:
            _sub(pm, CBC, 'InstructionNote', reason)

    # AllowanceCharge for doc-level discounts
    disc_vat = Decimal(str(validated_data.get('doc_level_discount_vat', 0)))
    disc_novat = Decimal(str(validated_data.get('doc_level_discount_novat', 0)))
    base_amount = totals['line_extension']
    if disc_vat > 0:
        ac = _sub(root, CAC, 'AllowanceCharge')
        _sub(ac, CBC, 'ChargeIndicator', 'false')
        _sub(ac, CBC, 'AllowanceChargeReason', 'Discount')
        if base_amount > 0:
            _sub(ac, CBC, 'MultiplierFactorNumeric', str((disc_vat / base_amount * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
        _sub(ac, CBC, 'Amount', str(disc_vat.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)), currencyID='SAR')
        _sub(ac, CBC, 'BaseAmount', str(base_amount), currencyID='SAR')
        ac_tax = _sub(ac, CAC, 'TaxCategory')
        _sub(ac_tax, CBC, 'ID', 'S')
        _sub(ac_tax, CBC, 'Percent', '15.00')
        ac_tax_scheme = _sub(ac_tax, CAC, 'TaxScheme')
        _sub(ac_tax_scheme, CBC, 'ID', VAT_SCHEME)
    # BR-O-01 etc.: the discount's category must be one that actually has a
    # matching VAT breakdown group on this invoice — use whichever non-'S'
    # category the line items use, rather than assuming 'O'.
    novat_category = next((i['vat_type'] for i in items if i['vat_type'] != 'S'), 'O')
    if disc_novat > 0:
        ac = _sub(root, CAC, 'AllowanceCharge')
        _sub(ac, CBC, 'ChargeIndicator', 'false')
        _sub(ac, CBC, 'AllowanceChargeReason', 'Discount')
        if base_amount > 0:
            _sub(ac, CBC, 'MultiplierFactorNumeric', str((disc_novat / base_amount * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
        _sub(ac, CBC, 'Amount', str(disc_novat.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)), currencyID='SAR')
        _sub(ac, CBC, 'BaseAmount', str(base_amount), currencyID='SAR')
        ac_tax = _sub(ac, CAC, 'TaxCategory')
        _sub(ac_tax, CBC, 'ID', novat_category)
        _sub(ac_tax, CBC, 'Percent', '0.00')
        ac_tax_scheme = _sub(ac_tax, CAC, 'TaxScheme')
        _sub(ac_tax_scheme, CBC, 'ID', VAT_SCHEME)

    # TaxTotal: ZATCA requires a tax-currency total without subtotals (since
    # TaxCurrencyCode is declared) ahead of the document-currency total with
    # the per-category subtotal breakdown — confirmed against the official
    # sample invoice's structure.
    tax_total_no_subtotal = _sub(root, CAC, 'TaxTotal')
    _sub(tax_total_no_subtotal, CBC, 'TaxAmount', str(totals['vat_total']), currencyID='SAR')

    tax_total = _sub(root, CAC, 'TaxTotal')
    _sub(tax_total, CBC, 'TaxAmount', str(totals['vat_total']), currencyID='SAR')

    # Group by vat_type for TaxSubtotal
    vat_groups = {}
    for item in items:
        vt = item['vat_type']
        amt = Decimal(str(item['qty'])) * Decimal(str(item['price']))
        group = vat_groups.setdefault(vt, {'amount': Decimal('0'), 'reason_code': ''})
        group['amount'] += amt
        if not group['reason_code'] and item.get('VatExceptionReason'):
            group['reason_code'] = item['VatExceptionReason']

    for vt, group in vat_groups.items():
        taxable_amount = group['amount']
        # BR-S-08 / equivalent per-category rules: the category's taxable
        # amount excludes the doc-level allowance modeled against it above.
        if vt == 'S':
            taxable_amount -= disc_vat
        elif vt == novat_category:
            taxable_amount -= disc_novat
        subtotal = _sub(tax_total, CAC, 'TaxSubtotal')
        _sub(subtotal, CBC, 'TaxableAmount', str(taxable_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)), currencyID='SAR')
        vat_amount = (taxable_amount * VAT_RATE if vt == 'S' else Decimal('0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        _sub(subtotal, CBC, 'TaxAmount', str(vat_amount), currencyID='SAR')
        cat = _sub(subtotal, CAC, 'TaxCategory')
        _sub(cat, CBC, 'ID', _VAT_CATEGORY_ID[vt])
        _sub(cat, CBC, 'Percent', '15.00' if vt == 'S' else '0.00')
        # BR-KSA-69: only emit the coded exemption reason (BT-121) when the
        # caller supplied one on a line — no default guess.
        if group['reason_code']:
            _sub(cat, CBC, 'TaxExemptionReasonCode', group['reason_code'])
        if vt in _VAT_EXEMPTION_REASON:
            _sub(cat, CBC, 'TaxExemptionReason', _VAT_EXEMPTION_REASON[vt])
        cat_scheme = _sub(cat, CAC, 'TaxScheme')
        _sub(cat_scheme, CBC, 'ID', VAT_SCHEME)

    # LegalMonetaryTotal
    lmt = _sub(root, CAC, 'LegalMonetaryTotal')
    _sub(lmt, CBC, 'LineExtensionAmount', str(totals['line_extension']), currencyID='SAR')
    _sub(lmt, CBC, 'TaxExclusiveAmount', str(totals['tax_exclusive']), currencyID='SAR')
    _sub(lmt, CBC, 'TaxInclusiveAmount', str(totals['tax_inclusive']), currencyID='SAR')
    if totals['discount_total'] > 0:
        _sub(lmt, CBC, 'AllowanceTotalAmount', str(totals['discount_total']), currencyID='SAR')
    if totals['advance'] > 0:
        _sub(lmt, CBC, 'PrepaidAmount', str(totals['advance']), currencyID='SAR')
    _sub(lmt, CBC, 'PayableAmount', str(totals['payable']), currencyID='SAR')

    # Invoice Lines
    for idx, item in enumerate(items, start=1):
        qty = Decimal(str(item['qty']))
        price = Decimal(str(item['price']))
        line_amount = (qty * price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        vt = item['vat_type']
        line_vat = (line_amount * VAT_RATE if vt == 'S' else Decimal('0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        il = _sub(root, CAC, 'InvoiceLine')
        _sub(il, CBC, 'ID', str(item['slno']))
        qty_el = _sub(il, CBC, 'InvoicedQuantity', str(qty.normalize()))
        qty_el.set('unitCode', 'PCE')
        _sub(il, CBC, 'LineExtensionAmount', str(line_amount), currencyID='SAR')
        il_tax = _sub(il, CAC, 'TaxTotal')
        _sub(il_tax, CBC, 'TaxAmount', str(line_vat), currencyID='SAR')
        _sub(il_tax, CBC, 'RoundingAmount', str(line_amount + line_vat), currencyID='SAR')
        il_item = _sub(il, CAC, 'Item')
        _sub(il_item, CBC, 'Name', item['name'])
        seller_item_id = _sub(il_item, CAC, 'SellersItemIdentification')
        _sub(seller_item_id, CBC, 'ID', item['code'])
        classified_tax = _sub(il_item, CAC, 'ClassifiedTaxCategory')
        _sub(classified_tax, CBC, 'ID', _VAT_CATEGORY_ID[vt])
        _sub(classified_tax, CBC, 'Percent', '15.00' if vt == 'S' else '0.00')
        if item.get('VatExceptionReason'):
            _sub(classified_tax, CBC, 'TaxExemptionReasonCode', item['VatExceptionReason'])
        line_tax_scheme = _sub(classified_tax, CAC, 'TaxScheme')
        _sub(line_tax_scheme, CBC, 'ID', VAT_SCHEME)
        il_price = _sub(il, CAC, 'Price')
        _sub(il_price, CBC, 'PriceAmount', str(price), currencyID='SAR')

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=False)
    return xml_bytes, invoice_uuid


def build_compliance_sample_invoice(device, invoice_type_code='388', name_attribute='020000000',
                                     billing_reference='', reason=''):
    from invoices.hashing import hash_invoice_xml

    organization = device.organization
    fake_data = {
        'invoice_number': 'COMP-SAMPLE-001',
        'issue_date': '2024-01-01',
        'issue_time': '00:00:00',
        'invoice_type_code': invoice_type_code,
        'invoice_type_code_name_attribute': name_attribute,
        'notes': '',
        'customer_name': 'Compliance Test Customer',
        'customer_vat': '',
        'customer_building_number': '',
        'customer_street': '',
        'customer_district': '',
        'customer_city': '',
        'customer_postal_zone': '',
        'customer_country_code': 'SA',
        'customer_id_number': '',
        'payment_mode': '',
        'doc_level_discount_vat': 0,
        'doc_level_discount_novat': 0,
        'advance_paid': 0,
        'billing_reference': billing_reference,
        'reason': reason,
        'items': [
            {
                'slno': 1,
                'code': 'ITEM-001',
                'name': 'Compliance Test Item',
                'qty': '1.0000',
                'price': '1.0000',
                'vat_type': 'S',
            }
        ],
    }
    xml_bytes, invoice_uuid = build_invoice_xml(fake_data, organization, device, 0, INITIAL_PIH)
    invoice_hash = hash_invoice_xml(xml_bytes)
    return xml_bytes, invoice_uuid, invoice_hash, fake_data


def embed_qr_in_xml(xml_bytes, qr_b64):
    root = etree.fromstring(xml_bytes)
    # Find QR AdditionalDocumentReference
    ns = {'cac': CAC, 'cbc': CBC}
    for adr in root.findall(f'{{{CAC}}}AdditionalDocumentReference'):
        id_el = adr.find(f'{{{CBC}}}ID')
        if id_el is not None and id_el.text == 'QR':
            emb = adr.find(f'.//{{{CBC}}}EmbeddedDocumentBinaryObject')
            if emb is not None:
                emb.text = qr_b64
            break
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=False)
