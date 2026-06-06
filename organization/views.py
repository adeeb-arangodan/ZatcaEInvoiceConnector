from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .models import Device, Organization
from .services import generate_device_csr, register_device_in_zatca


class OrganizationListView(ListView):
    model = Organization
    context_object_name = "organizations"
    template_name = "organization/organization_list.html"

    def get_queryset(self):
        return Organization.objects.prefetch_related("devices")


class OrganizationCreateView(CreateView):
    model = Organization
    fields = [
        "name",
        "branch_name",
        "industry_category",
        "vat_number",
        "country_code",
        "national_address_code",
        "street_name",
        "building_number",
        "city_sub_division",
        "city_name",
        "postal_zone",
        "cr_number",
        "invoice_category",
    ]
    template_name = "organization/organization_form.html"
    success_url = reverse_lazy("organization:list")


class OrganizationUpdateView(UpdateView):
    model = Organization
    fields = [
        "name",
        "branch_name",
        "industry_category",
        "vat_number",
        "country_code",
        "national_address_code",
        "street_name",
        "building_number",
        "city_sub_division",
        "city_name",
        "postal_zone",
        "cr_number",
        "invoice_category",
    ]
    template_name = "organization/organization_form.html"
    success_url = reverse_lazy("organization:list")

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.devices.exists():
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)


class OrganizationDeleteView(DeleteView):
    model = Organization
    template_name = "organization/organization_confirm_delete.html"
    success_url = reverse_lazy("organization:list")


class DeviceCreateView(CreateView):
    model = Device
    fields = ["asset_id", "egs_sw_serial_number", "otp"]
    template_name = "organization/device_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.organization = Organization.objects.get(pk=self.kwargs["organization_pk"])
        if not self.organization.is_active:
            messages.error(
                request,
                f'"{self.organization}" is not active. '
                "An administrator must activate it before devices can be added.",
            )
            return HttpResponseRedirect(reverse("organization:list"))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization"] = self.organization
        return context

    def form_valid(self, form):
        form.instance.organization = self.organization
        response = super().form_valid(form)
        self.object.csr_content = generate_device_csr(self.object)
        self.object.csid_response = register_device_in_zatca(self.object)
        self.object.save(update_fields=["csr_content", "csid_response", "updated_at"])
        return response

    def get_success_url(self):
        return reverse("organization:list")


class DeviceDeleteView(DeleteView):
    model = Device
    template_name = "organization/device_confirm_delete.html"
    success_url = reverse_lazy("organization:list")
