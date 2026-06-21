import base64
import hashlib
import io

from django.db import transaction

INITIAL_PIH = "NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjOTliNTk4NTYxMDYyNTkwNmU2NDBiOTljYmQ1MDAzYQ=="

EXT_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
CAC_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
CBC_NS = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'


def _remove_preserving_tail(el):
    # XPath-based exclusion (what ds:Reference's XPath transforms describe)
    # removes only the matched element, leaving sibling whitespace text nodes
    # intact. A plain Element.remove() discards the removed element's tail
    # text too, which shifts the canonical bytes — so reattach it first.
    parent = el.getparent()
    prev = el.getprevious()
    if el.tail:
        if prev is not None:
            prev.tail = (prev.tail or '') + el.tail
        else:
            parent.text = (parent.text or '') + el.tail
    parent.remove(el)


def hash_invoice_xml(xml_bytes):
    from lxml import etree

    # ZATCA's invoice hash is computed on the document with ext:UBLExtensions,
    # cac:Signature, and the QR cac:AdditionalDocumentReference removed — the
    # same exclusion the XAdES ds:Reference XPath transforms declare. Stripping
    # them here (rather than relying on them being empty placeholders) keeps the
    # hash identical whether it's computed before or after signing/QR embedding.
    root = etree.fromstring(xml_bytes)

    for el in root.findall(f'{{{EXT_NS}}}UBLExtensions'):
        _remove_preserving_tail(el)

    for el in root.findall(f'{{{CAC_NS}}}Signature'):
        _remove_preserving_tail(el)

    for adr in root.findall(f'{{{CAC_NS}}}AdditionalDocumentReference'):
        id_el = adr.find(f'{{{CBC_NS}}}ID')
        if id_el is not None and id_el.text == 'QR':
            _remove_preserving_tail(adr)

    # The declared CanonicalizationMethod is C14N 1.1 (inclusive), not exclusive
    # C14N, and the two produce different bytes — must match for ZATCA to
    # recompute the same hash/digests we signed.
    buf = io.BytesIO()
    root.getroottree().write_c14n(buf, exclusive=False, with_comments=False)
    canonical = buf.getvalue()
    digest = hashlib.sha256(canonical).digest()
    return base64.b64encode(digest).decode('ascii')


def get_icv_and_pih_atomically(organization):
    from organization.models import Organization

    with transaction.atomic():
        locked = Organization.objects.select_for_update().get(pk=organization.pk)
        locked.invoice_counter += 1
        locked.save(update_fields=['invoice_counter'])
        pih = locked.last_invoice_hash or INITIAL_PIH
        return locked.invoice_counter, pih


def store_invoice_hash(organization, invoice_hash):
    from organization.models import Organization

    Organization.objects.filter(pk=organization.pk).update(last_invoice_hash=invoice_hash)
