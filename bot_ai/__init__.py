"""
bot_ai — framework-agnostic AI for Russian draughts.

Pure Python: depends only on `py-draughts` (the rules engine) and the stdlib.
NO Django imports here, on purpose — this package is imported by CPU-worker
processes (ProcessPoolExecutor / Celery) that must not pull in the Django app
registry. Keep it that way.
"""
from bot_ai.engine import (
    EASY,
    MEDIUM,
    HARD,
    LEVEL_CONFIG,
    choose_move,
    evaluate,
)

__all__ = [
    "EASY",
    "MEDIUM",
    "HARD",
    "LEVEL_CONFIG",
    "choose_move",
    "evaluate",
]
