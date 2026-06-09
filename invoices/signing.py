import base64
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from lxml import etree

from organization.services import decrypt_private_key

DS_NS = 'http://www.w3.org/2000/09/xmldsig#'
XADES_NS = 'http://uri.etsi.org/01903/v1.3.2#'
EXT_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
CBC_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
CAC_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'


def _build_xades_signature(invoice_hash, signature_b64, certificate_b64, public_key_b64, signing_time):
    cert_bytes = base64.b64decode(certificate_b64)
    cert_hash = base64.b64encode(hashlib.sha256(cert_bytes).digest()).decode('ascii')

    sig_ns = {
        'ds': DS_NS,
        'xades': XADES_NS,
    }
    sig = etree.Element(f'{{{DS_NS}}}Signature', nsmap=sig_ns)
    sig.set('Id', 'signature')

    signed_info = etree.SubElement(sig, f'{{{DS_NS}}}SignedInfo')
    c14n_method = etree.SubElement(signed_info, f'{{{DS_NS}}}CanonicalizationMethod')
    c14n_method.set('Algorithm', 'http://www.w3.org/2006/12/xml-c14n11')
    sig_method = etree.SubElement(signed_info, f'{{{DS_NS}}}SignatureMethod')
    sig_method.set('Algorithm', 'http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256')
    ref = etree.SubElement(signed_info, f'{{{DS_NS}}}Reference')
    ref.set('Id', 'invoiceSignedData')
    ref.set('URI', '')
    transforms = etree.SubElement(ref, f'{{{DS_NS}}}Transforms')
    transform = etree.SubElement(transforms, f'{{{DS_NS}}}Transform')
    transform.set('Algorithm', 'http://www.w3.org/TR/1999/REC-xpath-19991116')
    xpath = etree.SubElement(transform, f'{{{DS_NS}}}XPath')
    xpath.text = 'not(//ancestor-or-self::ext:UBLExtensions)'
    transform2 = etree.SubElement(transforms, f'{{{DS_NS}}}Transform')
    transform2.set('Algorithm', 'http://www.w3.org/TR/1999/REC-xpath-19991116')
    xpath2 = etree.SubElement(transform2, f'{{{DS_NS}}}XPath')
    xpath2.text = 'not(//ancestor-or-self::cac:Signature)'
    transform3 = etree.SubElement(transforms, f'{{{DS_NS}}}Transform')
    transform3.set('Algorithm', 'http://www.w3.org/TR/1999/REC-xpath-19991116')
    xpath3 = etree.SubElement(transform3, f'{{{DS_NS}}}XPath')
    xpath3.text = 'not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID=\'QR\'])'
    digest_method = etree.SubElement(ref, f'{{{DS_NS}}}DigestMethod')
    digest_method.set('Algorithm', 'http://www.w3.org/2001/04/xmlenc#sha256')
    digest_value = etree.SubElement(ref, f'{{{DS_NS}}}DigestValue')
    digest_value.text = invoice_hash

    sig_value = etree.SubElement(sig, f'{{{DS_NS}}}SignatureValue')
    sig_value.text = signature_b64

    key_info = etree.SubElement(sig, f'{{{DS_NS}}}KeyInfo')
    x509_data = etree.SubElement(key_info, f'{{{DS_NS}}}X509Data')
    x509_cert = etree.SubElement(x509_data, f'{{{DS_NS}}}X509Certificate')
    x509_cert.text = certificate_b64

    obj = etree.SubElement(sig, f'{{{DS_NS}}}Object')
    qualifying = etree.SubElement(obj, f'{{{XADES_NS}}}QualifyingProperties')
    qualifying.set('Target', 'signature')
    signed_props = etree.SubElement(qualifying, f'{{{XADES_NS}}}SignedProperties')
    signed_props.set('Id', 'xadesSignedProperties')
    signed_sig_props = etree.SubElement(signed_props, f'{{{XADES_NS}}}SignedSignatureProperties')
    signing_time_el = etree.SubElement(signed_sig_props, f'{{{XADES_NS}}}SigningTime')
    signing_time_el.text = signing_time
    signing_cert = etree.SubElement(signed_sig_props, f'{{{XADES_NS}}}SigningCertificate')
    cert_el = etree.SubElement(signing_cert, f'{{{XADES_NS}}}Cert')
    cert_digest = etree.SubElement(cert_el, f'{{{XADES_NS}}}CertDigest')
    digest_method2 = etree.SubElement(cert_digest, f'{{{DS_NS}}}DigestMethod')
    digest_method2.set('Algorithm', 'http://www.w3.org/2001/04/xmlenc#sha256')
    digest_value2 = etree.SubElement(cert_digest, f'{{{DS_NS}}}DigestValue')
    digest_value2.text = cert_hash
    issuer_serial = etree.SubElement(cert_el, f'{{{XADES_NS}}}IssuerSerial')
    issuer_name = etree.SubElement(issuer_serial, f'{{{DS_NS}}}X509IssuerName')
    issuer_name.text = 'CN=ZATCA'
    serial_num = etree.SubElement(issuer_serial, f'{{{DS_NS}}}X509SerialNumber')
    serial_num.text = '1'

    return sig


def sign_invoice_xml(xml_bytes, device, invoice_hash):
    private_key_pem = decrypt_private_key(device.key_material.private_key_pem)
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode('ascii'), password=None
    )

    hash_bytes = base64.b64decode(invoice_hash)
    signature_der = private_key.sign(hash_bytes, ec.ECDSA(hashes.SHA256()))

    signature_b64 = base64.b64encode(signature_der).decode('ascii')

    public_key_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_b64 = base64.b64encode(public_key_der).decode('ascii')

    credential = device.pcsid if (device.pcsid and 'binarySecurityToken' in device.pcsid) else device.csid_response
    certificate_b64 = ''
    if credential and 'binarySecurityToken' in credential:
        certificate_b64 = credential['binarySecurityToken']

    root = etree.fromstring(xml_bytes)
    # Find IssueDate/Time for signing timestamp
    issue_date = root.findtext(f'{{{CBC_NS}}}IssueDate') or '2024-01-01'
    issue_time = root.findtext(f'{{{CBC_NS}}}IssueTime') or '00:00:00'
    signing_time = f"{issue_date}T{issue_time}Z"

    xades_sig = _build_xades_signature(
        invoice_hash, signature_b64, certificate_b64, public_key_b64, signing_time
    )

    # Embed into ExtensionContent
    ext_content = root.find(
        f'.//{{{EXT_NS}}}ExtensionContent'
    )
    if ext_content is not None:
        ext_content.append(xades_sig)

    signed_xml_bytes = etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=False)
    return signed_xml_bytes, signature_b64, public_key_b64
