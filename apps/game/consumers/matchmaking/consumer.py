"""
Matchmaking consumer — thin router that delegates to mixins.

V2 architecture: same pattern as GameConsumer.
Replaces V1's monolithic find_game.py (304 lines).
"""
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils.translation import gettext as _

from apps.game.consumers.matchmaking.mixins.connection import MatchmakingConnectionMixin
from apps.game.consumers.matchmaking.mixins.game_creation import GameCreationMixin
from apps.game.consumers.matchmaking.mixins.search import SearchMixin

logger = logging.getLogger(__name__)


class MatchmakingConsumer(
    MatchmakingConnectionMixin,
    SearchMixin,
    GameCreationMixin,
    AsyncJsonWebsocketConsumer,
):
    """
    WebSocket consumer for matchmaking.

    Handles: connect → search → cancel → disconnect.
    All logic is in mixins — this consumer is just a router.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_state()

    async def connect(self):
        """Accept connection and initialize auth + Redis."""
        await self.accept()
        await self.setup_connection()

    async def receive_json(self, content, **kwargs):
        """Route incoming messages to appropriate handlers."""
        msg_type = content.get("type")

        if msg_type == "ping":
            await self.send_json({"event": "pong"})
            return

        handlers = {
            "search": lambda: self.handle_search(content.get("message", {})),
            "cancel": self.handle_cancel,
        }

        handler = handlers.get(msg_type)
        if handler:
            await handler()
        else:
            await self.send_json({
                "event": "error",
                "message": _("Unknown message type: %(type)s") % {"type": msg_type},
            })

    async def disconnect(self, close_code):
        """Clean up on disconnect."""
        await self.handle_disconnect()

    # ===================================================================
    # Channel layer handlers
    # ===================================================================

    async def matchmaking_found(self, event):
        """Opponent found — notification from the matching player."""
        data = event.get("data", {})
        await self.send_json(data)
        self.searching = False
        await self.close()

    async def matchmaking_timeout(self, event):
        """Search timeout — notification from Celery task."""
        await self.send_json({
            "event": "timeout",
            "message": _("No opponent found. Try again."),
        })
        self.searching = False
        await self.close()
