"""
Rematch mixin — handles rematch offers/accepts using Redis + MPTT.

Flow:
1. Player sends {type: "rematch"} → Redis flag set (e.g. "{game_id}_rematch_white")
2. If both players have sent rematch → create child game (MPTT) and notify both
3. Both players redirect to the new game page
"""
import logging

from apps.game.consumers.db import database_sync_to_async  # thread_sensitive=False (concurrent DB)
from django.conf import settings

from shared.django import ColorChoices

logger = logging.getLogger(__name__)

# Seconds players stay on the result screen (able to rematch) before the game's
# sockets are force-closed to free the connections.
REMATCH_WAIT = 60


class RematchMixin:
    """Handles rematch offers and game creation."""

    async def handle_rematch(self, message):
        """
        Process a rematch request from a player.

        Uses Redis to track which players have requested a rematch.
        If both players request, creates a new child game.
        """
        if not hasattr(self, "game") or not self.game:
            await self.send_json({"event": "error", "message": "Game is not over yet"})
            return

        # The game was finalized on the OTHER player's consumer, so our in-memory
        # copy still has has_ended=False. Reload before the check, otherwise the
        # opponent's rematch click is wrongly rejected and both-agree never fires.
        await self._refresh_game()
        if not self.game.has_ended:
            await self.send_json({"event": "error", "message": "Game is not over yet"})
            return

        # Set rematch flag in Redis
        redis = self._get_redis()
        game_id = str(self.game.id)
        color_key = "white" if self.player_color == ColorChoices.white else "black"

        redis.set(f"{game_id}_rematch_{color_key}", "1", ex=300)  # 5 min expiry

        # Notify opponent about rematch offer
        await self.channel_layer.group_send(
            game_id,
            {
                "type": "game.message",
                "data": {
                    "event": "rematch_offer",
                    "color": self.player_color,
                },
                "broadcast": True,
            },
        )

        # Check if both players want a rematch
        white_wants = redis.get(f"{game_id}_rematch_white")
        black_wants = redis.get(f"{game_id}_rematch_black")

        if white_wants and black_wants:
            # Both agree — create new game
            new_game_info = await self._create_rematch_game()

            # Clean up Redis
            redis.delete(f"{game_id}_rematch_white")
            redis.delete(f"{game_id}_rematch_black")

            # Notify both players about the new game
            await self.channel_layer.group_send(
                game_id,
                {
                    "type": "game.message",
                    "data": {
                        "event": "rematch_accepted",
                        "new_game_id": str(new_game_info["id"]),
                        "private_key": new_game_info.get("private_key"),
                    },
                    "broadcast": True,
                },
            )

    @database_sync_to_async
    def _create_rematch_game(self) -> dict:
        """
        Create a new game as a child of the current game (MPTT tree).

        Swaps white/black for fairness (player who was white becomes black).
        """
        from apps.game.models import Game

        game = self.game
        new_game = Game(
            # Swap colors for fairness
            white=game.black,
            black=game.white,
            white_anonym=game.black_anonym,
            black_anonym=game.white_anonym,
            # Keep same settings
            created_by_authorized=game.created_by_authorized,
            created_by_anonym=game.created_by_anonym,
            type_of_game=game.type_of_game,
            type=game.type,
            initial_time_white=game.initial_time_white,
            initial_time_black=game.initial_time_black,
            remaining_time_white=game.initial_time_white,
            remaining_time_black=game.initial_time_black,
            increment=game.increment,
            private_key=game.private_key,
            # MPTT: child of current game
            parent_id=game.id,
        )
        new_game.save()

        logger.info(
            "Rematch game created: %s (parent: %s)",
            new_game.id, game.id,
        )

        return {
            "id": new_game.id,
            "type_of_game_id": new_game.type_of_game_id,
            "private_key": new_game.private_key,
        }

    async def start_rematch_wait_timer(self):
        """
        Schedule the post-game cleanup.

        After a game ends, players get REMATCH_WAIT seconds on the result screen
        to click a rematch. If no rematch game is created in that window, a Celery
        task closes both sockets so finished games don't hold connections open.
        """
        await self._schedule_rematch_cleanup()

    @database_sync_to_async
    def _schedule_rematch_cleanup(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.game.tasks import close_finished_game
        close_finished_game.apply_async(
            args=[str(self.game.id)],
            eta=timezone.now() + timedelta(seconds=REMATCH_WAIT),
        )

    def _get_redis(self):
        """Get Redis connection for rematch tracking."""
        import redis
        return redis.StrictRedis.from_url(settings.REDIS_URL)
