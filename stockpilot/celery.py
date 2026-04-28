"""Celery application setup."""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stockpilot.settings.dev")

app = Celery("stockpilot")
# Use Django settings, all CELERY_-prefixed config under the "CELERY" namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")
# Discover tasks in INSTALLED_APPS.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Celery worker self-test OK: {self.request!r}")
