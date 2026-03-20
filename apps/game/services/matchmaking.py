"""Matchmaking service — Redis-based player matching with Lua script."""
import json
import logging

from channels.layers import get_channel_layer
from django.conf import settings

logger = logging.getLogger(__name__)

# Lua script for atomic matchmaking search in Redis
# Searches for a player with rating within ±200 of the current player
MATCHMAKING_LUA = """
local keys = redis.call('KEYS', ARGV[1])
local my_token = ARGV[2]
local my_rating = tonumber(ARGV[3])
local range = 200

for _, key in ipairs(keys) do
    local data = redis.call('GET', key)
    if data then
        local info = cjson.decode(data)
        local their_rating = tonumber(info.rating)
        local their_token = info.token
        if their_token ~= my_token and 
           their_rating >= (my_rating - range) and 
           their_rating <= (my_rating + range) then
            redis.call('DEL', key)
            return data
        end
    end
end

return nil
"""


async def find_opponent(redis_conn, game_type_id: int, my_token: str, my_rating: int) -> dict | None:
    """
    Search for an opponent in Redis using Lua script.

    Args:
        redis_conn: Async Redis connection.
        game_type_id: ID of the GameTypesTime.
        my_token: Current player's token.
        my_rating: Current player's rating.

    Returns:
        Opponent info dict or None if no match found.
    """
    pattern = f"matchmaking:{game_type_id}:*"

    result = await redis_conn.eval(
        MATCHMAKING_LUA,
        0,  # no KEYS args
        pattern,
        my_token,
        str(my_rating),
    )

    if result:
        return json.loads(result)
    return None


async def add_to_queue(redis_conn, game_type_id: int, token: str, rating: int, channel_name: str) -> None:
    """Add a player to the matchmaking queue in Redis."""
    key = f"matchmaking:{game_type_id}:{token}"
    data = json.dumps({
        "rating": rating,
        "token": token,
        "channel_name": channel_name,
    })
    await redis_conn.set(key, data)


async def remove_from_queue(redis_conn, game_type_id: int, token: str) -> None:
    """Remove a player from the matchmaking queue."""
    key = f"matchmaking:{game_type_id}:{token}"
    await redis_conn.delete(key)
