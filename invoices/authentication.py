from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from organization.models import Organization


class OrganizationApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('ApiKey '):
            return None
        token = auth_header[len('ApiKey '):]
        if not token:
            raise AuthenticationFailed('API key must not be empty.')
        try:
            organization = Organization.objects.get(api_key=token)
        except Organization.DoesNotExist:
            raise AuthenticationFailed('Invalid API key.')
        return (organization, None)

    def authenticate_header(self, request):
        return 'ApiKey'
