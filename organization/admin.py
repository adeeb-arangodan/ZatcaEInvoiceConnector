import secrets

from django.contrib import admin, messages

from .models import Device, Organization
from .services import reissue_device_credentials


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "branch_name",
        "vat_number",
        "cr_number",
        "invoice_category",
        "city_name",
        "country_code",
        "is_active",
        "api_key",
    )
    search_fields = ("name", "branch_name", "vat_number", "cr_number")
    list_filter = ("is_active", "invoice_category", "country_code", "industry_category")
    readonly_fields = ("api_key",)
    actions = ["activate_organizations", "deactivate_organizations", "regenerate_api_key"]

    @admin.action(description="Activate selected organizations")
    def activate_organizations(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} organization(s) activated.", messages.SUCCESS)

    @admin.action(description="Deactivate selected organizations")
    def deactivate_organizations(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} organization(s) deactivated.", messages.WARNING)

    @admin.action(description="Regenerate API key for selected organizations")
    def regenerate_api_key(self, request, queryset):
        for org in queryset:
            org.api_key = secrets.token_hex(32)
            org.save(update_fields=["api_key", "updated_at"])
        self.message_user(request, f"API key regenerated for {queryset.count()} organization(s).", messages.SUCCESS)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("asset_id", "organization", "egs_sw_serial_number", "updated_at")
    search_fields = ("asset_id", "egs_sw_serial_number", "organization__name")
    list_filter = ("organization",)
    actions = ["reissue_credentials"]

    def has_delete_permission(self, request, obj=None):
        if not super().has_delete_permission(request, obj):
            return False
        if obj is not None and (obj.invoice_submissions.exists() or obj.invoice_submission_failures.exists()):
            return False
        return True

    @admin.action(description="Reissue ZATCA credentials (CSR + CSID + PCSID) using current OTP")
    def reissue_credentials(self, request, queryset):
        for device in queryset:
            try:
                reissue_device_credentials(device)
            except Exception as exc:
                self.message_user(
                    request, f'Failed to reissue credentials for "{device}": {exc}', messages.ERROR,
                )
                continue

            if device.pcsid and "binarySecurityToken" in device.pcsid:
                self.message_user(request, f'Reissued CSID and PCSID for "{device}".', messages.SUCCESS)
            elif device.csid_response and "binarySecurityToken" in device.csid_response:
                self.message_user(
                    request,
                    f'Reissued CSID for "{device}", but PCSID acquisition failed — '
                    "see device.pcsid for the error.",
                    messages.WARNING,
                )
            else:
                self.message_user(
                    request,
                    f'Failed to reissue CSID for "{device}" — see device.csid_response for the error. '
                    "Its OTP may be stale; set a fresh OTP from the ZATCA portal on the device and retry.",
                    messages.ERROR,
                )
