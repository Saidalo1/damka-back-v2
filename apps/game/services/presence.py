"""
Player presence for live games (who is currently connected).

A Redis SET of the connected player colours per game. Used to decide the
disconnect policy: if ONE player drops the clock keeps running (they lose on
time if they don't return), but if BOTH drop we abort the game after a short
grace instead of letting it hang. Spectators are tracked separately (watchers).
"""
from apps.game.services.bot_store import get_redis  # shared async Redis client

_KEY = "game_online:{game_id}"
_TTL = 60 * 60  # safety expiry

# Grace after a player disconnects before we act (they might just have a network
# blip). At the end of it: back → nothing; both still gone → abort (no rating);
# still gone but opponent present → they forfeit. Same wait for the both-gone
# case on purpose — the internet could have dropped for both.
ABANDON_GRACE = 90


async def mark_online(game_id: str, color: int) -> int:
    redis = get_redis()
    key = _KEY.format(game_id=game_id)
    await redis.sadd(key, str(color))
    await redis.expire(key, _TTL)
    return await redis.scard(key)


async def mark_offline(game_id: str, color: int) -> int:
    redis = get_redis()
    key = _KEY.format(game_id=game_id)
    await redis.srem(key, str(color))
    return await redis.scard(key)


async def online_count(game_id: str) -> int:
    return await get_redis().scard(_KEY.format(game_id=game_id))
