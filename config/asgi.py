"""ASGI config for Damka V2 — Daphne + Django Channels."""
import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django_asgi_app = get_asgi_application()

from apps.game.routing import websocket_urlpatterns  # noqa: E402
from apps.shared.middleware.ws_auth import TokenAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": TokenAuthMiddleware(
        URLRouter(websocket_urlpatterns)
    ),
})
