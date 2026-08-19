"""
Friend game consumer — create/join a private game via a shareable link.

Design parity (figma `12-friend-setup-*`, `13-friend-waiting-*`):
  - creator picks time + color (Oq / Random / Qora), gets a "Copy link" URL
  - "Do'st bilan o'ynash", waiting screen until the friend joins
  - guests are gated behind a "Ro'yxatdan o'ting!" register prompt → auth required

Flow (this consumer is the LOBBY only; actual play is the normal GameConsumer):
  1. Creator connects (no private_key) → sends {"type":"game_type",
     "message":{"color":2,"game_type":<time_id>}} → we create a PRIVATE Game with
     a private_key and reply {"event":"created", game_id, private_key, your_color}.
     Creator waits, joined to group `friend_<private_key>`.
  2. Friend opens the link → connects with ?private_key=<key> → we fill the empty
     seat and notify BOTH {"event":"start", game_id} → both navigate to
     ws/game/<game_id>/ to play.

V1 equivalent: game/consumers/game_with_friend.py (253 lines).
"""
import logging
from random import choice

from apps.game.consumers.db import database_sync_to_async  # thread_sensitive=False (concurrent DB)
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.game.models import Game, GameTypeChoices, GameTypesTime
from shared.django import ColorChoices, generate_private_key

logger = logging.getLogger(__name__)


