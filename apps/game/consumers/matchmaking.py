"""
Matchmaking consumer — handles player matching for rated games.

V1 equivalent: game/consumers/find_game.py (~60 lines).
V2 uses Redis Lua script for atomic matching (services/matchmaking.py).
"""
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class MatchmakingConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for matchmaking.

    Flow:
    1. Player connects with authorization token + game type info
    2. Server searches for an opponent in Redis (Lua script)
    3. If found → create Game, send game ID to both players
    4. If not found → add to queue, wait for opponent
    5. Disconnect → remove from queue
    """

    async def connect(self):
        await self.accept()
        # TODO: Implement matchmaking logic

    async def receive_json(self, content, **kwargs):
        # TODO: Handle search start/stop
        pass

    async def disconnect(self, close_code):
        # TODO: Remove from queue on disconnect
        pass
