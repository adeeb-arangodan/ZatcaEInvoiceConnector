import secrets

from django.db import migrations, models


def generate_api_keys(apps, schema_editor):
    Organization = apps.get_model('organization', 'Organization')
    for org in Organization.objects.filter(api_key=''):
        org.api_key = secrets.token_hex(32)
        org.save(update_fields=['api_key'])


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0006_organization_is_active'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='api_key',
            field=models.CharField(blank=True, editable=False, max_length=64, default=''),
        ),
        migrations.RunPython(generate_api_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='organization',
            name='api_key',
            field=models.CharField(blank=True, editable=False, max_length=64, unique=True),
        ),
    ]
