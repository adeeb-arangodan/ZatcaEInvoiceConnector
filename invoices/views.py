from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import OrganizationApiKeyAuthentication
from .models import InvoiceSubmission
from .permissions import IsActiveOrganization
from .pipeline import process_invoice_submission
from .serializers import InvoiceSubmissionSerializer, ReturnInvoiceSerializer
from .services import create_return_credit_note


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


class InvoiceReturnView(APIView):
    authentication_classes = [OrganizationApiKeyAuthentication]
    permission_classes = [IsActiveOrganization]

    def post(self, request, pk):
        original_invoice = get_object_or_404(
            InvoiceSubmission, pk=pk, organization=request.user,
            document_type=InvoiceSubmission.DOCUMENT_TYPE_INVOICE,
        )

        serializer = ReturnInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not original_invoice.device.csid_response or 'binarySecurityToken' not in original_invoice.device.csid_response:
            return Response(
                {'detail': 'Originating device has no valid compliance CSID. Please re-register the device.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        credit_note = create_return_credit_note(
            organization=request.user,
            device=original_invoice.device,
            original_invoice=original_invoice,
            system_return_number=serializer.validated_data['system_return_number'],
            reason=serializer.validated_data['reason'],
        )
        http_status = (
            status.HTTP_201_CREATED
            if credit_note.status == 'submitted'
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return Response(
            {
                'id': credit_note.pk,
                'status': credit_note.status,
                'qr_code': credit_note.qr_code_data,
                'invoice_uuid': str(credit_note.invoice_uuid) if credit_note.invoice_uuid else None,
                'original_invoice_id': original_invoice.pk,
                'zatca_status': credit_note.zatca_response,
            },
            status=http_status,
        )
