"""End-to-end integration test for GameWithBotConsumer (no DB / no Redis needed).

Uses Channels WebsocketCommunicator to drive the in-memory bot consumer through a
full game, validating the init/move/game_over protocol. Guarded with __main__ so
the ProcessPoolExecutor (spawn) doesn't re-run the test in child processes.
"""
import os
import asyncio

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")


async def play_one(color, level, label):
    from channels.testing import WebsocketCommunicator
    from apps.game.consumers.bot import GameWithBotConsumer

    comm = WebsocketCommunicator(GameWithBotConsumer.as_asgi(), "/ws/game/bot/")
    connected, _ = await comm.connect()
    assert connected, "failed to connect"

    await comm.send_json_to({"type": "game_type", "message": {"color": color, "level": level}})

    init = await comm.receive_json_from(timeout=20)
    assert init["event"] == "init", init
    assert init["your_color"] == color
    assert "session_score" in init and "users" in init
    print(f"[{label}] init ok: your_color={init['your_color']} turn={init['turn']} "
          f"pm={len(init.get('possible_moves', []))} users={[u['username'] for u in init['users']]}")

    # If bot opened (user is black), drain the bot's first move event.
    possible = init.get("possible_moves", [])
    if not possible:
        ev = await comm.receive_json_from(timeout=20)
        assert ev["event"] in ("move", "game_over"), ev
        if ev["event"] == "move":
            possible = ev.get("possible_moves", [])
        else:
            print(f"[{label}] immediate game_over: {ev['winner']}")
            await comm.disconnect()
            return ev

    moves_played = 0
    last = None
    for _ in range(200):
        if not possible:
            # Not our turn / no moves surfaced — read next server event.
            ev = await comm.receive_json_from(timeout=20)
            if ev["event"] == "game_over":
                last = ev
                break
            possible = ev.get("possible_moves", [])
            continue

        # Make our move (first legal), then read back user-move + bot-move events.
        await comm.send_json_to({"type": "move", "message": possible[0]})
        moves_played += 1
        possible = []

        # Read events until we either get our possible_moves again or game_over.
        got_turn = False
        for _ in range(4):
            ev = await comm.receive_json_from(timeout=20)
            assert ev["event"] in ("move", "game_over", "error"), ev
            if ev["event"] == "error":
                raise AssertionError(f"server error: {ev}")
            if ev["event"] == "game_over":
                last = ev
                got_turn = True
                break
            # move event: validate shape
            assert "fen" in ev and "turn" in ev and "pdn" in ev and "last_move" in ev
            if ev.get("possible_moves"):
                possible = ev["possible_moves"]
                got_turn = True
                break
        if last and last["event"] == "game_over":
            break
        if not got_turn:
            raise AssertionError("did not regain turn or end")

    assert last and last["event"] == "game_over", f"game did not end cleanly (moves={moves_played})"
    assert "winner" in last and "session_score" in last
    print(f"[{label}] game_over after {moves_played} user moves: winner={last['winner']} "
          f"session={last['session_score']}")

    # Test rematch resets and starts fresh
    await comm.send_json_to({"type": "rematch"})
    reinit = await comm.receive_json_from(timeout=20)
    assert reinit["event"] == "init", reinit
    print(f"[{label}] rematch ok: session={reinit['session_score']}")

    await comm.disconnect()
    return last


async def test_resign():
    from channels.testing import WebsocketCommunicator
    from apps.game.consumers.bot import GameWithBotConsumer
    comm = WebsocketCommunicator(GameWithBotConsumer.as_asgi(), "/ws/game/bot/")
    ok, _ = await comm.connect()
    assert ok
    await comm.send_json_to({"type": "game_type", "message": {"color": 2, "level": 1}})
    init = await comm.receive_json_from(timeout=20)
    assert init["event"] == "init"
    await comm.send_json_to({"type": "lose"})
    over = await comm.receive_json_from(timeout=20)
    assert over["event"] == "game_over" and over["reason"] == "resign"
    assert over["winner"] == 1  # user was white(2) → bot(black=1) wins
    print(f"[resign] ok: winner={over['winner']} reason={over['reason']}")
    await comm.disconnect()


async def main():
    # user plays white vs MEDIUM bot
    await play_one(color=2, level=2, label="white-vs-medium")
    # user plays black (bot opens) vs EASY bot
    await play_one(color=1, level=1, label="black-vs-easy")
    await test_resign()
    print("\nALL BOT CONSUMER TESTS PASSED")


if __name__ == "__main__":
    import django
    django.setup()
    asyncio.run(main())
