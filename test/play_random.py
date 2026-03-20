"""
WebSocket test client — plays a game with random moves (no frontend needed).

Usage:
  1. Start the server: docker compose up
  2. Create a test game (via Django shell or API)
  3. Run two instances:
     python test/play_random.py --game-id <UUID> --token <TOKEN_1>
     python test/play_random.py --game-id <UUID> --token <TOKEN_2>

Both players will play random moves until the game ends.
"""
import argparse
import asyncio
import json
from random import choice

import websockets


async def play_random(game_id: str, token: str, host: str = "localhost:8000"):
    """Connect to a game and play random legal moves."""
    uri = f"ws://{host}/ws/game/{game_id}/?authorization={token}"
    print(f"Connecting to {uri}...")

    async with websockets.connect(uri) as ws:
        try:
            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                print(f"\n{'='*60}")
                print(json.dumps(data, indent=2, ensure_ascii=False))

                # Check for game over
                event = data.get("event")
                if event == "game_over":
                    print(f"\n🏁 Game over! Winner: {data.get('winner')}, Reason: {data.get('reason')}")
                    break

                # If we have possible moves, play a random one
                possible_moves = data.get("possible_moves", [])
                if possible_moves:
                    move = choice(possible_moves)
                    msg = json.dumps({"type": "move", "message": move})
                    print(f"\n🎮 Playing move: {move}")
                    await ws.send(msg)

        except websockets.exceptions.ConnectionClosedError as e:
            print(f"Connection closed: {e}")
        except websockets.exceptions.ConnectionClosedOK:
            print("Connection closed OK.")
        finally:
            print("Disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Damka V2 WebSocket test client")
    parser.add_argument("--game-id", required=True, help="Game UUID")
    parser.add_argument("--token", required=True, help="Auth token or anonym token")
    parser.add_argument("--host", default="localhost:8000", help="Server host:port")
    args = parser.parse_args()

    asyncio.run(play_random(args.game_id, args.token, args.host))
