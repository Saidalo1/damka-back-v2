"""
Test settings — fast, self-contained, no external services.

Uses SQLite + the in-memory channel layer so the WebSocket consumers can be
tested end-to-end WITHOUT Docker/Postgres/Redis. Celery runs eagerly (inline).
"""
import tempfile
from pathlib import Path

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["*"]

# --- SQLite (file in temp dir; supports the async consumer thread executor) ---
_DB_FILE = Path(tempfile.gettempdir()) / "damka_v2_test.sqlite3"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(_DB_FILE),
    }
}
DATABASES["default"]["ATOMIC_REQUESTS"] = False

# --- In-memory channel layer (no Redis) ---
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# --- Celery inline (no broker) ---
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"

# --- Misc ---
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # faster tests