class GameWithFriendConsumer(AsyncJsonWebsocketConsumer):
    """Lobby consumer for creating/joining private games."""

    async def connect(self):
        # Initialise attributes first so disconnect() is always safe, even when
        # we reject the connection early (guest path below).
        self.game_group = None
        self.private_key = None
        self.created_game_id = None

        # Friend games are for authorized users only (design: guests see a
        # register prompt). Guests are rejected at the lobby.
        if self.scope.get("is_guest") or self.scope.get("user") is None:
            await self.accept()
            await self.send_json({
                "event": "error",
                "message": _("Registration required to play with a friend."),
                "need_register": True,
            })
            await self.close(code=4003)
            return

        self.user = self.scope["user"]
        self.private_key = self.scope.get("private_key")
        self.game_group = None
        await self.accept()

        if self.private_key:
            # Joiner path — try to join the existing private game.
            await self._join_private_game(self.private_key)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if msg_type == "ping":
            # Client heartbeat — reply so the socket isn't flagged as dead.
            await self.send_json({"event": "pong"})
        elif msg_type == "game_type":
            await self._create_private_game(content.get("message") or {})
        else:
            await self.send_json({"event": "error", "message": f"Unknown type: {msg_type}"})

    async def disconnect(self, close_code):
        # If the creator leaves before anyone joined, delete the abandoned game.
        await self._delete_if_abandoned()
        if self.game_group:
            await self.channel_layer.group_discard(self.game_group, self.channel_name)

    # ------------------------------------------------------------ create
    async def _create_private_game(self, message: dict):
        # Block if the user already has an unfinished game.
        existing = await self._get_unfinished_game()
        if existing:
            resp = {
                "event": "error",
                "message": _("You have unfinished games!"),
                "game_id": str(existing.id),
                "game_type": existing.type,
            }
            if existing.type == GameTypeChoices.PRIVATE:
                resp["private_key"] = existing.private_key
            await self.send_json(resp)
            return

        color = message.get("color", ColorChoices.white)
        if color not in (ColorChoices.white, ColorChoices.black):
            color = choice([ColorChoices.white.value, ColorChoices.black.value])

        game_type_id = message.get("game_type")
        game_type = await self._get_game_type(game_type_id)
        if game_type is None:
            await self.send_json({"event": "error", "message": _("Game type not found.")})
            return

        game = await self._save_new_game(game_type, color)
        self.private_key = game.private_key
        self.created_game_id = str(game.id)

        # Join a group so the joiner can notify us when they arrive.
        self.game_group = f"friend_{self.private_key}"
        await self.channel_layer.group_add(self.game_group, self.channel_name)

        await self.send_json({
            "event": "created",
            "game_id": str(game.id),
            "private_key": game.private_key,
            "your_color": color,
            "game_type_id": game_type.id,
            "waiting": True,
        })

    # ------------------------------------------------------------ join
    async def _join_private_game(self, private_key: str):
        game = await self._get_joinable_game(private_key)
        if game is None:
            await self.send_json({
                "event": "error",
                "message": _("Game not found or already full."),
            })
            await self.close(code=4004)
            return

        your_color = await self._fill_empty_seat(game)
        if your_color is None:
            await self.send_json({"event": "error", "message": _("Game is already full.")})
            await self.close(code=4004)
            return

        game_id = str(game.id)

        # Notify the creator (waiting in the group) that the game can start.
        await self.channel_layer.group_send(
            f"friend_{private_key}",
            {"type": "friend.start", "data": {
                "event": "start",
                "game_id": game_id,
                "private_key": private_key,
            }},
        )
        # Notify the joiner directly.
        await self.send_json({
            "event": "start",
            "game_id": game_id,
            "private_key": private_key,
            "your_color": your_color,
        })
        # Both sides now open ws/game/<game_id>/ — close the lobby socket.
        await self.close()

    async def friend_start(self, event):
        """Channel-layer handler: creator receives the start signal."""
        await self.send_json(event["data"])
        await self.close()

    # ------------------------------------------------------------ db helpers
    @database_sync_to_async
    def _get_unfinished_game(self):
        return Game.objects.filter(
            Q(has_ended=False) & (Q(white_id=self.user.id) | Q(black_id=self.user.id)),
        ).first()

    @database_sync_to_async
    def _get_game_type(self, game_type_id):
        try:
            return GameTypesTime.objects.select_related("type").get(pk=game_type_id)
        except (GameTypesTime.DoesNotExist, ValueError, TypeError):
            return None

    @database_sync_to_async
    def _save_new_game(self, game_type: GameTypesTime, color: int) -> Game:
        time_value = game_type.time
        game = Game(
            type_of_game=game_type,
            type=GameTypeChoices.PRIVATE,
            private_key=generate_private_key(),
            turn=ColorChoices.white.value,  # White moves first
            increment=game_type.increment,
            initial_time_white=time_value,
            initial_time_black=time_value,
            remaining_time_white=time_value,
            remaining_time_black=time_value,
            created_by_authorized=self.user,
        )
        if color == ColorChoices.white:
            game.white = self.user
        else:
            game.black = self.user
        game.save()
        return game

    @database_sync_to_async
    def _get_joinable_game(self, private_key: str):
        try:
            game = Game.objects.select_related("white", "black").get(
                private_key=private_key,
                type=GameTypeChoices.PRIVATE,
                has_ended=False,
            )
        except Game.DoesNotExist:
            return None
        # Must have an empty seat, and the joiner can't join their own game twice.
        if game.white_id == self.user.id or game.black_id == self.user.id:
            return None
        if game.white_id is not None and game.black_id is not None:
            return None
        return game

    @database_sync_to_async
    def _fill_empty_seat(self, game: Game):
        if game.white_id is None:
            game.white = self.user
            game.save(update_fields=["white"])
            return ColorChoices.white.value
        if game.black_id is None:
            game.black = self.user
            game.save(update_fields=["black"])
            return ColorChoices.black.value
        return None

    @database_sync_to_async
    def _delete_if_abandoned(self):
        """Delete a created private game if nobody joined (only one seat filled)."""
        pk = getattr(self, "created_game_id", None)
        if not pk:
            return
        Game.objects.filter(
            id=pk,
            type=GameTypeChoices.PRIVATE,
            has_ended=False,
        ).filter(
            Q(white__isnull=True) | Q(black__isnull=True),
        ).delete()
