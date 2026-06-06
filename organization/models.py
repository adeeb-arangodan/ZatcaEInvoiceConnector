from django.db import models


class Organization(models.Model):
    INVOICE_CATEGORY_STANDARD_AND_SIMPLIFIED = "1100"
    INVOICE_CATEGORY_STANDARD_ONLY = "1000"
    INVOICE_CATEGORY_SIMPLIFIED_ONLY = "0100"

    INVOICE_CATEGORY_CHOICES = [
        (INVOICE_CATEGORY_STANDARD_AND_SIMPLIFIED, "Standard & Simplified"),
        (INVOICE_CATEGORY_STANDARD_ONLY, "Standard Only"),
        (INVOICE_CATEGORY_SIMPLIFIED_ONLY, "Simplified Only"),
    ]

    name = models.CharField(max_length=255)
    branch_name = models.CharField(max_length=255)
    industry_category = models.CharField(max_length=100)
    vat_number = models.CharField(max_length=15, unique=True)
    country_code = models.CharField(max_length=2)
    national_address_code = models.CharField(max_length=20)
    street_name = models.CharField(max_length=255)
    building_number = models.CharField(max_length=10)
    city_sub_division = models.CharField(max_length=255)
    city_name = models.CharField(max_length=100)
    postal_zone = models.CharField(max_length=10)
    cr_number = models.CharField(max_length=20, unique=True)
    invoice_category = models.CharField(
        max_length=4,
        choices=INVOICE_CATEGORY_CHOICES,
        default=INVOICE_CATEGORY_STANDARD_AND_SIMPLIFIED,
    )
    is_active = models.BooleanField(
        default=False,
        verbose_name="Active",
        help_text="Only active organizations can register devices.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "branch_name"]

    def __str__(self):
        return f"{self.name} ({self.branch_name})"


class Device(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="devices",
    )
    asset_id = models.CharField(max_length=255)
    egs_sw_serial_number = models.CharField(max_length=255)
    otp = models.CharField(max_length=255)
    csr_content = models.TextField(blank=True)
    csid_response = models.JSONField(null=True, blank=True)
    pcsid = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "asset_id"]
        unique_together = [("organization", "asset_id")]

    def __str__(self):
        return f"{self.organization.name} - {self.asset_id}"


class DeviceKeyMaterial(models.Model):
    device = models.OneToOneField(
        Device,
        on_delete=models.CASCADE,
        related_name="key_material",
    )
    private_key_pem = models.TextField()
    public_key_pem = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Keys for {self.device}"
