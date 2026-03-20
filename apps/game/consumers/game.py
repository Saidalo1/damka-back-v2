"""
Game consumer — the main WebSocket handler for an active game.

V2 architecture: thin consumer that delegates to mixins.
Replaces v1's 783-line monolithic game/consumers/russian.py.
"""
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.game.consumers.mixins.connection import ConnectionMixin
from apps.game.consumers.mixins.game_end import GameEndMixin
from apps.game.consumers.mixins.move import MoveMixin

logger = logging.getLogger(__name__)


class GameConsumer(ConnectionMixin, MoveMixin, GameEndMixin, AsyncJsonWebsocketConsumer):
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

    async def receive_json(self, content, **kwargs):
        """Route incoming messages to appropriate handlers."""
        msg_type = content.get("type")
        message = content.get("message")

        handlers = {
            "move": self.handle_move,
            "lose": self.handle_resign,
            "draw": self.handle_draw,
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
        await self.handle_disconnect()

    # Stub handlers for mixins not yet implemented
    async def handle_chat(self, message):
        """TODO: Implement in ChatMixin."""
        pass

    async def handle_rematch(self, message):
        """TODO: Implement in RematchMixin."""
        pass

    async def handle_time_request(self, message):
        """TODO: Implement in TimerMixin."""
        pass

    async def cancel_current_timer(self):
        """TODO: Implement in TimerMixin."""
        pass

    async def start_move_timer(self):
        """TODO: Implement in TimerMixin."""
        pass

    async def start_rematch_wait_timer(self):
        """TODO: Implement in RematchMixin."""
        pass
