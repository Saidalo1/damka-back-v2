"""
Redis store for in-progress bot games.

Bot games are casual and single-player, so we don't persist them to the DB like
real (rated) games. But they shouldn't live in a single worker's RAM either —
with multiple ASGI workers a reconnect can land on a different worker. So the
state lives in Redis, keyed by the player's auth token, with a TTL: kept while
the game is being played, and auto-evicted a while after the player leaves.

This is intentionally NOT a full "resumable game" (no UUID, no rejoin flow) —
just the game state moved out of process memory, with expiry.
"""
import json

import redis.asyncio as aioredis
from django.conf import settings

_KEY = "bot_game:{token}"
# Kept alive on every move; a game with no activity for this long is dropped.
BOT_GAME_TTL = getattr(settings, "BOT_GAME_TTL", 900)  # 15 minutes

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Shared async Redis client (one connection pool for all bot games).

    Don't aclose() this — it's process-wide and reused across connections.
    """
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def save_bot_game(redis: aioredis.Redis, token: str, state: dict) -> None:
    """Write the game state and (re)set its TTL — call after every change."""
    await redis.setex(_KEY.format(token=token), BOT_GAME_TTL, json.dumps(state))


async def load_bot_game(redis: aioredis.Redis, token: str) -> dict | None:
    """Load the game state for this token, or None if there's no live game."""
    raw = await redis.get(_KEY.format(token=token))
    return json.loads(raw) if raw else None


async def delete_bot_game(redis: aioredis.Redis, token: str) -> None:
    """Drop the game (e.g. when it ends) instead of waiting for the TTL."""
    await redis.delete(_KEY.format(token=token))
