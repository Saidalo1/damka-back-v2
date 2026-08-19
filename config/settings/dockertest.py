"""
Docker-integration settings — run the LOCAL venv against the dockerized
Postgres + Redis (started via `docker compose up -d postgres redis`).

Real channel layer (Redis) + real DB (Postgres), so WebSocket consumers are
validated on production-like infrastructure without building the app image.
Point env at the compose-exposed ports (postgres:5432, redis:6379).
"""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "dockertest-secret-not-for-prod")
os.environ.setdefault("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/damka_v2")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

from .base import *  # noqa: F401,F403,E402

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True

# Celery inline so rating/timer tasks execute without a separate worker.
# Set CELERY_EAGER=0 to enqueue-only (timers stay dormant → useful for move tests
# that must not trigger premature timeouts).
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_EAGER", default=True)  # noqa: F405
CELERY_TASK_EAGER_PROPAGATES = True
