from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import OrganizationApiKeyAuthentication
from .models import InvoiceSubmission
from .permissions import IsActiveOrganization
from .pipeline import InvoiceSubmissionRejected, process_invoice_submission
from .serializers import InvoiceNumbersQuerySerializer, InvoiceSubmissionSerializer, ReturnInvoiceSerializer
from .services import DuplicateReturnNumberError, create_return_credit_note


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

        try:
            submission = process_invoice_submission(
                organization=request.user,
                device=device,
                validated_data=serializer.validated_data,
            )
        except InvoiceSubmissionRejected as exc:
            return Response(
                {
                    'failure_id': exc.failure.pk,
                    'detail': 'ZATCA rejected this submission. Correct the payload and resubmit.',
                    'zatca_status': exc.failure.zatca_response,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(
            {
                'id': submission.pk,
                'status': submission.status,
                'qr_code': submission.qr_code_data,
                'invoice_uuid': str(submission.invoice_uuid) if submission.invoice_uuid else None,
                'zatca_status': submission.zatca_response,
            },
            status=status.HTTP_201_CREATED,
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

        try:
            credit_note = create_return_credit_note(
                organization=request.user,
                device=original_invoice.device,
                original_invoice=original_invoice,
                system_return_number=serializer.validated_data['system_return_number'],
                reason=serializer.validated_data['reason'],
            )
        except DuplicateReturnNumberError as exc:
            return Response({'system_return_number': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvoiceSubmissionRejected as exc:
            return Response(
                {
                    'failure_id': exc.failure.pk,
                    'detail': 'ZATCA rejected this credit note. Correct the payload and resubmit.',
                    'zatca_status': exc.failure.zatca_response,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
            status=status.HTTP_201_CREATED,
        )


class InvoiceNumbersByDateView(APIView):
    authentication_classes = [OrganizationApiKeyAuthentication]
    permission_classes = [IsActiveOrganization]

    def get(self, request):
        serializer = InvoiceNumbersQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        date = serializer.validated_data['date']
        document_type = serializer.validated_data.get('document_type') or ''

        queryset = InvoiceSubmission.objects.filter(
            organization=request.user,
            payload__issue_date=date.isoformat(),
        )
        if document_type:
            queryset = queryset.filter(document_type=document_type)

        invoice_numbers = list(
            queryset.order_by('icv').values_list('payload__invoice_number', flat=True)
        )
        return Response({
            'date': date.isoformat(),
            'document_type': document_type or 'all',
            'count': len(invoice_numbers),
            'invoice_numbers': invoice_numbers,
        })
