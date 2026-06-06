from rest_framework.permissions import BasePermission


class IsActiveOrganization(BasePermission):
    message = 'This organization is not active.'

    def has_permission(self, request, view):
        return (
            request.user is not None
            and hasattr(request.user, 'is_active')
            and request.user.is_active is True
        )
