from django.contrib import admin, messages

from .models import Device, Organization


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
    )
    search_fields = ("name", "branch_name", "vat_number", "cr_number")
    list_filter = ("is_active", "invoice_category", "country_code", "industry_category")
    actions = ["activate_organizations", "deactivate_organizations"]

    @admin.action(description="Activate selected organizations")
    def activate_organizations(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} organization(s) activated.", messages.SUCCESS)

    @admin.action(description="Deactivate selected organizations")
    def deactivate_organizations(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} organization(s) deactivated.", messages.WARNING)


admin.site.register(Device)
