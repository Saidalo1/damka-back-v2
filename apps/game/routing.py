"""WebSocket URL routing for game consumers."""
from django.urls import re_path

from apps.game.consumers.game import GameConsumer
from apps.game.consumers.matchmaking import MatchmakingConsumer
from apps.game.consumers.friend import GameWithFriendConsumer
from apps.game.consumers.bot import GameWithBotConsumer

websocket_urlpatterns = [
    # Bot route MUST precede the uuid route so "bot" is never parsed as a game id.
    re_path(r"ws/game/bot/$", GameWithBotConsumer.as_asgi()),
    re_path(r"ws/game/(?P<game_uuid>[0-9a-f-]+)/$", GameConsumer.as_asgi()),
    re_path(r"ws/matchmaking/$", MatchmakingConsumer.as_asgi()),
    re_path(r"ws/friend/$", GameWithFriendConsumer.as_asgi()),
]
