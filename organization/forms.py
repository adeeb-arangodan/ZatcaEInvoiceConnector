from captcha.fields import CaptchaField
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from .models import Organization

User = get_user_model()


class OrganizationSignupForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="Confirm password", widget=forms.PasswordInput)
    captcha = CaptchaField()

    class Meta:
        model = Organization
        fields = [
            "name",
            "email",
            "branch_name",
            "industry_category",
            "vat_number",
            "country_code",
            "national_address_code",
            "street_name",
            "building_number",
            "city_sub_division",
            "city_name",
            "postal_zone",
            "cr_number",
            "invoice_category",
        ]

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(username=email).exists() or Organization.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError({"password_confirm": "Passwords do not match."})
        if password:
            validate_password(password)
        return cleaned_data

    def save(self, commit=True):
        organization = super().save(commit=False)
        with transaction.atomic():
            user = User.objects.create_user(
                username=self.cleaned_data["email"],
                email=self.cleaned_data["email"],
                password=self.cleaned_data["password"],
                is_staff=False,
            )
            organization.owner_user = user
            organization.save()
        return organization
