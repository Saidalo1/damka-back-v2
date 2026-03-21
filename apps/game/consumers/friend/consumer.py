"""
Friend game consumer — handles private game creation and join.

V1 equivalent: game/consumers/game_with_friend.py (~80 lines).
Creates a game with a private_key, second player joins via that key.
"""
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class GameWithFriendConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for creating/joining private games.

    Flow:
    1. Creator connects → creates Game with private_key → sends key to creator
    2. Joiner connects with private_key → joins existing Game → both redirected to GameConsumer
    """

    async def connect(self):
        await self.accept()
        # TODO: Implement private game creation/join

    async def receive_json(self, content, **kwargs):
        pass

    async def disconnect(self, close_code):
        pass
