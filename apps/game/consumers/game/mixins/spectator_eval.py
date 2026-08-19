"""
Spectator eval bar for online (human) games.

Showing an engine evaluation to the PLAYERS would be cheating, so the eval is
streamed to OBSERVERS only (via the `to_observers` channel flag). It runs at
most once per position, on the consumer that processed the move, and only when
someone is actually watching — no observers ⇒ zero engine work. Each eval is
tagged with the FEN it was computed for so a stale eval from a previous position
is ignored client-side.
"""
import asyncio
import logging
import time

from apps.game.services.bot_runner import (
    EVAL_HARD_DEPTH_CAP,
    analysis_budget,
    compute_eval_at_depth,
)
from apps.game.services.watchers import watcher_count
from bot_ai.engine import WIN_SCORE, evaluate_position

logger = logging.getLogger(__name__)

_WIN_CUTOFF = WIN_SCORE - 10_000


class SpectatorEvalMixin:
    """Streams a deepening eval to spectators of a live game."""

    def cancel_eval(self):
        task = getattr(self, "_eval_task", None)
        if task and not task.done():
            task.cancel()
        self._eval_task = None

    async def send_observer_initial_eval(self):
        """Quick (quiescence) eval sent to a spectator right when they join."""
        try:
            cp = evaluate_position(self.board)
        except Exception:  # pragma: no cover
            return
        await self.send_json({"event": "eval", "eval": cp, "fen": self.board.fen})

    async def maybe_stream_observer_eval(self, fen: str):
        """After a move, stream a deepening eval to observers — if any are watching."""
        self.cancel_eval()
        try:
            if await watcher_count(self.game_group) <= 0:
                return  # nobody watching → don't spend engine time
        except Exception:  # pragma: no cover
            return
        self._eval_task = asyncio.create_task(self._run_observer_eval(fen))

    async def _run_observer_eval(self, fen: str):
        budget = analysis_budget()
        if budget <= 0.0:
            return
        deadline = time.monotonic() + budget
        prev_dt = 0.0
        try:
            for depth in range(3, EVAL_HARD_DEPTH_CAP + 1):
                now = time.monotonic()
                if now >= deadline or (depth >= 6 and now + prev_dt * 3 > deadline):
                    return
                t0 = time.monotonic()
                cp = await compute_eval_at_depth(fen, depth)
                prev_dt = time.monotonic() - t0
                # Stop if the game has moved on (our board syncs on opponent moves).
                if getattr(self, "board", None) is None or self.board.fen != fen:
                    return
                await self.channel_layer.group_send(
                    self.game_group,
                    {"type": "game.message",
                     "data": {"event": "eval", "eval": cp, "fen": fen},
                     "to_observers": True},
                )
                if abs(cp) >= _WIN_CUTOFF:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - best-effort
            logger.exception("Spectator eval failed for fen %s", fen)
