from rest_framework import serializers

from organization.models import Device


class LineItemSerializer(serializers.Serializer):
    description = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=4)
    unit_price = serializers.DecimalField(max_digits=15, decimal_places=4)
    tax_percent = serializers.DecimalField(max_digits=5, decimal_places=2)


class InvoiceSubmissionSerializer(serializers.Serializer):
    DOCUMENT_TYPE_CHOICES = ['invoice', 'credit_note', 'debit_note']
    BILLING_REFERENCE_REQUIRED_TYPES = ['credit_note', 'debit_note']

    device_asset_id = serializers.CharField()
    document_type = serializers.ChoiceField(choices=DOCUMENT_TYPE_CHOICES)
    invoice_number = serializers.CharField()
    issue_date = serializers.DateField()
    issue_time = serializers.TimeField()
    buyer_vat = serializers.CharField(required=False, allow_blank=True)
    buyer_name = serializers.CharField(required=False, allow_blank=True)
    line_items = serializers.ListField(child=LineItemSerializer(), min_length=1)
    tax_total = serializers.DecimalField(max_digits=15, decimal_places=2)
    payable_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    billing_reference = serializers.CharField(required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True)

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
        document_type = data.get('document_type')
        billing_reference = data.get('billing_reference', '')
        if document_type in self.BILLING_REFERENCE_REQUIRED_TYPES and not billing_reference:
            raise serializers.ValidationError(
                {'billing_reference': 'This field is required for credit_note and debit_note.'}
            )
        return data

    def get_resolved_device(self):
        return self._resolved_device
