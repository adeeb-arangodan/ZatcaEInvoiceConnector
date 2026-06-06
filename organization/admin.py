import secrets

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


admin.site.register(Device)
