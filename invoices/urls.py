from django.urls import path

from .views import InvoiceSubmitView

app_name = 'invoices'

urlpatterns = [
    path('invoices/submit/', InvoiceSubmitView.as_view(), name='submit'),
]
