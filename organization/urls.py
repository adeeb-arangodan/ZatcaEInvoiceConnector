from django.urls import path

from invoices.views_template import (
    CustomReturnInvoiceFormView,
    FailedSubmissionListView,
    FailedSubmissionResubmitView,
    InvoiceDetailView,
    InvoiceExportView,
    InvoiceListView,
    InvoiceResubmitView,
    InvoiceXmlDownloadView,
    InvoiceXmlView,
    InvoiceXmlZipExportView,
    ReturnInvoiceFormView,
)

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
    path("organizations/<int:pk>/invoices/export/", InvoiceExportView.as_view(), name="invoice-export"),
    path(
        "organizations/<int:pk>/invoices/xml/",
        InvoiceXmlZipExportView.as_view(),
        name="invoice-xml-zip-export",
    ),
    path(
        "organizations/<int:pk>/invoices/<int:invoice_pk>/",
        InvoiceDetailView.as_view(),
        name="invoice-detail",
    ),
    path(
        "organizations/<int:pk>/invoices/<int:invoice_pk>/xml/",
        InvoiceXmlView.as_view(),
        name="invoice-xml",
    ),
    path(
        "organizations/<int:pk>/invoices/<int:invoice_pk>/xml/download/",
        InvoiceXmlDownloadView.as_view(),
        name="invoice-xml-download",
    ),
    path(
        "organizations/<int:pk>/invoices/<int:invoice_pk>/return/",
        ReturnInvoiceFormView.as_view(),
        name="invoice-return",
    ),
    path(
        "organizations/<int:pk>/invoices/<int:invoice_pk>/return/custom/",
        CustomReturnInvoiceFormView.as_view(),
        name="invoice-return-custom",
    ),
    path(
        "organizations/<int:pk>/invoices/<int:invoice_pk>/resubmit/",
        InvoiceResubmitView.as_view(),
        name="invoice-resubmit",
    ),
    path(
        "organizations/<int:pk>/invoices/failed/",
        FailedSubmissionListView.as_view(),
        name="failed-submission-list",
    ),
    path(
        "organizations/<int:pk>/invoices/failed/<int:failure_pk>/resubmit/",
        FailedSubmissionResubmitView.as_view(),
        name="failed-submission-resubmit",
    ),
]
