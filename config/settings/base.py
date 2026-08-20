"""
Django base settings for Damka.uz V2.

Common settings shared between development and production.
"""
import os
from pathlib import Path

import environ
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
APPS_DIR = BASE_DIR / "apps"

# Environment
env = environ.Env()
env.read_env(str(BASE_DIR / ".env"))

# Security
SECRET_KEY = env("DJANGO_SECRET_KEY", default="change-me-in-production")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# Application definition
DJANGO_APPS = [
    "daphne",
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "channels",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "drf_yasg",
    "mptt",
    "imagekit",
    "django_countries",
]

LOCAL_APPS = [
    "apps.game",
    "apps.users",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://postgres:postgres@localhost:5432/damka_v2"),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# Reuse Postgres connections across queries instead of opening/closing one per
# query (the default, CONN_MAX_AGE=0). Under WebSocket load every move runs a
# SELECT+UPDATE through the sync thread-pool; connection churn (TCP+auth per
# query) otherwise serializes moves and the box sits mostly idle waiting on it.
# CONN_HEALTH_CHECKS revalidates a reused connection so a dead one is replaced
# rather than raising. Keep (workers × threads) under Postgres max_connections.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

# Auth
AUTH_USER_MODEL = "users.User"
# Accept username OR phone for session/admin login (phone stays USERNAME_FIELD).
AUTHENTICATION_BACKENDS = [
    "apps.users.backends.UsernameOrPhoneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

# Static & Media
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Custom auth returns None (not HTTP 401) on an unknown token, so a guest's
        # 43-char anonym_token falls through to AnonymousUser instead of failing at
        # the auth layer. Endpoints that need a real user still enforce it via
        # IsAuthenticated; public (AllowAny) endpoints now work for guests too.
        # Standard TokenAuthentication RAISES 401 on any non-DRF token, which 401'd
        # every guest REST call (they send "Authorization: Token <anonym_token>").
        "shared.django.CustomTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# Channels (WebSocket)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("REDIS_URL", default="redis://localhost:6379/0")],
        },
    },
}

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Redis (direct access for rematch, matchmaking, etc.)
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

# CORS
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[
    "http://localhost:3000",
    "http://127.0.0.1:3000",
])

# Game settings
FIRST_MOVE_TIMEOUT = 30  # seconds to make first move
SEARCH_MATCH_TIMEOUT = 300  # seconds for matchmaking timeout
REMATCH_WAIT_TIMEOUT = 300  # seconds to wait for rematch after game ends
ELO_K_FACTOR = 32
DEFAULT_RATING = 1600

# SMS (Eskiz.uz)
ESKIZ_EMAIL = env("ESKIZ_EMAIL", default="")
ESKIZ_PASSWORD = env("ESKIZ_PASSWORD", default="")
ESKIZ_API_URL = env("ESKIZ_API_URL", default="https://notify.eskiz.uz/api")
# Sender nick registered with Eskiz ("4546" is Eskiz's test sender).
ESKIZ_FROM = env("ESKIZ_FROM", default="4546")
# Must match a template approved by Eskiz for production. {code} is substituted.
ESKIZ_MESSAGE = env("ESKIZ_MESSAGE", default="Damka.uz tasdiqlash kodi: {code}")
# TEMPORARY bypass: when True, verification codes are forced to "0000" and NO real
# SMS/email is sent — lets you test registration on a real (DEBUG=False) deploy
# before Eskiz/SMTP are configured. ⚠️ This is a backdoor (anyone can verify with
# 0000). Keep it False in a live product; turn it OFF the moment Eskiz works.
SMS_TEST_MODE = env.bool("SMS_TEST_MODE", default=False)

# Telegram notifications
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID", default="")

# Email
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")

# ── Unfold Admin Panel ───────────────────────────────────────────
UNFOLD = {
    "SITE_TITLE": "Damka.uz Admin",
    "SITE_HEADER": "Damka.uz",
    "SITE_SUBHEADER": "Checkers Game Platform",
    "SITE_URL": "/",
    "SITE_SYMBOL": "playing_cards",  # Material icon
    # Unfold-styled login form, relabelled "Username or phone" (styling intact).
    "LOGIN": {"form": "apps.users.forms.AdminLoginForm"},
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "THEME": "dark",
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Dashboard"),
                "separator": True,
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                ],
            },
            {
                "title": _("Game"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Games"),
                        "icon": "sports_esports",
                        "link": reverse_lazy("admin:game_game_changelist"),
                    },
                    {
                        "title": _("Game Types"),
                        "icon": "category",
                        "link": reverse_lazy("admin:game_gametypes_changelist"),
                    },
                    {
                        "title": _("Time Controls"),
                        "icon": "timer",
                        "link": reverse_lazy("admin:game_gametypestime_changelist"),
                    },
                    {
                        "title": _("Chat Messages"),
                        "icon": "chat",
                        "link": reverse_lazy("admin:game_chat_changelist"),
                    },
                    {
                        "title": _("Guest Connections"),
                        "icon": "person_outline",
                        "link": reverse_lazy("admin:game_connectionhistory_changelist"),
                    },
                ],
            },
            {
                "title": _("Users"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "people",
                        "link": reverse_lazy("admin:users_user_changelist"),
                    },
                    {
                        "title": _("Countries"),
                        "icon": "public",
                        "link": reverse_lazy("admin:users_countries_changelist"),
                    },
                ],
            },
        ],
    },
}

# Silence USERNAME_FIELD warning — phone_number is intentionally nullable (guest users)
SILENCED_SYSTEM_CHECKS = ["auth.W004", "auth.E003"]
