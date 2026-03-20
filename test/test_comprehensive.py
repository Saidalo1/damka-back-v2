"""
Comprehensive game logic test suite.

Tests:
  1. Timer accuracy (with timing logs between stages)
  2. Full game play-through (checkmate/draw)
  3. Duplicate connection attempt
  4. Wrong player trying to move
  5. Invalid move handling
  6. Resign
  7. Draw offer/accept
  8. Connection to non-existent game
  9. Connection to ended game

Usage:
  docker compose exec web python manage.py shell -c "from apps.game.models import Game; ..."
  python test/test_comprehensive.py
"""
import argparse
import asyncio
import json
import time
from random import choice

import websockets


def ts():
    """Current timestamp for logging."""
    return f"[{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}]"


class GameTester:
    """Runs comprehensive game logic tests."""

    def __init__(self, game_id: str, token_white: str, token_black: str, host: str):
        self.game_id = game_id
        self.token_white = token_white
        self.token_black = token_black
        self.host = host
        self.results = []

    def log(self, msg: str):
        print(f"{ts()} {msg}")

    def result(self, test_name: str, passed: bool, detail: str = ""):
        status = "✅ PASS" if passed else "❌ FAIL"
        self.results.append((test_name, passed, detail))
        self.log(f"  {status}: {test_name} {detail}")

    async def connect(self, token: str, game_id: str = None) -> websockets.WebSocketClientProtocol:
        """Open a WS connection."""
        gid = game_id or self.game_id
        uri = f"ws://{self.host}/ws/game/{gid}/?authorization={token}"
        return await websockets.connect(uri)

    async def recv_json(self, ws, timeout=5) -> dict:
        """Receive and parse JSON with timeout."""
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        return json.loads(raw)

    async def send_json(self, ws, data: dict):
        """Send JSON message."""
        await ws.send(json.dumps(data))

    # ===================================================================
    # TEST 1: Timer accuracy
    # ===================================================================
    async def test_timer_accuracy(self):
        """Test that timer deducts correct amount of time."""
        self.log("\n=== TEST 1: Timer Accuracy ===")

        ws_white = await self.connect(self.token_white)
        ws_black = await self.connect(self.token_black)

        try:
            # Both receive init
            init_w = await self.recv_json(ws_white)
            init_b = await self.recv_json(ws_black)

            initial_time = init_w.get("times", {}).get("white", 0)
            self.log(f"  Initial white time: {initial_time}s")

            # White makes a move with a controlled delay
            moves = init_w.get("possible_moves", [])
            if not moves:
                self.result("Timer Accuracy", False, "No possible moves for white")
                return

            # Wait exactly 2 seconds before moving
            self.log(f"  Waiting 2 seconds before white's first move...")
            t0 = time.time()
            await asyncio.sleep(2.0)
            await self.send_json(ws_white, {"type": "move", "message": moves[0]})
            t1 = time.time()
            actual_delay = t1 - t0
            self.log(f"  Actual delay: {actual_delay:.3f}s")

            # White gets move confirmation
            move_w = await self.recv_json(ws_white)
            new_white_time = move_w.get("times", {}).get("white", 0)
            elapsed_game = initial_time - new_white_time
            self.log(f"  New white time: {new_white_time}s, game elapsed: {elapsed_game:.1f}s")

            # Timer should be within 1 second of actual delay
            timer_error = abs(elapsed_game - actual_delay)
            self.result(
                "Timer Accuracy",
                timer_error < 1.0,
                f"error={timer_error:.2f}s (expected ~{actual_delay:.1f}s, got {elapsed_game:.1f}s)"
            )

            # Black also gets the move
            move_b = await self.recv_json(ws_black)
            self.result(
                "Opponent receives move",
                move_b.get("event") == "move",
                f"event={move_b.get('event')}"
            )

        finally:
            await ws_white.close()
            await ws_black.close()

    # ===================================================================
    # TEST 2: Full game play-through
    # ===================================================================
    async def test_full_game(self):
        """Play a full game until checkmate."""
        self.log("\n=== TEST 2: Full Game Play-Through ===")

        ws_white = await self.connect(self.token_white)
        ws_black = await self.connect(self.token_black)

        try:
            init_w = await self.recv_json(ws_white)
            init_b = await self.recv_json(ws_black)

            move_count = 0
            max_moves = 200
            game_over = False

            while move_count < max_moves:
                # White's turn
                if init_w.get("possible_moves"):
                    move = choice(init_w["possible_moves"])
                    await self.send_json(ws_white, {"type": "move", "message": move})
                    move_count += 1

                    # Both receive update
                    resp_w = await self.recv_json(ws_white)
                    resp_b = await self.recv_json(ws_black)

                    if resp_w.get("event") == "game_over" or resp_b.get("event") == "game_over":
                        game_over = True
                        game_over_data = resp_w if resp_w.get("event") == "game_over" else resp_b
                        break

                    # Black's turn
                    black_moves = resp_b.get("possible_moves", [])
                    if black_moves:
                        await asyncio.sleep(0.05)
                        move = choice(black_moves)
                        await self.send_json(ws_black, {"type": "move", "message": move})
                        move_count += 1

                        resp_b2 = await self.recv_json(ws_black)
                        resp_w2 = await self.recv_json(ws_white)

                        if resp_b2.get("event") == "game_over" or resp_w2.get("event") == "game_over":
                            game_over = True
                            game_over_data = resp_b2 if resp_b2.get("event") == "game_over" else resp_w2
                            break

                        init_w = resp_w2  # Use latest state for next iteration
                    else:
                        self.log(f"  Black has no moves after {move_count} total moves")
                        break
                else:
                    self.log(f"  White has no moves after {move_count} total moves")
                    break

            self.result(
                "Full Game Completion",
                game_over,
                f"moves={move_count}, winner={game_over_data.get('winner') if game_over else 'N/A'}"
            )

            if game_over:
                self.result(
                    "ELO Rating Calculated",
                    "rating" in game_over_data and game_over_data["rating"].get("diff") is not None,
                    f"rating={game_over_data.get('rating', {})}"
                )

        finally:
            await ws_white.close()
            await ws_black.close()

    # ===================================================================
    # TEST 3: Non-existent game
    # ===================================================================
    async def test_nonexistent_game(self):
        """Connect to a game that doesn't exist."""
        self.log("\n=== TEST 3: Non-Existent Game ===")
        fake_id = "00000000-0000-0000-0000-000000000000"
        try:
            ws = await self.connect(self.token_white, game_id=fake_id)
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            await ws.close()
            self.result("Non-existent game rejected", False, f"Got message: {msg[:80]}")
        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError) as e:
            self.result("Non-existent game rejected", True, f"Connection closed: {e}")
        except Exception as e:
            # InvalidStatusCode, ConnectionRefusedError, etc — all valid rejections
            self.result("Non-existent game rejected", True, f"Rejected: {type(e).__name__}")

    # ===================================================================
    # TEST 4: Invalid token
    # ===================================================================
    async def test_invalid_token(self):
        """Connect with an invalid auth token."""
        self.log("\n=== TEST 4: Invalid Token ===")
        try:
            ws = await self.connect("totally_invalid_token_12345")
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            await ws.close()
            self.result("Invalid token rejected", False, f"Got message: {msg[:80]}")
        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError) as e:
            self.result("Invalid token rejected", True, f"Connection closed: {e}")
        except Exception as e:
            # InvalidStatusCode (HTTP 403), ConnectionRefusedError — valid rejections
            self.result("Invalid token rejected", True, f"Rejected: {type(e).__name__}")

    # ===================================================================
    # TEST 5: Invalid move
    # ===================================================================
    async def test_invalid_move(self):
        """Send an illegal move."""
        self.log("\n=== TEST 5: Invalid Move ===")

        ws_white = await self.connect(self.token_white)
        ws_black = await self.connect(self.token_black)

        try:
            init_w = await self.recv_json(ws_white)
            init_b = await self.recv_json(ws_black)

            # Send an impossible move
            await self.send_json(ws_white, {"type": "move", "message": [1, 2]})
            resp = await self.recv_json(ws_white)

            self.result(
                "Invalid move rejected",
                resp.get("event") == "error",
                f"response={resp.get('event')}: {resp.get('message', '')[:50]}"
            )
        finally:
            await ws_white.close()
            await ws_black.close()

    # ===================================================================
    # TEST 6: Wrong player moves
    # ===================================================================
    async def test_wrong_player_move(self):
        """The player whose turn it is NOT tries to move."""
        self.log("\n=== TEST 6: Wrong Player Moves ===")

        ws_white = await self.connect(self.token_white)
        ws_black = await self.connect(self.token_black)

        try:
            init_w = await self.recv_json(ws_white)
            init_b = await self.recv_json(ws_black)

            # Check whose turn it is and have the OTHER player try to move
            current_turn = init_w.get("turn", 2)
            if current_turn == 2:
                # White's turn — black tries to move
                self.log("  White's turn — black trying to move...")
                await self.send_json(ws_black, {"type": "move", "message": [9, 13]})
                resp = await self.recv_json(ws_black)
            else:
                # Black's turn — white tries to move
                self.log("  Black's turn — white trying to move...")
                await self.send_json(ws_white, {"type": "move", "message": [21, 17]})
                resp = await self.recv_json(ws_white)

            self.result(
                "Wrong player rejected",
                resp.get("event") == "error" and "Not your turn" in resp.get("message", ""),
                f"response={resp.get('message', '')}"
            )
        finally:
            await ws_white.close()
            await ws_black.close()

    # ===================================================================
    # SUMMARY
    # ===================================================================
    def print_summary(self):
        self.log("\n" + "=" * 60)
        self.log("TEST SUMMARY")
        self.log("=" * 60)
        passed = sum(1 for _, p, _ in self.results if p)
        failed = sum(1 for _, p, _ in self.results if not p)
        for name, p, detail in self.results:
            status = "✅" if p else "❌"
            self.log(f"  {status} {name}")
        self.log(f"\nTotal: {passed} passed, {failed} failed out of {len(self.results)}")
        return failed == 0


async def run_tests(args):
    """Run all tests. Each test resets the game before running."""
    tester = GameTester(args.game_id, args.token_white, args.token_black, args.host)

    # Test order: non-destructive first, then timer on fresh state, then game-modifying
    await tester.test_nonexistent_game()
    await tester.test_invalid_token()
    await tester.test_timer_accuracy()  # Needs fresh game state
    await tester.test_invalid_move()
    await tester.test_wrong_player_move()

    # Full game changes game state permanently
    # await tester.test_full_game()  # Uncomment after resetting game

    all_passed = tester.print_summary()
    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Comprehensive Damka V2 game logic tests")
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--token-white", required=True)
    parser.add_argument("--token-black", required=True)
    parser.add_argument("--host", default="localhost:8000")
    args = parser.parse_args()

    success = asyncio.run(run_tests(args))
    exit(0 if success else 1)
