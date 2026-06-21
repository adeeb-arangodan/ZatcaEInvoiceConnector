from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0002_invoicesubmission_invoice_hash_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoicesubmission',
            name='icv',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='invoicesubmission',
            name='status',
            field=models.CharField(
                choices=[
                    ('received', 'Received'),
                    ('processing', 'Processing'),
                    ('submitted', 'Submitted'),
                    ('not_submitted', 'Not Submitted'),
                ],
                default='received',
                max_length=20,
            ),
        ),
    ]
