"""Base settings shared by all environments."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-insecure-overridden-in-prod-1234567890abcdef",
)

DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    # Unfold MUST come before django.contrib.admin
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "apps.tenants",
    "apps.catalog",
    "apps.inventory",
    "apps.vision",
    "apps.forecast",
    "apps.orders",
]

# Email — defaults overridden in dev/prod
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "stockpilot@example.local")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.tenants.middleware.ActiveOrganizationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "stockpilot.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "stockpilot.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Vision / inference
VISION_INFERENCE_BACKEND = os.environ.get(
    "VISION_INFERENCE_BACKEND",
    "apps.vision.inference.UltralyticsBackend",
)
VISION_YOLO_MODEL = os.environ.get("VISION_YOLO_MODEL", "yolo11n.pt")
VISION_YOLO_CONFIDENCE = float(os.environ.get("VISION_YOLO_CONFIDENCE", "0.25"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/admin/"

UNFOLD = {
    "SITE_TITLE": "Stockpilot",
    "SITE_HEADER": "Stockpilot",
    "SITE_SUBHEADER": "Inventory & Logistics",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "COLORS": {
        "primary": {
            "500": "59 130 246",
            "600": "37 99 235",
            "700": "29 78 216",
        },
    },
}
