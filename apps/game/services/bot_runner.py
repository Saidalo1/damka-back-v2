"""
Bot runner — runs the CPU-bound bot search OFF the async event loop.

The alpha-beta search in `bot_ai.engine.choose_move` is CPU-bound and would
freeze every other game on a Daphne worker if awaited inline. We offload it to a
ProcessPoolExecutor (a real process → its own GIL), so the event loop stays free.

Why ProcessPool and not a thread: a pure-Python CPU search holds the GIL, so a
ThreadPool would still block the loop. Why not Celery (yet): a bot move is
request→response, and ProcessPool keeps that simple. Celery (prefork) is the
documented scale-up path if bot load grows — `choose_move` already takes only
str/int args, so it drops into a Celery task unchanged.

The pool targets `bot_ai.engine.choose_move`, which imports ONLY py-draughts —
no Django — so spawned workers start fast and never touch the app registry.
"""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from functools import partial

from django.conf import settings

from bot_ai.engine import analyze_fen, choose_move

logger = logging.getLogger(__name__)

_executor: ProcessPoolExecutor | None = None


def _cpu_count() -> int:
    return os.cpu_count() or 2


def default_pool_workers() -> int:
    """Adaptive pool size: scale with the server's cores, not a hardcoded number.

    A bot game hits the pool with up to two concurrent CPU tasks (the bot's move
    search + the live eval analysis), so we want ≥2, but we leave a core for the
    event loop and cap it so a big box doesn't spawn a huge pool. Override with
    settings.BOT_POOL_WORKERS.
    """
    return max(2, min(_cpu_count() - 1, 8))


# Safety ceiling so a trivial/quiet position can't iterate forever within the
# time budget (the win-cutoff usually stops it long before this).
EVAL_HARD_DEPTH_CAP = 18


def analysis_budget(active_games: int = 1) -> float:
    """Time budget (seconds) for the live eval analysis — 0.0 means "skip".

    Time-based on purpose: we do NOT statically cut depth by core count. The
    clock self-adapts — an idle/fast box reaches a deep ply within the budget,
    a slow OR busy one reaches a shallower ply for the SAME latency. So on an
    unloaded server the bar runs at full strength; we only shrink the budget as
    real load (concurrent games) climbs, and drop it entirely past a ceiling so
    the bot's own move search always keeps the pool. Game perf > pretty bar.

    Override the base with settings.EVAL_BUDGET_SEC.
    """
    override = getattr(settings, "EVAL_BUDGET_SEC", None)
    base = float(override) if override else 3.5

    workers = default_pool_workers()
    if active_games > workers * 3:
        return 0.0            # heavy load → skip the eval bar, protect gameplay
    if active_games > workers:
        return base * 0.5     # busy → shorter budget (shallower, still useful)
    return base


def _get_executor() -> ProcessPoolExecutor:
    """Lazily create the shared process pool."""
    global _executor
    if _executor is None:
        max_workers = getattr(settings, "BOT_POOL_WORKERS", default_pool_workers())
        _executor = ProcessPoolExecutor(max_workers=max_workers)
        logger.info(
            "Bot ProcessPoolExecutor started (max_workers=%s, cpu=%s, eval_budget=%ss)",
            max_workers, _cpu_count(), analysis_budget(),
        )
    return _executor


async def compute_bot_move(fen: str, level: int, *, seed: int | None = None) -> list[int]:
    """
    Compute the bot's move without blocking the event loop.

    Returns a 1-indexed square list [from, ..., to] (empty if no move).
    Falls back to inline execution only if the process pool is unavailable
    (e.g. platform quirk) — correctness over throughput.
    """
    loop = asyncio.get_running_loop()
    fn = partial(choose_move, fen, level, seed=seed)
    try:
        return await loop.run_in_executor(_get_executor(), fn)
    except Exception:  # pragma: no cover - defensive fallback
        logger.exception("Bot process pool failed; running inline as fallback")
        return await asyncio.to_thread(fn)


async def compute_eval_at_depth(fen: str, depth: int) -> int:
    """White-perspective centipawn eval at a fixed search depth (off the loop).

    Used by the live eval bar: called for depth = 1, 2, 3, … to stream a
    progressively deeper evaluation to the client.
    """
    loop = asyncio.get_running_loop()
    fn = partial(analyze_fen, fen, depth)
    try:
        return await loop.run_in_executor(_get_executor(), fn)
    except Exception:  # pragma: no cover - defensive fallback
        logger.exception("Eval process pool failed; running inline as fallback")
        return await asyncio.to_thread(fn)


def shutdown_pool() -> None:
    """Shut down the process pool (call on app shutdown if wired)."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
