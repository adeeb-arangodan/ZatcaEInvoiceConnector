from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import OrganizationApiKeyAuthentication
from .models import InvoiceSubmission
from .permissions import IsActiveOrganization
from .serializers import InvoiceSubmissionSerializer


class InvoiceSubmitView(APIView):
    authentication_classes = [OrganizationApiKeyAuthentication]
    permission_classes = [IsActiveOrganization]

    def post(self, request):
        serializer = InvoiceSubmissionSerializer(
            data=request.data,
            organization=request.user,
        )
        serializer.is_valid(raise_exception=True)
        submission = InvoiceSubmission.objects.create(
            organization=request.user,
            device=serializer.get_resolved_device(),
            document_type=serializer.validated_data['document_type'],
            payload=request.data,
            status=InvoiceSubmission.STATUS_RECEIVED,
        )
        return Response(
            {
                'id': submission.pk,
                'status': submission.status,
                'message': 'Invoice received and queued for processing.',
            },
            status=status.HTTP_201_CREATED,
        )
