import base64
import hashlib
import io

from django.db import transaction

INITIAL_PIH = "NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjOTliNTk4NTYxMDYyNTkwNmU2NDBiOTljYmQ1MDAzYQ=="


def hash_invoice_xml(xml_bytes):
    from lxml import etree

    root = etree.fromstring(xml_bytes)
    buf = io.BytesIO()
    root.getroottree().write_c14n(buf, exclusive=True, with_comments=False)
    canonical = buf.getvalue()
    digest = hashlib.sha256(canonical).digest()
    return base64.b64encode(digest).decode('ascii')


def get_icv_and_pih_atomically(device):
    from organization.models import Device

    with transaction.atomic():
        locked = Device.objects.select_for_update().get(pk=device.pk)
        locked.invoice_counter += 1
        locked.save(update_fields=['invoice_counter'])
        pih = locked.last_invoice_hash or INITIAL_PIH
        return locked.invoice_counter, pih


def store_invoice_hash(device, invoice_hash):
    from organization.models import Device

    Device.objects.filter(pk=device.pk).update(last_invoice_hash=invoice_hash)
