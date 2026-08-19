"""
Timer mixin — manages Celery-based timer tasks for game time enforcement.

Handles:
- Starting/cancelling move timers (Celery tasks with eta=remaining_time)
- Starting first-move timer on game start
- Time sync requests from clients
"""
import json
import logging
from datetime import timedelta

from apps.game.consumers.db import database_sync_to_async  # thread_sensitive=False (concurrent DB)
from django.db.transaction import on_commit
from django.utils import timezone

logger = logging.getLogger(__name__)


class TimerMixin:
    """Manages game timers via Celery delayed tasks."""

    async def start_first_move_timer(self):
        """Schedule a Celery task to check first move after timeout."""
        await self._schedule_first_move_check()

    async def start_move_timer(self):
        """
        Schedule a Celery task to check if the current player's time runs out.

        Called after each move to set a timer for the NEXT player.
        """
        await self._schedule_move_timeout_check()

    async def cancel_current_timer(self):
        """Cancel the current move timer task (if any)."""
        await self._revoke_move_timer()

    async def handle_time_request(self, message):
        """
        Client requests current time — recalculate and send.

        Useful for time sync when client reconnects or drifts.
        """
        if not hasattr(self, "game") or not self.game:
            return

        await self._refresh_game()

        times = {
            "white": int(self.game.remaining_time_white or 0),
            "black": int(self.game.remaining_time_black or 0),
        }

        # If game is active and someone is on the clock, calculate live time
        if self.game.last_move_time and not self.game.has_ended:
            elapsed = (timezone.now() - self.game.last_move_time).total_seconds()
            from shared.django import ColorChoices
            if self.game.turn == ColorChoices.white and self.game.first_color_first_move_done:
                times["white"] = max(0, int(self.game.remaining_time_white - elapsed))
            elif self.game.turn == ColorChoices.black and self.game.second_color_first_move_done:
                times["black"] = max(0, int(self.game.remaining_time_black - elapsed))

        await self.send_json({
            "event": "time_sync",
            "times": times,
            "turn": self.game.turn,
        })

    @database_sync_to_async
    def _schedule_first_move_check(self):
        """Schedule check_first_move Celery task using on_commit."""
        from apps.game.tasks import check_first_move, FIRST_MOVE_TIMEOUT
        from shared.django import ColorChoices

        game = self.game
        color = self.player_color
        queue = ColorChoices.white if color == ColorChoices.white else ColorChoices.black

        def handler():
            task = check_first_move.apply_async(
                args=[str(game.id), color, queue],
                eta=timezone.now() + timedelta(seconds=FIRST_MOVE_TIMEOUT),
            )
            game.first_move_check_task_id = task.id
            game.first_move_check_task_time = timezone.now()
            game.save(update_fields=("first_move_check_task_id", "first_move_check_task_time"))

        on_commit(handler)

    @database_sync_to_async
    def _schedule_move_timeout_check(self):
        """Schedule check_move_timeout for the player whose turn it is."""
        from apps.game.tasks import check_move_timeout
        from shared.django import ColorChoices

        game = self.game

        # Get the remaining time for the current player
        if game.turn == ColorChoices.white:
            remaining = game.remaining_time_white or 0
        else:
            remaining = game.remaining_time_black or 0

        if remaining <= 0:
            return  # Already out of time

        # Get current move info for stale-check
        history = json.loads(game.history) if game.history else {}
        if history:
            last_entry = list(history.values())[-1]
            last_pdn = list(last_entry.keys())[-1]
            last_fen = list(last_entry.values())[-1]
        else:
            last_pdn = ""
            last_fen = ""

        def handler():
            task = check_move_timeout.apply_async(
                args=[str(game.id), last_pdn, last_fen, len(history), game.turn],
                eta=timezone.now() + timedelta(seconds=remaining),
            )
            game.move_check_task_id = task.id
            game.save(update_fields=("move_check_task_id",))

        on_commit(handler)

    @database_sync_to_async
    def _revoke_move_timer(self):
        """Revoke the current move timeout Celery task."""
        from config.celery import app as celery_app

        game = self.game
        if game.move_check_task_id:
            celery_app.control.revoke(str(game.move_check_task_id), terminate=True)
            game.move_check_task_id = None
            game.save(update_fields=("move_check_task_id",))
