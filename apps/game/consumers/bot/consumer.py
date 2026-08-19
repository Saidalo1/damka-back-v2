"""
Bot game consumer — play against the AI.

Design parity (figma `10-bot-setup-*`, `11-bot-game-*`):
  - client picks difficulty (Oson/O'rta/Qiyin) + color (Oq/Random/Qora)
  - purple "Bot bilan o'ynash" theme, robot avatar
  - same board/history UI as the online game

Architecture:
  - Self-contained: the board lives IN MEMORY on the consumer (bot games are NOT
    persisted to DB — same as V1). No channel group, no Celery, no Game row.
  - Emits the SAME event protocol as the online GameConsumer (`init` / `move` /
    `game_over`) so the frontend board component is reused verbatim.
  - The bot search runs OFF the event loop via `bot_runner.compute_bot_move`.

Client → server:
  {"type": "game_type", "message": {"color": 2, "level": 1}}   # color 1=black 2=white 0=random
  {"type": "move",      "message": [21, 17]}                    # 1-indexed square list
  {"type": "lose"}                                              # resign
  {"type": "rematch"}                                           # new game, same settings
"""
import asyncio
import logging
import random
import time
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.game.services.board import (
    create_board,
    get_legal_moves_as_lists,
    get_turn_color,
    make_move,
)
from apps.game.services.bot_runner import (
    EVAL_HARD_DEPTH_CAP,
    analysis_budget,
    compute_bot_move,
    compute_eval_at_depth,
)
from apps.game.services.bot_store import delete_bot_game, get_redis, save_bot_game
from bot_ai.engine import EASY, HARD, MEDIUM, WIN_SCORE, evaluate_position
from shared.django import ColorChoices

logger = logging.getLogger(__name__)

_VALID_LEVELS = (EASY, MEDIUM, HARD)

# Live eval bar: after each move we stream a deepening eval of the current
# position so the bar animates and reflects real combinations. How deep it gets
# is bounded by a TIME BUDGET (bot_runner.analysis_budget), not a static cap.
_ANALYSIS_WIN_CUTOFF = WIN_SCORE - 10_000  # stop deepening once a win is proven


