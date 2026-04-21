from django.contrib import admin

from .models import Organization


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
    )
    search_fields = ("name", "branch_name", "vat_number", "cr_number")
    list_filter = ("invoice_category", "country_code", "industry_category")
