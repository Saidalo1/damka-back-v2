"""
WebSocket authentication middleware for Django Channels.

Replaces v1's TokenAuthMiddleware with cleaner implementation.
Supports both authorized (Token) and anonymous (urlsafe) players.
Tracks connections in Redis to prevent duplicate connections.
"""
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from rest_framework.authtoken.models import Token

from apps.game.models import ConnectionHistory

logger = logging.getLogger(__name__)

# URL-safe token is 43 characters (token_urlsafe(32))
ANONYM_TOKEN_LENGTH = 43


def is_anonym_token(token: str) -> bool:
    """Check if token is an anonymous (urlsafe) token by length."""
    return len(token) >= ANONYM_TOKEN_LENGTH


class TokenAuthMiddleware(BaseMiddleware):
    """
    Authenticate WebSocket connections via query string token.

    Query format: ?authorization=<token>

    Token types:
    - Authorized: DRF Token (~40 chars) → resolves to User
    - Anonymous: token_urlsafe(32) (~43 chars) → resolves to ConnectionHistory
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)

        authorization = params.get("authorization")
        if not authorization:
            logger.warning("WebSocket connection without authorization token")
            await send({"type": "websocket.close", "code": 4001})
            return

        token = authorization[0]

        if is_anonym_token(token):
            # Anonymous player
            scope["is_guest"] = True
            scope["anonym_token"] = token
            scope["user"] = None
            scope["connection"] = await self._get_or_create_connection(token)
        else:
            # Authorized player
            user = await self._get_user_from_token(token)
            if user is None:
                logger.warning("Invalid auth token for WebSocket")
                await send({"type": "websocket.close", "code": 4001})
                return
            scope["is_guest"] = False
            scope["user"] = user
            scope["anonym_token"] = None
            scope["connection"] = None

        # Extract private_key for friend games
        private_key = params.get("private_key")
        if private_key:
            scope["private_key"] = private_key[0]

        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def _get_user_from_token(self, token_key: str):
        """Look up user from DRF auth token."""
        try:
            token = Token.objects.select_related("user").get(key=token_key)
            return token.user
        except Token.DoesNotExist:
            return None

    @database_sync_to_async
    def _get_or_create_connection(self, anonym_token: str):
        """Get or create ConnectionHistory for anonymous player."""
        connection, _ = ConnectionHistory.objects.get_or_create(
            anonym_token=anonym_token,
            defaults={"status": 1},  # ONLINE
        )
        return connection
