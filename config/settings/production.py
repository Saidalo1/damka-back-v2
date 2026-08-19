"""Production settings.

Enable with DJANGO_SETTINGS_MODULE=config.settings.production and a .env that
sets DJANGO_DEBUG=False, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS,
CORS_ALLOWED_ORIGINS, a strong DJANGO_SECRET_KEY, and DATABASE_URL/REDIS_URL.
TLS is terminated by the host nginx (see compose/nginx/damka.conf), which sets
X-Forwarded-Proto — Django trusts it via SECURE_PROXY_SSL_HEADER below.
"""
from .base import *  # noqa: F401,F403

# ── Security / HTTPS ──────────────────────────────────────────────
# TLS is terminated at the nginx reverse proxy; trust its forwarded scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Browsers post to the API/admin over HTTPS on these origins (scheme required).
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405

# ── Static files (WhiteNoise) ─────────────────────────────────────
# The app serves its own collected static (admin/unfold) with compression +
# hashed filenames, so a plain nginx proxy is enough and /static never 404s even
# before nginx is fully wired. `manage.py collectstatic` runs in compose/django/start.
_wn = "whitenoise.middleware.WhiteNoiseMiddleware"
if _wn not in MIDDLEWARE:  # noqa: F405
    _sec = "django.middleware.security.SecurityMiddleware"
    _at = MIDDLEWARE.index(_sec) + 1 if _sec in MIDDLEWARE else 0  # noqa: F405
    MIDDLEWARE.insert(_at, _wn)  # noqa: F405

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
