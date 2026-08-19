"""
Game end mixin — handles resign, draw, timeout, and game over logic.

Replaces v1's resign/draw logic inline in GameConsumer.
All game termination goes through a single _end_game() method.
"""
import logging

from apps.game.consumers.db import database_sync_to_async  # thread_sensitive=False (concurrent DB)

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
        # The opponent may have set their offer flag on a DIFFERENT consumer, so
        # our in-memory game is stale — reload before reading the flags.
        await self._refresh_game()
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
                # Offer draw — notify BOTH players (V1 parity). The offerer gets
                # the echo too so their button flips to "waiting"; the opponent
                # (draw != their color) gets the accept/decline banner.
                await self._set_draw_offer(ColorChoices.white)
                await self.channel_layer.group_send(
                    self.game_group,
                    {"type": "game.message", "data": {"event": "draw_offer", "color": self.player_color}, "broadcast": True},
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

    async def handle_draw_decline(self, message=None):
        """Decline the opponent's pending draw offer — clears it for both sides."""
        await self._refresh_game()  # opponent's offer flag was set elsewhere
        if self.game.has_ended:
            return
        opponent_offered = (
            (self.opponent_color == ColorChoices.white and self.game.white_draw_offer)
            or (self.opponent_color == ColorChoices.black and self.game.black_draw_offer)
        )
        if not opponent_offered:
            return
        await self._clear_draw_offers()
        await self.channel_layer.group_send(
            self.game_group,
            {"type": "game.message", "data": {"event": "draw_declined"}, "broadcast": True},
        )

    @database_sync_to_async
    def _clear_draw_offers(self):
        self.game.white_draw_offer = False
        self.game.black_draw_offer = False
        self.game.save(update_fields=["white_draw_offer", "black_draw_offer"])

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
            # Observers get the public game-over (no personalized rating).
            await self.channel_layer.group_send(
                self.game_group,
                {"type": "game.broadcast", "data": game_over_data, "to_observers": True},
            )
        else:
            # No rating change (private game or anon) — send same to both
            await self.channel_layer.group_send(
                self.game_group,
                {"type": "game.broadcast", "data": game_over_data},
            )

        # Start rematch wait timer
        await self.start_rematch_wait_timer()

    async def game_broadcast(self, event):
        """Handle game.broadcast — to all, or observers-only when flagged."""
        if event.get("to_observers") and not getattr(self, "is_observer", False):
            return  # players already received their personalized copy
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
