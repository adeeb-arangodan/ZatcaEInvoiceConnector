from django.urls import path

from .views import (
    DeviceCreateView,
    DeviceDeleteView,
    OrganizationCreateView,
    OrganizationDeleteView,
    OrganizationListView,
    OrganizationUpdateView,
)

app_name = "organization"

urlpatterns = [
    path("", OrganizationListView.as_view(), name="list"),
    path("organizations/add/", OrganizationCreateView.as_view(), name="create"),
    path("organizations/<int:pk>/edit/", OrganizationUpdateView.as_view(), name="update"),
    path("organizations/<int:pk>/delete/", OrganizationDeleteView.as_view(), name="delete"),
    path(
        "organizations/<int:organization_pk>/devices/add/",
        DeviceCreateView.as_view(),
        name="device-create",
    ),
    path("devices/<int:pk>/delete/", DeviceDeleteView.as_view(), name="device-delete"),
]
