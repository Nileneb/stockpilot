"""Subdomain slug validation for self-service signup."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

# Subdomains we never let a tenant claim. Lower-case match only.
RESERVED_SUBDOMAINS = frozenset(
    {
        "www",
        "admin",
        "api",
        "app",
        "auth",
        "mail",
        "support",
        "help",
        "status",
        "docs",
        "blog",
        "signup",
        "login",
        "logout",
        "dashboard",
        "static",
        "media",
        "assets",
        "stockpilot",
        "public",
        "localhost",
        "test",
        "staging",
        "prod",
        "production",
    }
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$")


def validate_subdomain_slug(value: str) -> None:
    """Raise ValidationError if `value` isn't a usable subdomain slug.

    Rules: 3–30 lowercase chars, alnum + dash, no leading/trailing dash,
    not in RESERVED_SUBDOMAINS, and not starting with `xn--` (IDN/punycode
    prefix — would let a tenant register homograph-phishing subdomains).
    """
    if not isinstance(value, str) or not _SLUG_RE.match(value):
        raise ValidationError(
            "Subdomain must be 3–30 lowercase letters, digits, or dashes "
            "(no leading/trailing dash)."
        )
    if value.lower().startswith("xn--"):
        raise ValidationError(
            "Subdomains starting with 'xn--' are reserved (IDN/punycode)."
        )
    if value.lower() in RESERVED_SUBDOMAINS:
        raise ValidationError(f"'{value}' is reserved and can't be used.")
