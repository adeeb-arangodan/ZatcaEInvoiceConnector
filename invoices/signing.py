import base64
import hashlib
from xml.sax.saxutils import escape

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from lxml import etree

from organization.services import decrypt_private_key

DS_NS = 'http://www.w3.org/2000/09/xmldsig#'
XADES_NS = 'http://uri.etsi.org/01903/v1.3.2#'
EXT_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
CBC_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
CAC_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
SIG_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2'
SAC_NS = 'urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2'
SBC_NS = 'urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2'

SIGNATURE_INFORMATION_ID = 'urn:oasis:names:specification:ubl:signature:1'
REFERENCED_SIGNATURE_ID = 'urn:oasis:names:specification:ubl:signature:Invoice'


def _hex_then_b64(data_bytes):
    return base64.b64encode(hashlib.sha256(data_bytes).hexdigest().encode('ascii')).decode('ascii')


def _signed_properties_xml(signing_time, cert_hash, issuer_name, serial_number):
    # ZATCA's backend computes this digest using dom4j's Node.asXML() on the
    # SignedProperties subtree, not real XML C14N: empty elements self-close,
    # and xmlns:ds is redeclared on every ds:-prefixed element (since none of
    # their xades:-prefixed parents declare it), regardless of sibling/ancestor
    # history. Confirmed by decompiling and running the official ZATCA SDK's
    # own signing class against its own freshly-generated sample.
    return (
        '<xades:SignedProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" Id="xadesSignedProperties">'
        '<xades:SignedSignatureProperties>'
        f'<xades:SigningTime>{escape(signing_time)}</xades:SigningTime>'
        '<xades:SigningCertificate>'
        '<xades:Cert>'
        '<xades:CertDigest>'
        '<ds:DigestMethod xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
        f'<ds:DigestValue xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{escape(cert_hash)}</ds:DigestValue>'
        '</xades:CertDigest>'
        '<xades:IssuerSerial>'
        f'<ds:X509IssuerName xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{escape(issuer_name)}</ds:X509IssuerName>'
        f'<ds:X509SerialNumber xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{escape(serial_number)}</ds:X509SerialNumber>'
        '</xades:IssuerSerial>'
        '</xades:Cert>'
        '</xades:SigningCertificate>'
        '</xades:SignedSignatureProperties>'
        '</xades:SignedProperties>'
    )


def _build_xades_signature(
    invoice_hash, signature_b64, certificate_b64, public_key_b64, signing_time,
    issuer_name, serial_number,
):
    # ZATCA hashes the base64 *text* of the certificate (the same text that
    # appears in ds:X509Certificate), not the decoded DER bytes — confirmed
    # against a freshly self-signed sample from ZATCA's own SDK.
    cert_hash = _hex_then_b64(certificate_b64.encode('ascii'))

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
    transform4 = etree.SubElement(transforms, f'{{{DS_NS}}}Transform')
    transform4.set('Algorithm', 'http://www.w3.org/2006/12/xml-c14n11')
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

    signed_props_xml = _signed_properties_xml(signing_time, cert_hash, issuer_name, serial_number)
    signed_props_digest = _hex_then_b64(signed_props_xml.encode('utf-8'))
    signed_props = etree.fromstring(signed_props_xml)
    qualifying.append(signed_props)

    props_ref = etree.SubElement(signed_info, f'{{{DS_NS}}}Reference')
    props_ref.set('Type', 'http://www.w3.org/2000/09/xmldsig#SignatureProperties')
    props_ref.set('URI', '#xadesSignedProperties')
    props_digest_method = etree.SubElement(props_ref, f'{{{DS_NS}}}DigestMethod')
    props_digest_method.set('Algorithm', 'http://www.w3.org/2001/04/xmlenc#sha256')
    props_digest_value = etree.SubElement(props_ref, f'{{{DS_NS}}}DigestValue')
    props_digest_value.text = signed_props_digest

    doc_signatures = etree.Element(
        f'{{{SIG_NS}}}UBLDocumentSignatures',
        nsmap={'sig': SIG_NS, 'sac': SAC_NS, 'sbc': SBC_NS, 'ds': DS_NS},
    )
    signature_information = etree.SubElement(doc_signatures, f'{{{SAC_NS}}}SignatureInformation')
    sig_info_id = etree.SubElement(signature_information, f'{{{CBC_NS}}}ID')
    sig_info_id.text = SIGNATURE_INFORMATION_ID
    referenced_signature_id = etree.SubElement(signature_information, f'{{{SBC_NS}}}ReferencedSignatureID')
    referenced_signature_id.text = REFERENCED_SIGNATURE_ID
    signature_information.append(sig)

    return doc_signatures


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
    issuer_name = ''
    serial_number = ''
    cert_signature_b64 = ''
    if credential and 'binarySecurityToken' in credential:
        # ZATCA's binarySecurityToken is the base64-of-DER certificate, base64-encoded
        # again for transport. Undo the outer encoding to get the base64-of-DER string
        # that ds:X509Certificate/CertDigest expect.
        certificate_b64 = base64.b64decode(credential['binarySecurityToken']).decode('ascii')
        certificate = x509.load_der_x509_certificate(base64.b64decode(certificate_b64))
        issuer_name = certificate.issuer.rfc4514_string().replace(',', ', ')
        serial_number = str(certificate.serial_number)
        # The QR code's 9th field is the CA's own signature over our device
        # certificate (proves the cert's chain of trust), not a signature we
        # produce — confirmed against ZATCA's official sample QR.
        cert_signature_b64 = base64.b64encode(certificate.signature).decode('ascii')

    root = etree.fromstring(xml_bytes)
    # Find IssueDate/Time for signing timestamp
    issue_date = root.findtext(f'{{{CBC_NS}}}IssueDate') or '2024-01-01'
    issue_time = root.findtext(f'{{{CBC_NS}}}IssueTime') or '00:00:00'
    signing_time = f"{issue_date}T{issue_time}"

    xades_sig = _build_xades_signature(
        invoice_hash, signature_b64, certificate_b64, public_key_b64, signing_time,
        issuer_name, serial_number,
    )

    # Embed into ExtensionContent
    ext_content = root.find(
        f'.//{{{EXT_NS}}}ExtensionContent'
    )
    if ext_content is not None:
        ext_content.append(xades_sig)

    signed_xml_bytes = etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=False)
    return signed_xml_bytes, signature_b64, public_key_b64, cert_signature_b64
