from django.urls import path

from .views import InvoiceNumbersByDateView, InvoiceReturnView, InvoiceSubmitView

app_name = 'invoices'

urlpatterns = [
    path('invoices/submit/', InvoiceSubmitView.as_view(), name='submit'),
    path('invoices/<int:pk>/return/', InvoiceReturnView.as_view(), name='return'),
    path('invoices/numbers/', InvoiceNumbersByDateView.as_view(), name='numbers-by-date'),
]
