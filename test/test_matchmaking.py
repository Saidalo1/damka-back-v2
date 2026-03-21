"""
Matchmaking test — two players search for each other.

Usage:
  1. Start the server: docker compose up
  2. Run two instances in parallel:
     python test/test_matchmaking.py --token <TOKEN_1> --game-type 1
     python test/test_matchmaking.py --token <TOKEN_2> --game-type 1

When matched, both will get a game_id and play random moves.
"""
import argparse
import asyncio
import json
from random import choice

import websockets


async def test_matchmaking(token: str, game_type_id: int, host: str = "localhost:8000"):
    """Connect to matchmaking, find opponent, then play random moves."""
    uri = f"ws://{host}/ws/matchmaking/?authorization={token}"
    print(f"Searching for opponent (game_type={game_type_id})...")

    async with websockets.connect(uri) as ws:
        # Send search request
        # Backend requires rating_level for guest tokens (len >= 43)
        is_guest = len(token) >= 43
        search_msg = {
            "type": "search",
            "message": {
                "game_type_id": game_type_id,
            },
        }
        if is_guest:
            search_msg["message"]["rating_level"] = 3  # ~1200 rating
        await ws.send(json.dumps(search_msg))

        try:
            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                print(json.dumps(data, indent=2, ensure_ascii=False))

                # Check if we got matched
                event = data.get("event")
                if event == "matched":
                    game_id = data.get("game_id")
                    print(f"\n✅ Matched! Game ID: {game_id}")
                    print("Connect with: python test/play_random.py "
                          f"--game-id {game_id} --token {token}")
                    break

        except websockets.exceptions.ConnectionClosedError as e:
            print(f"Connection closed: {e}")
        finally:
            print("Disconnected from matchmaking.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Damka V2 matchmaking test")
    parser.add_argument("--token", required=True, help="Auth/anonym token")
    parser.add_argument("--game-type", type=int, default=1, help="GameTypesTime ID")
    parser.add_argument("--host", default="localhost:8000", help="Server host:port")
    args = parser.parse_args()

    asyncio.run(test_matchmaking(args.token, args.game_type, args.host))
