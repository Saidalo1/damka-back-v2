"""
Game end mixin — handles resign, draw, timeout, and game over logic.

Replaces v1's resign/draw logic inline in GameConsumer.
All game termination goes through a single _end_game() method.
"""
import logging

from channels.db import database_sync_to_async

from shared.django import ColorChoices
from apps.game.services.elo import update_ratings_after_game

logger = logging.getLogger(__name__)


class GameEndMixin:
    """Handles all game termination scenarios."""

    async def handle_resign(self, message=None):
        """Player resigns — opponent wins."""
        if self.game.has_ended:
            return

        winner_color = self.opponent_color
        await self._end_game(winner_color, reason="resign")

    async def handle_draw(self, message=None):
        """
        Handle draw offer/acceptance.

        First call from a player → sets draw offer flag.
        Second call from opponent → accepts draw.
        """
        if self.game.has_ended:
            return

        # Check if this player already offered draw
        if self.player_color == ColorChoices.white:
            if self.game.white_draw_offer:
                return  # Already offered
            if self.game.black_draw_offer:
                # Opponent already offered → accept draw
                await self._end_game(winner_color=0, reason="draw")
                return
            else:
                # Offer draw
                await self._set_draw_offer(ColorChoices.white)
                await self.channel_layer.group_send(
                    self.game_group,
                    {"type": "game.message", "data": {"event": "draw_offer", "color": self.player_color}, "target_color": self.opponent_color},
                )
        else:
            if self.game.black_draw_offer:
                return
            if self.game.white_draw_offer:
                await self._end_game(winner_color=0, reason="draw")
                return
            else:
                await self._set_draw_offer(ColorChoices.black)
                await self.channel_layer.group_send(
                    self.game_group,
                    {"type": "game.message", "data": {"event": "draw_offer", "color": self.player_color}, "target_color": self.opponent_color},
                )

    async def _handle_game_over_by_board(self, winner_color: int | None):
        """Called when board.game_over is True (no legal moves or draw rule)."""
        if winner_color is None:
            winner_color = 0  # Draw
        await self._end_game(winner_color, reason="checkmate")

    async def handle_timeout(self, timed_out_color: int):
        """Called by timer when a player runs out of time."""
        if self.game.has_ended:
            return
        winner_color = (
            ColorChoices.black if timed_out_color == ColorChoices.white
            else ColorChoices.white
        )
        await self._end_game(winner_color, reason="timeout")

    async def _end_game(self, winner_color: int, reason: str):
        """
        Central game termination method.

        All game-ending paths funnel through here.

        Args:
            winner_color: 1=black, 2=white, 0=draw.
            reason: checkmate, resign, timeout, draw, cancelled.
        """
        # Cancel any active timer
        await self.cancel_current_timer()

        # Update game in DB
        rating_changes = await self._finalize_game(winner_color)

        # Build game_over event
        game_over_data = {
            "event": "game_over",
            "winner": winner_color,
            "reason": reason,
            "session_score": await self._get_session_score(),
        }

        # Add rating info per player
        if rating_changes:
            # Send personalized rating data to each player
            for color in [ColorChoices.white, ColorChoices.black]:
                color_key = "white" if color == ColorChoices.white else "black"
                player_data = {
                    **game_over_data,
                    "rating": rating_changes.get(color_key, {}),
                }
                await self._send_to_player(color, player_data)
        else:
            # No rating change (private game or anon) — send same to both
            await self.channel_layer.group_send(
                self.game_group,
                {"type": "game.broadcast", "data": game_over_data},
            )

        # Start rematch wait timer
        await self.start_rematch_wait_timer()

    async def game_broadcast(self, event):
        """Handle game.broadcast — send to all players in group."""
        await self.send_json(event["data"])

    @database_sync_to_async
    def _finalize_game(self, winner_color: int) -> dict:
        """Mark game as ended, calculate ratings, record finish time."""
        from django.utils import timezone

        self.game.has_ended = True
        self.game.color_win = winner_color
        self.game.finished_time = timezone.now()

        self.game.save(update_fields=[
            "has_ended", "color_win", "finished_time",
        ])

        # Calculate ELO rating changes (service handles all validation)
        return update_ratings_after_game(self.game)

    @database_sync_to_async
    def _set_draw_offer(self, color: int):
        """Set draw offer flag for a color."""
        if color == ColorChoices.white:
            self.game.white_draw_offer = True
            self.game.save(update_fields=["white_draw_offer"])
        else:
            self.game.black_draw_offer = True
            self.game.save(update_fields=["black_draw_offer"])
