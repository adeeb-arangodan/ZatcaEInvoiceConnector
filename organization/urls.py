from django.urls import path

from invoices.views_template import InvoiceListView, ReturnInvoiceFormView

from .views import (
    DeviceCreateView,
    DeviceDeleteView,
    OrganizationCreateView,
    OrganizationDashboardView,
    OrganizationDeleteView,
    OrganizationListView,
    OrganizationUpdateView,
    landing,
)

app_name = "organization"

urlpatterns = [
    path("", landing, name="landing"),
    path("organizations/", OrganizationListView.as_view(), name="list"),
    path("organizations/add/", OrganizationCreateView.as_view(), name="create"),
    path("organizations/<int:pk>/", OrganizationDashboardView.as_view(), name="dashboard"),
    path("organizations/<int:pk>/edit/", OrganizationUpdateView.as_view(), name="update"),
    path("organizations/<int:pk>/delete/", OrganizationDeleteView.as_view(), name="delete"),
    path(
        "organizations/<int:organization_pk>/devices/add/",
        DeviceCreateView.as_view(),
        name="device-create",
    ),
    path("devices/<int:pk>/delete/", DeviceDeleteView.as_view(), name="device-delete"),
    path("organizations/<int:pk>/invoices/", InvoiceListView.as_view(), name="invoice-list"),
    path(
        "organizations/<int:pk>/invoices/<int:invoice_pk>/return/",
        ReturnInvoiceFormView.as_view(),
        name="invoice-return",
    ),
]
