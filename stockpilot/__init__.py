"""Celery application instance for stockpilot.

Tasks live in `apps/<app>/tasks.py`. Celery autodiscovers them once Django
INSTALLED_APPS is loaded.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
