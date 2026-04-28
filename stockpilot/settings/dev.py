"""Development settings — DEBUG, permissive hosts, console mail."""

from .base import *  # noqa: F401, F403

DEBUG = True
# Wildcard so any *.localhost subdomain hits the right tenant in dev.
ALLOWED_HOSTS = ["*"]

# Faster password hasher for dev/tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Mail goes to stdout so we can see the rendered POs in dev
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
