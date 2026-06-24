from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import Http404


def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


class OrgScopedMixin:
    """Restricts access to the organization owned by request.user, unless they're an admin.

    Must come after LoginRequiredMixin in the MRO so anonymous users are
    redirected to login rather than hitting the 404 below. Views whose URL
    pk doesn't directly identify the organization (e.g. DeviceDeleteView,
    keyed by device pk) should override get_organization().
    """

    def get_organization(self):
        from .models import Organization

        if not hasattr(self, "_org_scoped_organization"):
            self._org_scoped_organization = Organization.objects.get(pk=self.kwargs.get("pk"))
        return self._org_scoped_organization

    def dispatch(self, request, *args, **kwargs):
        if not is_admin(request.user):
            try:
                organization = self.get_organization()
            except Exception:
                raise Http404
            if organization.owner_user_id != request.user.id:
                raise Http404
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return is_admin(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise Http404
