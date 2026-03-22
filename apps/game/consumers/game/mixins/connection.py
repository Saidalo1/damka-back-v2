"""
Connection mixin — handles WebSocket connect/disconnect for game consumers.

Replaces v1's monolithic connect() logic in GameBaseConsumer (633 lines).
Responsible for: auth, channel tracking in Redis, group join, initial state.
"""
import logging

from channels.db import database_sync_to_async
from django.utils import timezone

from apps.game.models import Game
from apps.game.services.board import create_board, get_legal_moves_as_lists, get_turn_color
from shared.django import ColorChoices

logger = logging.getLogger(__name__)


class ConnectionMixin:
    """Handles WebSocket connection lifecycle for game consumers."""

    async def setup_connection(self, game_uuid: str):
        """
        Initialize connection: load game, determine player color, join group.

        Called from GameConsumer.connect().
        """
        self.game = await self._get_game(game_uuid)
        if not self.game:
            await self.close(code=4004)
            return False

        # Determine which color this player is
        self.player_color = await self._determine_player_color()
        if self.player_color is None:
            await self.close(code=4003)
            return False

        # Determine opponent
        self.opponent_color = (
            ColorChoices.black if self.player_color == ColorChoices.white
            else ColorChoices.white
        )

        # Join the game group
        self.game_group = str(self.game.id)
        await self.channel_layer.group_add(self.game_group, self.channel_name)

        # Initialize board from FEN (None → startpos)
        fen = self.game.fen or "startpos"
        self.board = create_board(fen)

        # V1 logic: for matchmaking, mark started immediately
        if not self.game.has_started:
            await self._check_game_start()

        return True


    async def send_initial_state(self):
        """Send full game state to the connecting player (event: init)."""
        is_my_turn = get_turn_color(self.board) == self.player_color
        possible_moves = get_legal_moves_as_lists(self.board) if is_my_turn else []

        users = await self._build_users_list()
        chat_history = await self._get_chat_history()
        mode_info = await self._get_mode_info()

        # Session score from MPTT tree
        session_score = await self._get_session_score()

        await self.send_json({
            "event": "init",
            "fen": self.board.fen,
            "turn": self.game.turn if self.game.turn is not None else get_turn_color(self.board),
            "users": users,
            "times": {
                "white": int(self.game.remaining_time_white or 0),
                "black": int(self.game.remaining_time_black or 0),
            },
            "increment": self.game.increment,
            "mode": mode_info,
            "your_color": self.player_color,
            "chat": chat_history,
            "history": self.game.history,
            "captured": {
                "white": self.game.captured_pieces_count_by_white,
                "black": self.game.captured_pieces_count_by_black,
            },
            "possible_moves": possible_moves,
            "has_started": bool(self.game.last_move),  # V1: True when first move made
            "has_ended": self.game.has_ended,
            "session_score": session_score,
        })

    async def handle_disconnect(self):
        """Clean up on player disconnect."""
        if hasattr(self, "game_group"):
            await self.channel_layer.group_discard(self.game_group, self.channel_name)

    @database_sync_to_async
    def _get_game(self, game_uuid: str):
        """Load game from DB with related objects."""
        try:
            return Game.objects.select_related(
                "white", "black", "white_anonym", "black_anonym",
                "type_of_game", "type_of_game__type",
            ).get(id=game_uuid)
        except (Game.DoesNotExist, ValueError, Exception):
            # ValueError: invalid UUID format
            # Game.DoesNotExist: no game with this ID
            return None

    @database_sync_to_async
    def _determine_player_color(self) -> int | None:
        """Determine which color belongs to the connecting player."""
        user = self.scope.get("user")
        anonym_token = self.scope.get("anonym_token")

        if user and not self.scope.get("is_guest"):
            if self.game.white == user:
                return ColorChoices.white
            elif self.game.black == user:
                return ColorChoices.black
        elif anonym_token:
            if self.game.white_anonym and self.game.white_anonym.anonym_token == anonym_token:
                return ColorChoices.white
            elif self.game.black_anonym and self.game.black_anonym.anonym_token == anonym_token:
                return ColorChoices.black

        return None

    @database_sync_to_async
    def _check_game_start(self):
        """
        V1 logic: for matchmaking games, mark started immediately.

        Sets has_started, turn, and last_move_time.
        Mirrors V1's update_game_started_status for MATCHMAKING type.
        """
        self.game.has_started = True
        self.game.turn = get_turn_color(self.board)  # WHITE moves first
        self.game.last_move_time = timezone.now()
        self.game.save(update_fields=["has_started", "turn", "last_move_time"])



    @database_sync_to_async
    def _build_users_list(self) -> list[dict]:
        """Build user info list for both players."""
        users = []
        for color, user_field, anonym_field in [
            (ColorChoices.white, "white", "white_anonym"),
            (ColorChoices.black, "black", "black_anonym"),
        ]:
            user = getattr(self.game, user_field)
            anonym = getattr(self.game, anonym_field)

            if user:
                users.append({
                    "id": user.id,
                    "username": user.username,
                    "rating": getattr(user, f"{self.game.type_of_game.type.separate_var}_rating", 1600)
                    if self.game.type_of_game else 1600,
                    "avatar": user.avatar.url if user.avatar else None,
                    "is_you": color == self.player_color,
                    "color": color,
                })
            elif anonym:
                users.append({
                    "id": None,
                    "username": "Guest",
                    "rating": anonym.rating,
                    "avatar": None,
                    "is_you": color == self.player_color,
                    "color": color,
                })

        return users

    @database_sync_to_async
    def _get_chat_history(self) -> list[dict]:
        """Load chat history for the game."""
        from apps.game.models import Chat
        messages = Chat.objects.filter(game=self.game).order_by("timestamp")[:50]
        return [
            {
                "message": msg.message,
                "is_authorized": msg.authorized_sender is not None,
                "timestamp": str(msg.timestamp),
            }
            for msg in messages
        ]

    @database_sync_to_async
    def _get_mode_info(self) -> dict:
        """Get game mode information."""
        if not self.game.type_of_game:
            return {}
        gtt = self.game.type_of_game
        return {
            "id": gtt.type.id,
            "title": gtt.type.title,
            "additional_info": {
                "id": gtt.id,
                "title": gtt.title,
                "time": gtt.time,
                "increment": gtt.increment,
            },
        }

    @database_sync_to_async
    def _get_session_score(self) -> dict:
        """Calculate session score from MPTT rematch tree."""
        root = self.game.get_root()
        games_in_tree = root.get_descendants(include_self=True).filter(has_ended=True)

        white_score = 0
        black_score = 0
        draws = 0

        for g in games_in_tree:
            if g.color_win == ColorChoices.white:
                white_score += 1
            elif g.color_win == ColorChoices.black:
                black_score += 1
            elif g.color_win == 0:
                draws += 1

        return {"white": white_score, "black": black_score, "draws": draws}
