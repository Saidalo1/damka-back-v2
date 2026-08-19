"""
Live watcher (spectator) counting for games.

Each game keeps a Redis SET of the channel names currently watching it, so the
count is robust (a missed disconnect doesn't double-count — it's a set, and the
key carries a TTL as a final safety net). Players see this count in the UI.
"""
from apps.game.services.bot_store import get_redis  # shared async Redis client

_KEY = "game_watchers:{game_id}"
_TTL = 60 * 60  # safety expiry so an orphaned set can't linger forever


async def add_watcher(game_id: str, channel_name: str) -> int:
    """Register a spectator channel; returns the new watcher count."""
    redis = get_redis()
    key = _KEY.format(game_id=game_id)
    await redis.sadd(key, channel_name)
    await redis.expire(key, _TTL)
    return await redis.scard(key)


async def remove_watcher(game_id: str, channel_name: str) -> int:
    """Deregister a spectator channel; returns the remaining watcher count."""
    redis = get_redis()
    key = _KEY.format(game_id=game_id)
    await redis.srem(key, channel_name)
    return await redis.scard(key)


async def watcher_count(game_id: str) -> int:
    """Current number of spectators watching a game."""
    return await get_redis().scard(_KEY.format(game_id=game_id))
