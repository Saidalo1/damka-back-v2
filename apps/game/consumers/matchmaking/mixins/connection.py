"""Matchmaking connection mixin — connect, disconnect, Redis init, auth helpers."""
import logging

import redis.asyncio as aioredis
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils.translation import gettext as _

from apps.game.models import ConnectionHistory
from apps.game.models.handbook import ConnectionStatusChoices

logger = logging.getLogger(__name__)


class MatchmakingConnectionMixin:
    """Handles WebSocket lifecycle: connect, disconnect, auth, Redis."""

    def init_state(self):
        """Initialize all instance attributes for matchmaking."""
        self.redis = None
        self.user = None
        self.connection = None  # ConnectionHistory for guests
        self.is_guest = False
        self.token = None
        self.game_type = None
        self.game_mode = None
        self.searching = False
        self.celery_task_id = None

    async def setup_connection(self):
        """Extract auth info from scope and initialize Redis."""
        self.is_guest = self.scope.get("is_guest", False)
        self.user = self.scope.get("user")
        self.connection = self.scope.get("connection")
        self.token = self.scope.get("anonym_token") if self.is_guest else None

        if not self.is_guest and self.user is None:
            await self.send_json({
                "event": "error",
                "message": _("Authentication required."),
            })
            await self.close()
            return False

        # Initialize async Redis
        self.redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        return True

    async def handle_disconnect(self):
        """Clean up on disconnect: remove from queue, update connection status."""
        if self.searching:
            await self.cleanup_search()

        # Update connection status for guests
        if self.connection:
            self.connection.status = ConnectionStatusChoices.OFFLINE
            self.connection.was_failed = False
            await self.connection.asave(update_fields=("status", "was_failed"))

        # Close Redis connection
        if self.redis:
            await self.redis.aclose()

    async def cleanup_search(self):
        """Remove player from matchmaking queue and revoke Celery task."""
        from apps.game.services.matchmaking import remove_from_queue

        if self.redis and self.game_type:
            my_token = self.token if self.is_guest else await self.get_auth_token()
            await remove_from_queue(
                self.redis,
                game_type_id=self.game_type.pk,
                token=my_token,
            )

        # Revoke Celery timeout task
        if self.celery_task_id:
            from config.celery import app
            app.control.revoke(self.celery_task_id, terminate=True)
            self.celery_task_id = None

        self.searching = False

    # ===================================================================
    # Auth and rating helpers
    # ===================================================================

    @sync_to_async
    def get_auth_token(self) -> str:
        """Get the DRF auth token key for the current user."""
        from rest_framework.authtoken.models import Token
        return Token.objects.get(user=self.user).key

    @sync_to_async
    def get_game_mode(self, game_type) -> str:
        """Get the game mode string (bullet/blitz/rapid) from game type FK."""
        return game_type.type.separate_var

    @staticmethod
    @sync_to_async
    def get_user_rating(user, mode: str) -> int:
        """Get rating for the game mode. Mode is 'bullet'/'blitz'/'rapid'."""
        return getattr(user, f"{mode}_rating", 1600)

    @staticmethod
    def get_user_rating_sync(user, mode: str) -> int:
        """Sync version of get_user_rating."""
        return getattr(user, f"{mode}_rating", 1600)
