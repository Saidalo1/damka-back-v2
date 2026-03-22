"""Game creation mixin — creates Game record, assigns players, notifies both."""
import logging
from random import choice

from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.game.models import Game, GameTypeChoices, GameTypesTime, ConnectionHistory
from shared.django import ColorChoices

logger = logging.getLogger(__name__)


class GameCreationMixin:
    """Handles creating a Game when two players are matched."""

    async def create_and_notify_game(self, opponent: dict, game_type: GameTypesTime,
                                      my_token: str, my_rating: int):
        """Create a Game record and notify both players."""
        opponent_token = opponent["token"]
        opponent_rating = opponent["rating"]
        opponent_channel = opponent["channel_name"]

        # Random color assignment
        color = choice((ColorChoices.white.value, ColorChoices.black.value))
        time_value = game_type.time

        game = Game(
            type_of_game=game_type,
            type=GameTypeChoices.MATCHMAKING,
            turn=ColorChoices.white.value,  # White moves first in Russian draughts
            increment=game_type.increment,
            initial_time_white=time_value,
            initial_time_black=time_value,
            remaining_time_white=time_value,
            remaining_time_black=time_value,
        )

        # Assign players based on color
        await self._assign_players(game, color, opponent_token, opponent_rating)
        await game.asave()

        game_id = str(game.pk)

        # Build response for both
        my_info = self._build_current_user_info()
        opponent_info = await self._build_opponent_info(opponent_token, opponent_rating)

        # Notify opponent (via channel layer)
        await self.channel_layer.send(opponent_channel, {
            "type": "matchmaking.found",
            "data": {
                "event": "matched",
                "game_id": game_id,
                "users": [
                    {**opponent_info, "is_you": True},
                    {**my_info, "is_you": False},
                ],
            },
        })

        # Notify current player
        await self.send_json({
            "event": "matched",
            "game_id": game_id,
            "users": [
                {**my_info, "is_you": True},
                {**opponent_info, "is_you": False},
            ],
        })
        self.searching = False
        await self.close()

    async def _assign_players(self, game: Game, color: int,
                               opponent_token: str, opponent_rating: int):
        """Assign white/black players on the game based on color draw."""
        current_is_white = color == ColorChoices.white.value

        # Determine if opponent is guest or authorized
        opponent_is_guest = len(opponent_token) >= 43  # ANONYM_TOKEN_LENGTH

        if opponent_is_guest:
            opponent_conn = await ConnectionHistory.objects.aget(
                anonym_token=opponent_token,
            )
            opponent_conn.rating = opponent_rating
            await opponent_conn.asave(update_fields=("rating",))
            game.created_by_anonym = opponent_conn

            if current_is_white:
                game.white_anonym = opponent_conn
            else:
                game.black_anonym = opponent_conn
        else:
            from rest_framework.authtoken.models import Token
            token_obj = await Token.objects.select_related("user").aget(
                key=opponent_token,
            )
            game.created_by_authorized = token_obj.user

            if current_is_white:
                game.white = token_obj.user
            else:
                game.black = token_obj.user

        # Assign current player
        if self.is_guest:
            if current_is_white:
                game.black_anonym = self.connection
            else:
                game.white_anonym = self.connection
        else:
            if current_is_white:
                game.black = self.user
            else:
                game.white = self.user

    async def _build_opponent_info(self, opponent_token: str,
                                     opponent_rating: int) -> dict:
        """Build user info dict for the opponent."""
        opponent_is_guest = len(opponent_token) >= 43

        if opponent_is_guest:
            return {
                "username": "guest",
                "avatar": None,
                "rating": opponent_rating,
                "country": None,
            }

        from rest_framework.authtoken.models import Token
        try:
            token_obj = await Token.objects.select_related("user").aget(
                key=opponent_token,
            )
            opp_user = token_obj.user
            return {
                "username": opp_user.username,
                "avatar": opp_user.avatar.url if opp_user.avatar else None,
                "rating": self.get_user_rating_sync(opp_user, self.game_mode),
                "country": None,
            }
        except Token.DoesNotExist:
            return {
                "username": "unknown",
                "avatar": None,
                "rating": opponent_rating,
                "country": None,
            }
