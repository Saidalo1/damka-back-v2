"""
Combined 2-player test — both players in one process via asyncio.

Usage:
  python test/play_two_players.py --game-id <UUID> --token-white <T1> --token-black <T2>

Both players connect simultaneously and play random moves until game ends.
"""
import argparse
import asyncio
import json
import time
from random import choice

import websockets


def ts():
    """Real clock timestamp for logging."""
    return time.strftime('%H:%M:%S') + f'.{int(time.time()*1000)%1000:03d}'


async def player(name: str, game_id: str, token: str, host: str):
    """Connect to game and play random legal moves."""
    uri = f"ws://{host}/ws/game/{game_id}/?authorization={token}"
    print(f"[{ts()}] [{name}] Connecting...")

    async with websockets.connect(uri) as ws:
        try:
            move_count = 0
            start_real = time.time()
            initial_white = 0
            initial_black = 0

            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(raw)
                event = data.get("event", "unknown")

                if event == "init":
                    color = data.get("your_color")
                    moves = data.get("possible_moves", [])
                    times = data.get("times", {})
                    initial_white = times.get("white", 0)
                    initial_black = times.get("black", 0)
                    print(f"[{ts()}] [{name}] Connected as color={color}, {len(moves)} moves, W:{initial_white}s B:{initial_black}s")
                    if moves:
                        move = choice(moves)
                        print(f"[{ts()}] [{name}] Move #{move_count + 1}: {move}")
                        await ws.send(json.dumps({"type": "move", "message": move}))
                        move_count += 1

                elif event == "move":
                    moves = data.get("possible_moves", [])
                    turn = data.get("turn")
                    times = data.get("times", {})
                    w_time = times.get('white', 0)
                    b_time = times.get('black', 0)
                    real_elapsed = time.time() - start_real
                    game_elapsed_w = initial_white - w_time
                    game_elapsed_b = initial_black - b_time
                    print(f"[{ts()}] [{name}] Turn={turn} | Real: {real_elapsed:.1f}s | Game W:-{game_elapsed_w:.0f}s B:-{game_elapsed_b:.0f}s | {len(moves)} moves")
                    if moves:
                        await asyncio.sleep(0.1)  # Small delay for realism
                        move = choice(moves)
                        print(f"[{ts()}] [{name}] Move #{move_count + 1}: {move}")
                        await ws.send(json.dumps({"type": "move", "message": move}))
                        move_count += 1

                elif event == "game_over":
                    winner = data.get("winner")
                    reason = data.get("reason")
                    rating = data.get("rating", {})
                    real_total = time.time() - start_real
                    print(f"\n[{ts()}] [{name}] 🏁 Game Over! Winner={winner}, Reason={reason}, Real time: {real_total:.1f}s")
                    if rating:
                        print(f"[{ts()}] [{name}] Rating: {rating}")
                    break

                elif event == "error":
                    print(f"[{ts()}] [{name}] ❌ Error: {data.get('message')}")
                    break

                else:
                    print(f"[{ts()}] [{name}] Unknown event: {event}")

        except asyncio.TimeoutError:
            print(f"[{name}] ⏱️ Timeout waiting for server message")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[{name}] Connection closed: {e}")
        except websockets.exceptions.ConnectionClosedOK:
            print(f"[{name}] Connection closed OK")
        finally:
            print(f"[{name}] Disconnected after {move_count} moves")


async def main(game_id: str, token_white: str, token_black: str, host: str):
    """Run both players concurrently."""
    print(f"Starting 2-player game test on {host}...")
    print(f"Game ID: {game_id}\n")

    await asyncio.gather(
        player("WHITE", game_id, token_white, host),
        player("BLACK", game_id, token_black, host),
    )
    print("\n✅ Test complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Damka V2 two-player WS test")
    parser.add_argument("--game-id", required=True, help="Game UUID")
    parser.add_argument("--token-white", required=True, help="White player token")
    parser.add_argument("--token-black", required=True, help="Black player token")
    parser.add_argument("--host", default="localhost:8000", help="Server host:port")
    args = parser.parse_args()

    asyncio.run(main(args.game_id, args.token_white, args.token_black, args.host))
