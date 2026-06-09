from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import OrganizationApiKeyAuthentication
from .permissions import IsActiveOrganization
from .pipeline import process_invoice_submission
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
        device = serializer.get_resolved_device()

        if not device.csid_response or 'binarySecurityToken' not in device.csid_response:
            return Response(
                {'detail': 'Device has no valid compliance CSID. Please re-register the device.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        submission = process_invoice_submission(
            organization=request.user,
            device=device,
            validated_data=serializer.validated_data,
        )
        http_status = (
            status.HTTP_201_CREATED
            if submission.status == 'submitted'
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return Response(
            {
                'id': submission.pk,
                'status': submission.status,
                'qr_code': submission.qr_code_data,
                'invoice_uuid': str(submission.invoice_uuid) if submission.invoice_uuid else None,
                'zatca_status': submission.zatca_response,
            },
            status=http_status,
        )