class GameWithBotConsumer(AsyncJsonWebsocketConsumer):
    """Game against the AI bot. State lives in Redis (keyed by token, TTL), not
    in worker RAM — see apps/game/services/bot_store.py."""

    # Live load signal (shared across all bot games) → the eval bar backs off
    # when many games run at once; gameplay always keeps priority.
    _active_games = 0

    async def connect(self):
        GameWithBotConsumer._active_games += 1
        self.redis = get_redis()
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        self.token = qs.get("authorization", [None])[0]  # Redis key for this game
        self.board = None
        self.user_color = None
        self.bot_color = None
        self.level = MEDIUM
        self.captured_white = 0
        self.captured_black = 0
        self.session = {"white": 0, "black": 0, "draws": 0}
        self.finished = True  # no game until game_type received
        self.analysis_task = None
        await self.accept()

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if msg_type == "ping":
            await self.send_json({"event": "pong"})
            return
        if msg_type == "game_type":
            await self._setup(content.get("message") or {})
        elif msg_type == "move":
            await self._handle_move(content.get("message"))
        elif msg_type == "lose":
            await self._resign()
        elif msg_type == "rematch":
            await self._rematch()
        else:
            await self.send_json({"event": "error", "message": f"Unknown type: {msg_type}"})

    async def disconnect(self, close_code):
        # The game state stays in Redis with its TTL (evicted a while after the
        # player leaves). Just stop analysis and release the Redis client.
        GameWithBotConsumer._active_games = max(0, GameWithBotConsumer._active_games - 1)
        self._cancel_analysis()
        # redis client is process-shared — don't close it here.
        return

    # ------------------------------------------------------------ persistence
    def _state_dict(self) -> dict:
        return {
            "fen": self.board.fen if self.board is not None else None,
            "user_color": self.user_color,
            "bot_color": self.bot_color,
            "level": self.level,
            "captured_white": self.captured_white,
            "captured_black": self.captured_black,
            "session": self.session,
            "finished": self.finished,
        }

    async def _persist(self) -> None:
        """Write current game state to Redis (refreshes the TTL)."""
        if self.token and self.board is not None and not self.finished:
            await save_bot_game(self.redis, self.token, self._state_dict())

    # -------------------------------------------------------------- eval bar
    def _cancel_analysis(self):
        if self.analysis_task and not self.analysis_task.done():
            self.analysis_task.cancel()
        self.analysis_task = None

    def _start_analysis(self):
        """Stream a deepening eval of the current position to the client."""
        self._cancel_analysis()
        if self.board is None or self.finished or self.board.game_over:
            return
        self.analysis_task = asyncio.create_task(self._run_analysis(self.board.fen))

    async def _run_analysis(self, fen: str):
        # Time-budgeted iterative deepening: go as deep as the server can within
        # the budget (deep when idle/fast, shallow when slow/busy) — no static
        # depth cap. Budget shrinks (or drops to 0) as live load climbs.
        budget = analysis_budget(GameWithBotConsumer._active_games)
        if budget <= 0.0:
            return  # under heavy load the eval bar analysis is dropped entirely

        deadline = time.monotonic() + budget
        prev_dt = 0.0
        try:
            # Start at depth 3: depths 1-2 are noisy (search instability) and make
            # the bar twitch; the frontend eases the rest. Hybrid smoothing.
            for depth in range(3, EVAL_HARD_DEPTH_CAP + 1):
                now = time.monotonic()
                # Don't START a depth we can't finish in budget (~5x the last
                # one) — keeps total work near budget and a pool worker free.
                # Skip the estimate for depths 3-5: they're always cheap, and the
                # first call's timing includes pool warm-up (not real search).
                if now >= deadline or (depth >= 6 and now + prev_dt * 3 > deadline):
                    return
                t0 = time.monotonic()
                cp = await compute_eval_at_depth(fen, depth)
                prev_dt = time.monotonic() - t0
                # Abort if the position moved on while we were computing.
                if self.board is None or self.board.fen != fen or self.finished:
                    return
                await self.send_json({"event": "eval", "eval": cp, "depth": depth})
                if abs(cp) >= _ANALYSIS_WIN_CUTOFF:
                    return  # forced result found — no point going deeper
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - analysis is best-effort
            logger.exception("Eval analysis failed for fen %s", fen)

    # ------------------------------------------------------------------ setup
    async def _setup(self, message: dict):
        color = message.get("color", ColorChoices.white)
        if color not in (ColorChoices.white, ColorChoices.black):
            color = random.choice([ColorChoices.white, ColorChoices.black])

        level = message.get("level", MEDIUM)
        self.level = level if level in _VALID_LEVELS else MEDIUM

        self.user_color = color
        self.bot_color = (
            ColorChoices.black if color == ColorChoices.white else ColorChoices.white
        )
        self.board = create_board("startpos")
        self.captured_white = 0
        self.captured_black = 0
        self.finished = False

        await self._send_initial_state()

        # White always moves first — if the bot is white, it opens.
        if get_turn_color(self.board) == self.bot_color:
            await self._play_bot_move()
        else:
            self._start_analysis()

    async def _rematch(self):
        """Start a fresh game with the same color + level (session score persists)."""
        if self.user_color is None:
            await self.send_json({"event": "error", "message": "No game to rematch"})
            return
        self.board = create_board("startpos")
        self.captured_white = 0
        self.captured_black = 0
        self.finished = False
        await self._send_initial_state()
        if get_turn_color(self.board) == self.bot_color:
            await self._play_bot_move()
        else:
            self._start_analysis()

    # ------------------------------------------------------------------ moves
    async def _handle_move(self, message):
        if self.board is None or self.finished:
            await self.send_json({"event": "error", "message": "Game not active"})
            return
        if not isinstance(message, list):
            await self.send_json({"event": "error", "message": "Invalid move"})
            return
        if get_turn_color(self.board) != self.user_color:
            await self.send_json({"event": "error", "message": "Not your turn"})
            return

        self._cancel_analysis()  # position is changing
        try:
            result = make_move(self.board, message)
        except ValueError as e:
            await self.send_json({"event": "error", "message": str(e)})
            return

        self._add_capture(self.user_color, result)
        await self._send_move_event(result, message)

        if result["game_over"]:
            await self._end(result["winner"], reason="checkmate")
            return

        # Analyse the bot-to-move position WHILE the bot thinks, so the bar
        # already shows the bot's best reply (minimax) — no surprise drop when
        # it actually moves. It auto-aborts once the bot's move changes the board.
        self._start_analysis()
        await self._play_bot_move()

    async def _play_bot_move(self):
        """Compute the bot's move off the event loop, apply it, broadcast."""
        move = await compute_bot_move(self.board.fen, self.level)
        if not move:
            return  # no legal move → board.game_over would already have fired

        try:
            result = make_move(self.board, move)
        except ValueError:
            logger.exception("Bot produced an illegal move %s on fen %s", move, self.board.fen)
            return

        self._add_capture(self.bot_color, result)
        await self._send_move_event(result, move)

        if result["game_over"]:
            await self._end(result["winner"], reason="checkmate")
        else:
            self._start_analysis()  # now the human's turn — stream a deepening eval

    async def _resign(self):
        if self.board is None or self.finished:
            return
        await self._end(self.bot_color, reason="resign")

    # ------------------------------------------------------------------ send
    async def _send_initial_state(self):
        my_turn = get_turn_color(self.board) == self.user_color
        await self.send_json({
            "event": "init",
            "fen": self.board.fen,
            "turn": get_turn_color(self.board),
            "your_color": self.user_color,
            "level": self.level,
            "users": self._users(),
            "captured": {"white": self.captured_white, "black": self.captured_black},
            "possible_moves": get_legal_moves_as_lists(self.board) if my_turn else [],
            "history": {},
            "has_started": True,
            "has_ended": False,
            "session_score": self.session,
            "eval": evaluate_position(self.board),
        })
        await self._persist()

    async def _send_move_event(self, result: dict, last_move: list[int]):
        now_turn = result["turn"]
        data = {
            "event": "move",
            "fen": result["fen"],
            "turn": now_turn,
            "pdn": {result["pdn"]: result["fen"]},
            "last_move": last_move,
            "captured": {"white": self.captured_white, "black": self.captured_black},
            "your_color": self.user_color,
            "eval": evaluate_position(self.board),
        }
        # Only the human can move; attach possible_moves when it's their turn.
        if now_turn == self.user_color and not result["game_over"]:
            data["possible_moves"] = get_legal_moves_as_lists(self.board)
        await self.send_json(data)
        await self._persist()

    async def _end(self, winner: int, reason: str):
        self.finished = True
        if winner == ColorChoices.white:
            self.session["white"] += 1
        elif winner == ColorChoices.black:
            self.session["black"] += 1
        else:
            self.session["draws"] += 1

        await self.send_json({
            "event": "game_over",
            "winner": winner,
            "reason": reason,
            "your_color": self.user_color,
            "session_score": self.session,
        })
        # Game's done — drop it from Redis rather than waiting for the TTL.
        if self.token:
            await delete_bot_game(self.redis, self.token)

    # ---------------------------------------------------------------- helpers
    def _add_capture(self, mover_color: int, result: dict):
        if not result["is_capture"]:
            return
        if mover_color == ColorChoices.white:
            self.captured_white += result["captured_count"]
        else:
            self.captured_black += result["captured_count"]

    def _users(self) -> list[dict]:
        user = self.scope.get("user")
        is_guest = self.scope.get("is_guest")
        if user is not None and not is_guest:
            username = getattr(user, "username", "Player")
        else:
            username = "Guest"

        human = {
            "id": getattr(user, "id", None) if not is_guest else None,
            "username": username,
            "rating": None,
            "avatar": None,
            "is_you": True,
            "color": self.user_color,
            "is_bot": False,
        }
        bot = {
            "id": None,
            "username": "Bot",
            "rating": None,
            "avatar": None,
            "is_you": False,
            "color": self.bot_color,
            "is_bot": True,
            "level": self.level,
        }
        return [human, bot]
