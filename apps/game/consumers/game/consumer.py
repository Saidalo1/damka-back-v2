"""
Game consumer — the main WebSocket handler for an active game.

V2 architecture: thin consumer that delegates to mixins.
Replaces v1's 783-line monolithic game/consumers/russian.py.
"""
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.game.consumers.game.mixins.chat import ChatMixin
from apps.game.consumers.game.mixins.connection import ConnectionMixin
from apps.game.consumers.game.mixins.game_end import GameEndMixin
from apps.game.consumers.game.mixins.move import MoveMixin
from apps.game.consumers.game.mixins.rematch import RematchMixin
from apps.game.consumers.game.mixins.spectator_eval import SpectatorEvalMixin
from apps.game.consumers.game.mixins.timer import TimerMixin

logger = logging.getLogger(__name__)


class GameConsumer(
    ConnectionMixin,
    MoveMixin,
    TimerMixin,
    ChatMixin,
    RematchMixin,
    GameEndMixin,
    SpectatorEvalMixin,
    AsyncJsonWebsocketConsumer,
):
    """
    WebSocket consumer for an active draughts game.

    Handles: connect → move → resign/draw → chat → rematch → disconnect.
    All logic is in mixins — this consumer is just a router.
    """

    async def connect(self):
        """Connect to a game by UUID."""
        game_uuid = self.scope["url_route"]["kwargs"]["game_uuid"]
        await self.accept()

        success = await self.setup_connection(game_uuid)
        if success:
            await self.send_initial_state()
            if getattr(self, "is_observer", False):
                await self.send_observer_initial_eval()

    # Game actions a spectator can't perform (chat IS allowed, but routed
    # spectator-only — see ChatMixin.handle_chat).
    _OBSERVER_BLOCKED = {"move", "lose", "draw", "rematch"}

    async def receive_json(self, content, **kwargs):
        """Route incoming messages to appropriate handlers."""
        msg_type = content.get("type")
        message = content.get("message")

        # Heartbeat — keeps the socket alive through idle proxies (players may
        # think for minutes without sending anything) and lets the client detect
        # a dead connection. Allowed for everyone, including observers.
        if msg_type == "ping":
            await self.send_json({"event": "pong"})
            return

        # Read-only observers can't act on the game.
        if getattr(self, "is_observer", False) and msg_type in self._OBSERVER_BLOCKED:
            await self.send_json({
                "event": "error",
                "message": "You do not have permission to this action!",
            })
            return

        handlers = {
            "move": self.handle_move,
            "lose": self.handle_resign,
            "draw": self.handle_draw,
            "draw_decline": self.handle_draw_decline,
            "chat": self.handle_chat,
            "rematch": self.handle_rematch,
            "time": self.handle_time_request,
        }

        handler = handlers.get(msg_type)
        if handler:
            await handler(message)
        else:
            await self.send_json({"event": "error", "message": f"Unknown type: {msg_type}"})

    async def disconnect(self, close_code):
        """Clean up on disconnect."""
        self.cancel_eval()
        await self.handle_disconnect()

    async def game_over(self, event):
        """
        Handle game.over from Celery tasks (timeout, first move timeout).

        Celery tasks send game.over via channel_layer.group_send.
        Each connected consumer receives this and forwards to its client.
        """
        data = event.get("data", {})
        await self.send_json(data)
