from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import OrganizationSignupForm
from .mixins import AdminRequiredMixin, OrgScopedMixin, is_admin
from .models import Device, Organization
from .services import acquire_pcsid_for_device, generate_device_csr, register_device_in_zatca


def _credential_acquired(result):
    return bool(result) and "binarySecurityToken" in result


def _credential_error_detail(result):
    if not result:
        return "no response was received from ZATCA."
    return result.get("error", result)


def landing(request):
    if not request.user.is_authenticated:
        return render(request, "organization/welcome.html")
    if is_admin(request.user):
        return redirect("organization:list")
    organization = getattr(request.user, "organization", None)
    if organization is None:
        return render(request, "organization/welcome.html")
    return redirect("organization:dashboard", pk=organization.pk)


class OrganizationListView(AdminRequiredMixin, ListView):
    model = Organization
    context_object_name = "organizations"
    template_name = "organization/organization_list.html"

    def get_queryset(self):
        return Organization.objects.prefetch_related("devices")


class OrganizationDashboardView(LoginRequiredMixin, OrgScopedMixin, DetailView):
    model = Organization
    context_object_name = "organization"
    template_name = "organization/organization_dashboard.html"


class OrganizationCreateView(CreateView):
    model = Organization
    form_class = OrganizationSignupForm
    template_name = "organization/organization_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        auth_login(self.request, self.object.owner_user)
        return response

    def get_success_url(self):
        return reverse("organization:dashboard", kwargs={"pk": self.object.pk})


class OrganizationUpdateView(LoginRequiredMixin, OrgScopedMixin, UpdateView):
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

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.devices.exists():
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("organization:dashboard", kwargs={"pk": self.object.pk})


class OrganizationDeleteView(AdminRequiredMixin, DeleteView):
    model = Organization
    template_name = "organization/organization_confirm_delete.html"
    success_url = reverse_lazy("organization:list")


class DeviceCreateView(LoginRequiredMixin, OrgScopedMixin, CreateView):
    model = Device
    fields = ["asset_id", "egs_sw_serial_number", "otp"]
    template_name = "organization/device_form.html"

    def get_organization(self):
        if not hasattr(self, "_org_scoped_organization"):
            self._org_scoped_organization = get_object_or_404(
                Organization, pk=self.kwargs["organization_pk"]
            )
        return self._org_scoped_organization

    def get(self, request, *args, **kwargs):
        blocked = self._block_if_inactive(request)
        if blocked:
            return blocked
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        blocked = self._block_if_inactive(request)
        if blocked:
            return blocked
        return super().post(request, *args, **kwargs)

    def _block_if_inactive(self, request):
        self.organization = self.get_organization()
        if not self.organization.is_active:
            messages.error(
                request,
                f'"{self.organization}" is not active. '
                "An administrator must activate it before devices can be added.",
            )
            return HttpResponseRedirect(reverse("organization:dashboard", kwargs={"pk": self.organization.pk}))
        return None

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

        if not _credential_acquired(self.object.csid_response):
            messages.error(
                self.request,
                "Failed to obtain CSID for this device: "
                f"{_credential_error_detail(self.object.csid_response)}",
            )
            return response

        messages.success(self.request, "CSID obtained for this device.")

        try:
            pcsid_result = acquire_pcsid_for_device(self.object)
        except Exception as exc:
            messages.error(
                self.request,
                f"Failed to obtain PCSID for this device: {exc}. "
                "Invoices will use compliance credentials until PCSID is available.",
            )
            return response

        if _credential_acquired(pcsid_result):
            messages.success(self.request, "PCSID obtained for this device.")
        else:
            messages.error(
                self.request,
                "Failed to obtain PCSID for this device: "
                f"{_credential_error_detail(pcsid_result)}. "
                "Invoices will use compliance credentials until PCSID is available.",
            )
        return response

    def get_success_url(self):
        return reverse("organization:dashboard", kwargs={"pk": self.organization.pk})


class DeviceDeleteView(LoginRequiredMixin, OrgScopedMixin, DeleteView):
    model = Device
    template_name = "organization/device_confirm_delete.html"

    def get_organization(self):
        if not hasattr(self, "_org_scoped_organization"):
            device = get_object_or_404(Device, pk=self.kwargs["pk"])
            self._org_scoped_organization = device.organization
        return self._org_scoped_organization

    def get_success_url(self):
        return reverse("organization:dashboard", kwargs={"pk": self.get_organization().pk})
