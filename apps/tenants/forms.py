"""Self-service signup form.

Validates subdomain slug, email uniqueness, and password strength before
hand-off to `provision_organization`. Validation order matters:
slug-format → reserved → uniqueness, so error messages stay specific.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Organization
from .validators import validate_subdomain_slug


class SignupForm(forms.Form):
    company_name = forms.CharField(
        max_length=120,
        label="Firmenname",
        widget=forms.TextInput(attrs={"autofocus": "autofocus"}),
    )
    slug = forms.CharField(
        max_length=30,
        label="Subdomain",
        help_text="z.B. acme → acme.stockpilot.app",
    )
    email = forms.EmailField(label="E-Mail")
    password = forms.CharField(
        widget=forms.PasswordInput,
        label="Passwort",
        min_length=8,
    )

    def clean_slug(self):
        slug = (self.cleaned_data["slug"] or "").lower().strip()
        validate_subdomain_slug(slug)  # raises ValidationError on bad input
        if Organization.objects.filter(slug=slug).exists():
            raise ValidationError(f"'{slug}' ist schon vergeben.")
        return slug

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                "Für diese E-Mail existiert schon ein Account. Logge dich "
                "ein und nutze 'Org wechseln'."
            )
        return email

    def clean_password(self):
        pwd = self.cleaned_data["password"]
        validate_password(pwd)  # Django's built-in validators
        return pwd

    def clean_company_name(self):
        name = self.cleaned_data["company_name"].strip()
        if Organization.objects.filter(name__iexact=name).exists():
            raise ValidationError(
                "Eine Organisation mit diesem Namen existiert bereits."
            )
        return name
