"""Public-schema views: landing + signup.

Lives only on the apex/public domain. Tenant subdomains hit a different
URLconf (`stockpilot.urls`).
"""

from __future__ import annotations

import logging
import time

from django.contrib.auth import login
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from . import services
from .forms import SignupForm

logger = logging.getLogger(__name__)


# Lightweight per-IP rate limit. Default cache backend is locmem which
# means it's per-process — for v1 dev this is fine; production should
# back django.core.cache by Redis (already running for Celery).
SIGNUP_RATE_LIMIT_PER_HOUR = 3


def _client_ip(request: HttpRequest) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def _rate_limited(request: HttpRequest) -> bool:
    ip = _client_ip(request)
    key = f"signup_attempts:{ip}"
    now = time.time()
    window_start = now - 3600
    attempts = [t for t in (cache.get(key) or []) if t > window_start]
    if len(attempts) >= SIGNUP_RATE_LIMIT_PER_HOUR:
        return True
    attempts.append(now)
    cache.set(key, attempts, timeout=3600)
    return False


@require_safe
def landing(request: HttpRequest) -> HttpResponse:
    return render(request, "tenants/landing.html")


@require_http_methods(["GET", "POST"])
def signup(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        if _rate_limited(request):
            return render(
                request,
                "tenants/signup.html",
                {"form": SignupForm(), "rate_limited": True},
                status=429,
            )

        form = SignupForm(request.POST)
        if form.is_valid():
            user, org = services.provision_organization(
                company_name=form.cleaned_data["company_name"],
                slug=form.cleaned_data["slug"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
            login(request, user)
            target = f"//{org.domains.first().domain}:{request.get_port()}/admin/"
            logger.info("signup ok slug=%s redirect=%s", org.slug, target)
            return redirect(target)
    else:
        form = SignupForm()

    return render(request, "tenants/signup.html", {"form": form})
