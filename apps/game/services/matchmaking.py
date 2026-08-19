"""Matchmaking service — Redis sorted-set matching (no blocking KEYS scan).

Waiting players live in a per-game-type ZSET scored by rating, so finding an
opponent is a `ZRANGEBYSCORE` over the ±range window — O(log N + M) — instead of
`KEYS matchmaking:*` which is a blocking O(total-keys) scan of the whole DB.
Each player's payload (channel name) is a separate key with a TTL for cleanup;
a claim (find + remove) is atomic in one Lua call.
"""
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

RANGE = 200  # rating window for a match (±)

# Keys: ZSET of waiting tokens (score=rating), and per-player data with a TTL.
def _zkey(game_type_id) -> str:
    return f"mm:z:{game_type_id}"


def _dkey(game_type_id, token) -> str:
    return f"mm:d:{game_type_id}:{token}"


# Atomically find + claim an opponent within the rating window.
# ARGV: zkey, dkey_prefix, my_token, my_rating, range
_FIND_LUA = """
local zkey = ARGV[1]
local dprefix = ARGV[2]
local my_token = ARGV[3]
local my_rating = tonumber(ARGV[4])
local range = tonumber(ARGV[5])
local cand = redis.call('ZRANGEBYSCORE', zkey, my_rating - range, my_rating + range)
for _, tok in ipairs(cand) do
    if tok ~= my_token then
        local data = redis.call('GET', dprefix .. tok)
        if data then
            redis.call('ZREM', zkey, tok)
            redis.call('DEL', dprefix .. tok)
            return data
        else
            redis.call('ZREM', zkey, tok)  -- payload expired → drop stale member
        end
    end
end
return nil
"""


async def find_opponent(redis_conn, game_type_id: int, my_token: str, my_rating: int) -> dict | None:
    """Find + atomically claim a waiting opponent within ±RANGE rating."""
    result = await redis_conn.eval(
        _FIND_LUA, 0,
        _zkey(game_type_id), f"mm:d:{game_type_id}:", my_token, str(my_rating), str(RANGE),
    )
    return json.loads(result) if result else None


async def add_to_queue(redis_conn, game_type_id: int, token: str, rating: int,
                       channel_name: str, timeout: int = 303) -> None:
    """Enqueue a waiting player (ZSET member + TTL'd payload)."""
    await redis_conn.zadd(_zkey(game_type_id), {token: rating})
    await redis_conn.setex(
        _dkey(game_type_id, token), timeout,
        json.dumps({"rating": rating, "token": token, "channel_name": channel_name}),
    )


async def remove_from_queue(redis_conn, game_type_id: int, token: str) -> None:
    """Remove a player from the queue."""
    await redis_conn.zrem(_zkey(game_type_id), token)
    await redis_conn.delete(_dkey(game_type_id, token))
