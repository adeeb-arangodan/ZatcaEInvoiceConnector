from rest_framework import serializers

from organization.models import Device

BILLING_REFERENCE_REQUIRED_CODES = {'381', '383'}


class ItemSerializer(serializers.Serializer):
    slno = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    qty = serializers.DecimalField(max_digits=15, decimal_places=4)
    price = serializers.DecimalField(max_digits=15, decimal_places=4)
    vat_type = serializers.ChoiceField(choices=['S', 'Z', 'E', 'O'])


class InvoiceSubmissionSerializer(serializers.Serializer):
    device_asset_id = serializers.CharField()
    invoice_number = serializers.CharField()
    issue_date = serializers.DateField()
    issue_time = serializers.TimeField()
    invoice_type_code = serializers.CharField()
    invoice_type_code_name_attribute = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    customer_name = serializers.CharField()
    customer_vat = serializers.CharField(required=False, allow_blank=True, default='')
    customer_building_number = serializers.CharField(required=False, allow_blank=True, default='')
    customer_street = serializers.CharField(required=False, allow_blank=True, default='')
    customer_district = serializers.CharField(required=False, allow_blank=True, default='')
    customer_city = serializers.CharField(required=False, allow_blank=True, default='')
    customer_postal_zone = serializers.CharField(required=False, allow_blank=True, default='')
    customer_country_code = serializers.CharField(required=False, allow_blank=True, default='SA')
    customer_id_number = serializers.CharField(required=False, allow_blank=True, default='')
    customer_id_type = serializers.ChoiceField(
        choices=['NAT', 'IQA', 'PAS', 'CRN', 'MOM', 'MLS', '700', 'SAG', 'GCC', 'OTH'],
        required=False, allow_blank=True, default='NAT',
    )
    payment_mode = serializers.CharField(required=False, allow_blank=True, default='')
    doc_level_discount_vat = serializers.DecimalField(
        required=False, default=0, max_digits=15, decimal_places=2)
    doc_level_discount_novat = serializers.DecimalField(
        required=False, default=0, max_digits=15, decimal_places=2)
    advance_paid = serializers.DecimalField(
        required=False, default=0, max_digits=15, decimal_places=2)
    billing_reference = serializers.CharField(required=False, allow_blank=True, default='')
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    items = serializers.ListField(child=ItemSerializer(), min_length=1)

    def __init__(self, *args, **kwargs):
        self._organization = kwargs.pop('organization', None)
        self._resolved_device = None
        super().__init__(*args, **kwargs)

    def validate_device_asset_id(self, value):
        if self._organization is None:
            raise serializers.ValidationError("Serializer requires an organization context.")
        try:
            device = Device.objects.get(organization=self._organization, asset_id=value)
        except Device.DoesNotExist:
            raise serializers.ValidationError(
                "No device with this asset ID belongs to your organization."
            )
        self._resolved_device = device
        return value

    def validate(self, data):
        invoice_type_code = data.get('invoice_type_code', '')
        billing_reference = data.get('billing_reference', '')
        if invoice_type_code in BILLING_REFERENCE_REQUIRED_CODES and not billing_reference:
            raise serializers.ValidationError(
                {'billing_reference': 'This field is required for credit notes (381) and debit notes (383).'}
            )
        if invoice_type_code in BILLING_REFERENCE_REQUIRED_CODES and not data.get('reason'):
            raise serializers.ValidationError(
                {'reason': 'This field is required for credit notes (381) and debit notes (383) — '
                           'ZATCA (BR-KSA-17) requires the reason for issuance.'}
            )
        return data

    def get_resolved_device(self):
        return self._resolved_device


class ReturnInvoiceSerializer(serializers.Serializer):
    system_return_number = serializers.CharField(required=False, allow_blank=True, default='')
    reason = serializers.CharField(required=False, allow_blank=True, default='')
