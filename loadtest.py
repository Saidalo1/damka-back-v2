"""
Load test for the Damka realtime backend.

Simulates N human games (2*N players matched via matchmaking, then playing
random legal moves back-and-forth) plus M bot games, all concurrently, and
measures move round-trip latency + the BACKEND process's CPU/RAM (isolated from
this generator so the numbers reflect the server, not the test client).

Usage:  python loadtest.py [N_HUMAN_GAMES] [N_BOT_GAMES] [MOVE_CAP]
"""
import asyncio
import json
import random
import secrets
import statistics
import sys
import time

import os

import websockets

try:
    import psutil
except ImportError:
    psutil = None

BASE = os.environ.get("LOADTEST_BASE", "ws://127.0.0.1:8000")
GAME_TYPE_ID = 4  # "5 min"
# arg1: number of matchmade human games, OR "pre" to play loadtest_games.json.
MODE = sys.argv[1] if len(sys.argv) > 1 else "100"
N_HUMAN = int(MODE) if MODE.isdigit() else 0
N_BOT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
MOVE_CAP = int(sys.argv[3]) if len(sys.argv) > 3 else 16
DURATION_CAP = 90  # seconds a single game is allowed to run
RAMP = float(os.environ.get("LOADTEST_RAMP", "8"))  # spread connects over N s

lat = []           # move round-trip latencies (ms)
moves = 0
errors = 0
connected = 0
games_started = 0


async def _recv(ws, t=10):
    try:
        return json.loads(await asyncio.wait_for(ws.recv(), t))
    except Exception:
        return None


async def _matchmake(token):
    try:
        async with websockets.connect(f"{BASE}/ws/matchmaking/?authorization={token}") as ws:
            await ws.send(json.dumps({"type": "search",
                                      "message": {"game_type_id": GAME_TYPE_ID, "rating_level": 3}}))
            t = time.time()
            while time.time() - t < 40:
                m = await _recv(ws, 25)
                if m and m.get("event") == "matched":
                    me = next((u for u in m.get("users", []) if u.get("is_you")), {})
                    return m["game_id"], me.get("color")
    except Exception:
        pass
    return None, None


async def _run_game(ws, my_color=None, is_bot=False):
    """Common play loop: the server only sends `possible_moves` to the player on
    turn, so whenever we receive them we play a random legal move."""
    global moves, connected, games_started
    connected += 1
    games_started += 1
    my_moves = 0
    pending = None
    start = time.time()

    async def move_if_my_turn(msg):
        nonlocal my_moves, pending
        pm = msg.get("possible_moves")
        if pm and pending is None and my_moves < MOVE_CAP:
            pending = time.perf_counter()
            await ws.send(json.dumps({"type": "move", "message": random.choice(pm)}))

    init = await _recv(ws, 12)
    if init is None:
        return
    await move_if_my_turn(init)

    while time.time() - start < DURATION_CAP and my_moves < MOVE_CAP:
        msg = await _recv(ws, 10)
        if msg is None:
            break
        ev = msg.get("event")
        if ev == "move":
            # My move's ack arrives with no possible_moves (opponent's turn now).
            if pending is not None and not msg.get("possible_moves"):
                lat.append((time.perf_counter() - pending) * 1000)
                pending = None
                my_moves += 1
                moves += 1
            await move_if_my_turn(msg)
        elif ev == "game_over":
            break


async def play_human(token):
    global errors
    await asyncio.sleep(random.uniform(0, RAMP))  # ramp up (avoid a connect storm)
    gid, color = await _matchmake(token)
    if not gid:
        errors += 1
        return
    try:
        async with websockets.connect(f"{BASE}/ws/game/{gid}/?authorization={token}") as ws:
            await _run_game(ws, color)
    except Exception:
        errors += 1


async def play_bot(token):
    global errors
    await asyncio.sleep(random.uniform(0, RAMP))
    try:
        async with websockets.connect(f"{BASE}/ws/game/bot/?authorization={token}") as ws:
            await ws.send(json.dumps({"type": "game_type", "message": {"color": 2, "level": 1}}))
            await _run_game(ws, None, is_bot=True)
    except Exception:
        errors += 1


async def play_pre(game_id, token):
    """Play a pre-created game (bypasses matchmaking)."""
    global errors
    try:
        async with websockets.connect(f"{BASE}/ws/game/{game_id}/?authorization={token}") as ws:
            await _run_game(ws)
    except Exception:
        errors += 1


def _find_daphne():
    if not psutil:
        return None
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cl = " ".join(p.info.get("cmdline") or [])
            if "daphne" in cl and "8000" in cl:
                return p
        except Exception:
            continue
    return None


async def _sample_backend(stop):
    proc = _find_daphne()
    if not proc:
        return None
    cpu, rss = [], []
    proc.cpu_percent(None)  # prime
    ncpu = psutil.cpu_count() or 1
    while not stop.is_set():
        await asyncio.sleep(1.0)
        try:
            cpu.append(proc.cpu_percent(None) / ncpu)  # normalized 0-100% of the box
            rss.append(proc.memory_info().rss / 1e6)   # MB
        except Exception:
            break
    if not cpu:
        return None
    return {"cpu_avg": statistics.mean(cpu), "cpu_max": max(cpu),
            "rss_avg": statistics.mean(rss), "rss_max": max(rss), "ncpu": ncpu}


async def main():
    print(f"Load test: {N_HUMAN} human games ({N_HUMAN*2} players) + {N_BOT} bot games, "
          f"move cap {MOVE_CAP}/game. psutil={'yes' if psutil else 'no'}")
    stop = asyncio.Event()
    sampler = asyncio.create_task(_sample_backend(stop))
    t0 = time.time()

    tasks = []
    if MODE == "pre":
        with open("loadtest_games.json") as f:
            pre_games = json.load(f)
        for g in pre_games:
            tasks.append(asyncio.create_task(play_pre(g["game_id"], g["white"])))
            tasks.append(asyncio.create_task(play_pre(g["game_id"], g["black"])))
        print(f"  (playing {len(pre_games)} pre-created games)")
    else:
        tasks = [asyncio.create_task(play_human(secrets.token_urlsafe(32))) for _ in range(N_HUMAN * 2)]
    tasks += [asyncio.create_task(play_bot(secrets.token_urlsafe(32))) for _ in range(N_BOT)]
    await asyncio.gather(*tasks, return_exceptions=True)

    dur = time.time() - t0
    stop.set()
    res = await sampler

    print("\n================ RESULTS ================")
    print(f"duration            : {dur:.1f}s")
    print(f"games started       : {games_started}  | connections: {connected}  | errors: {errors}")
    print(f"total moves          : {moves}  ({moves/dur:.0f} moves/s)")
    if lat:
        s = sorted(lat)
        p = lambda q: s[min(len(s) - 1, int(len(s) * q))]
        print(f"move round-trip (ms) : p50={p(0.5):.0f}  p95={p(0.95):.0f}  p99={p(0.99):.0f}  max={max(s):.0f}")
    if res:
        print(f"BACKEND cpu (of {res['ncpu']} cores): avg={res['cpu_avg']:.1f}%  peak={res['cpu_max']:.1f}%")
        print(f"BACKEND memory       : avg={res['rss_avg']:.0f}MB  peak={res['rss_max']:.0f}MB")
    print("=========================================")


if __name__ == "__main__":
    asyncio.run(main())
