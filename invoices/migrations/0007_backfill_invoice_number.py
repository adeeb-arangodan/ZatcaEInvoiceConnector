from collections import defaultdict

from django.db import migrations


def backfill_and_disambiguate(apps, schema_editor):
    InvoiceSubmission = apps.get_model('invoices', 'InvoiceSubmission')

    for submission in InvoiceSubmission.objects.all():
        submission.invoice_number = submission.payload.get('invoice_number') or f'UNSET-{submission.pk}'
        submission.save(update_fields=['invoice_number'])

    # Disambiguate any pre-existing duplicates (same org + document_type +
    # invoice_number) so the unique constraint added in the next migration
    # can apply. Keeps the highest-ICV row as the canonical number, renames
    # the older ones with a -DUP-{icv} suffix. Payload is left untouched —
    # it's the immutable record of what was actually signed and sent to ZATCA.
    groups = defaultdict(list)
    for submission in InvoiceSubmission.objects.order_by('icv'):
        key = (submission.organization_id, submission.document_type, submission.invoice_number)
        groups[key].append(submission)

    for rows in groups.values():
        if len(rows) <= 1:
            continue
        for row in rows[:-1]:
            row.invoice_number = f'{row.invoice_number}-DUP-{row.icv}'
            row.save(update_fields=['invoice_number'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0006_invoicesubmission_invoice_number'),
    ]

    operations = [
        migrations.RunPython(backfill_and_disambiguate, noop_reverse),
    ]
