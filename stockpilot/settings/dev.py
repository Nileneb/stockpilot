"""Development settings — SQLite, DEBUG on, permissive hosts."""

from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Faster password hasher for dev/tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
