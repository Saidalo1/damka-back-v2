"""Import Celery app for Django to pick it up."""
from .celery import app as celery_app

__all__ = ["celery_app"]
