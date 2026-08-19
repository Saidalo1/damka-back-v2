"""
Bot engine — custom alpha-beta search for Russian draughts (framework-agnostic).

WHY CUSTOM (not py-draughts' built-in AlphaBetaEngine):
    py-draughts' `AlphaBetaEngine` evaluator is hardcoded for international 10x10
    (50 squares) and raises IndexError on the 8x8 RussianBoard (verified on 1.6.4
    and 1.9.0). No free, Linux-native, strong Russian-8x8 engine exists
    (KestoG/Kallisto/Aurora = Windows CheckerBoard DLLs, unclear licensing;
    Scan/Hub = 10x10 only). So a tuned custom alpha-beta is the correct choice.

STRENGTH FEATURES (per engine research):
    - Negamax + alpha-beta with alpha/beta threaded through the recursion.
    - Iterative deepening with a per-move time budget.
    - Quiescence: never evaluate mid forced-capture sequence (kills horizon-effect
      blunders — the #1 reason draughts bots hang pieces).
    - Transposition table keyed by a bitboard tuple (pieces + side to move) with
      EXACT/LOWER/UPPER flags — big effective-depth gain.
    - Move ordering: TT best-move first, then multi-captures, then killer/history.
    - copy-make search (see `_child`): py-draughts' pop() corrupts state in deep
      recursion, so we copy the board per move instead of push/pop.
    - Evaluation: material + man advancement/centre + king centralisation +
      back-rank + side-to-move mobility.

DEPLOYMENT (critical):
    CPU-bound — MUST run OFF the async event loop (ProcessPoolExecutor via
    apps/game/services/bot_runner.py, or a Celery worker). `choose_move` is a pure
    sync function (str/int args) so it drops into either.

UPGRADE PATH (if "hard" must be stronger): killer/history move ordering, aspiration
    windows + LMR, endgame tablebases, or a Cython/Rust hot loop (~100x nodes/s);
    ultimately an AlphaZero-style NN (py-draughts exposes to_tensor/features).
"""
from __future__ import annotations

import copy
import logging
import random
import re
import time
from dataclasses import dataclass

from draughts import Color, RussianBoard

logger = logging.getLogger(__name__)


def _child(board: RussianBoard, move) -> RussianBoard:
    """Return a NEW board with `move` applied — copy-make, never push/pop.

    py-draughts' `pop()` does NOT reliably restore board state through nested
    recursion (it desyncs the position on captures/promotions ~5 plies deep),
    which silently corrupts any deep alpha-beta search built on push/pop. Its
    `push()` IS correct (pure bitboard update), and a board is just 4 ints + a
    couple of scalars, so copying then pushing once is both correct and cheap
    (~4M copies/s). This is the standard "copy-make" search technique.
    """
    nb = copy.copy(board)                       # shallow-copies the __slots__ ints/enums
    nb._moves_stack = board._moves_stack.copy()  # own stack so push() can't touch the parent
    nb.push(move)
    return nb

# --- Difficulty levels (map to design: Oson / O'rta / Qiyin) -----------------
EASY = 1
MEDIUM = 2
HARD = 3

# level -> (max search depth, time budget seconds, blunder probability)
# Depth caps iterative deepening; the time budget usually decides how deep HARD
# actually reaches. blunder_prob makes EASY/MEDIUM beatable for beginners.
LEVEL_CONFIG: dict[int, tuple[int, float, float]] = {
    EASY: (2, 0.15, 0.35),
    MEDIUM: (6, 0.70, 0.03),
    HARD: (10, 2.00, 0.00),
}

# --- Evaluation weights (white-positive, centipawns) -------------------------
MAN_VALUE = 100
KING_VALUE = 300          # flying king is strong in Russian draughts
ADVANCE_WEIGHT = 5        # per row of advancement toward promotion (men)
CENTRE_WEIGHT = 2         # central-square control (men)
KING_CENTRE_WEIGHT = 5    # king centralisation (more diagonals = more reach)
BACK_RANK_BONUS = 8       # holding own back rank (anti-promotion defense)
MOBILITY_WEIGHT = 2       # per legal move for the side to move
WIN_SCORE = 1_000_000
INF = WIN_SCORE * 2

# TT entry flags
_EXACT, _LOWER, _UPPER = 0, 1, 2

# 1-indexed square (1..32) → algebraic name (py-draughts russian numbering).
_ALG = {
    1: "b8", 2: "d8", 3: "f8", 4: "h8", 5: "a7", 6: "c7", 7: "e7", 8: "g7",
    9: "b6", 10: "d6", 11: "f6", 12: "h6", 13: "a5", 14: "c5", 15: "e5", 16: "g5",
    17: "b4", 18: "d4", 19: "f4", 20: "h4", 21: "a3", 22: "c3", 23: "e3", 24: "g3",
    25: "b2", 26: "d2", 27: "f2", 28: "h2", 29: "a1", 30: "c1", 31: "e1", 32: "g1",
}
_SQ_COL = {sq: ord(a[0]) - 97 for sq, a in _ALG.items()}  # 0..7
_FEN_RE = re.compile(r'"(.*)"')


def _row_of(square: int) -> int:
    """Numbering-row 1..8 (squares 1..4 -> 1, 29..32 -> 8). White promotes on 1."""
    return (square - 1) // 4 + 1


def _centrality(square: int) -> int:
    """0 (edge/corner) .. 6 (dead centre) — symmetric, fine for both colours."""
    r = _row_of(square)
    c = _SQ_COL[square]
    return min(r - 1, 8 - r) + min(c, 7 - c)


def _bits(bb: int):
    """Yield 0-indexed set-bit positions of a bitboard (square = index + 1)."""
    while bb:
        lsb = bb & -bb
        yield lsb.bit_length() - 1
        bb ^= lsb


# Precomputed per-square (0-indexed) positional tables — built once at import so
# the hot eval loop is pure table lookups over bitboards (no FEN string parsing).
_MAN_W = [0] * 32
_MAN_B = [0] * 32
_KING_PST = [0] * 32
for _i in range(32):
    _sq = _i + 1
    _r = _row_of(_sq)
    _cen = _centrality(_sq)
    _MAN_W[_i] = (8 - _r) * ADVANCE_WEIGHT + _cen * CENTRE_WEIGHT + (BACK_RANK_BONUS if _r == 8 else 0)
    _MAN_B[_i] = (_r - 1) * ADVANCE_WEIGHT + _cen * CENTRE_WEIGHT + (BACK_RANK_BONUS if _r == 1 else 0)
    _KING_PST[_i] = _cen * KING_CENTRE_WEIGHT


@dataclass
class _Position:
    white_men: list[int]
    white_kings: list[int]
    black_men: list[int]
    black_kings: list[int]


def _parse_positions(fen: str) -> _Position:
    """Parse a RussianBoard FEN into piece square lists (1-indexed)."""
    inner = fen
    m = _FEN_RE.search(fen)
    if m:
        inner = m.group(1)
    parts = inner.split(":")
    white_seg = next((p for p in parts if p.startswith("W") and len(p) > 1), "")
    black_seg = next((p for p in reversed(parts) if p.startswith("B") and len(p) > 1), "")

    def split_seg(seg: str) -> tuple[list[int], list[int]]:
        men: list[int] = []
        kings: list[int] = []
        for tok in seg[1:].split(","):
            if not tok:
                continue
            if tok.startswith("K"):
                kings.append(int(tok[1:]))
            else:
                men.append(int(tok))
        return men, kings

    wm, wk = split_seg(white_seg)
    bm, bk = split_seg(black_seg)
    return _Position(wm, wk, bm, bk)


def evaluate(board: RussianBoard) -> int:
    """
    Static evaluation from WHITE's perspective (white-positive).

    Reads py-draughts BITBOARDS (int masks over 32 squares; bit i = square i+1)
    directly — ~60x faster than parsing board.fen, so the search reaches far
    deeper in the same time budget (better tactics/endgame at no extra think-time).
    """
    wm = board.white_men
    wk = board.white_kings
    bm = board.black_men
    bk = board.black_kings

    score = (wm.bit_count() - bm.bit_count()) * MAN_VALUE
    score += (wk.bit_count() - bk.bit_count()) * KING_VALUE

    for i in _bits(wm):
        score += _MAN_W[i]
    for i in _bits(bm):
        score -= _MAN_B[i]
    for i in _bits(wk):
        score += _KING_PST[i]
    for i in _bits(bk):
        score -= _KING_PST[i]

    return score


def _terminal_score(board: RussianBoard, ply: int) -> int:
    """Finished-game score from white's perspective (prefer faster wins)."""
    result = board.result
    if result == "1-0":
        return WIN_SCORE - ply
    if result == "0-1":
        return -(WIN_SCORE - ply)
    return 0  # draw


def evaluate_position(board: RussianBoard) -> int:
    """White-perspective evaluation (centipawns) for the live eval bar.

    Runs a depth-0 quiescence search so forced captures are resolved first — the
    bar won't jump mid-combination the way a raw static eval would. Cheap enough
    to call inline after each move (forced-capture chains are short in draughts).
    Positive = White is better; ±WIN_SCORE means a forced win is seen.
    """
    if board.game_over:
        return _terminal_score(board, 0)
    stm = 1 if board.turn == Color.WHITE else -1
    far = time.monotonic() + 5.0
    q = _negamax(board, 0, -INF, INF, stm, 0, far, {}, {}, {})
    return stm * q  # side-to-move score → white's perspective


def analyze_fen(fen: str, depth: int) -> int:
    """White-perspective centipawn eval from a FIXED-depth negamax search.

    Unlike `evaluate_position` (depth-0 quiescence, material-ish), this searches
    `depth` plies so real combinations are seen — this is what the live eval bar
    should show. Called repeatedly with increasing depth to stream a deepening
    eval (the "bar plays back and forth" effect from chess.com / lichess).
    """
    board = RussianBoard() if fen == "startpos" else RussianBoard.from_fen(fen)
    if board.game_over:
        return _terminal_score(board, 0)
    color = 1 if board.turn == Color.WHITE else -1
    far = time.monotonic() + 30.0  # depth-bounded; deadline is just a safety net
    tt: dict = {}
    killers: dict = {}
    history: dict = {}
    alpha, best = -INF, -INF
    for mv in sorted(board.legal_moves, key=lambda m: -len(m.captured_list)):
        v = -_negamax(_child(board, mv), depth - 1, -INF, -alpha, -color, 1,
                      far, tt, killers, history)
        if v > best:
            best = v
        if v > alpha:
            alpha = v
    return color * best  # side-to-move best → white's perspective


def _order(moves: list, tt_move, killer1, killer2, history: dict) -> list:
    """Move ordering (better ordering → more cutoffs → deeper search, same time):
    TT best-move → captures (most first) → killer moves → history-heuristic score.
    """
    def rank(mv):
        sl = mv.square_list
        if sl == tt_move:
            return (0, 0)
        caps = len(mv.captured_list)
        if caps:
            return (1, -caps)
        if sl == killer1 or sl == killer2:
            return (2, 0)
        return (3, -history.get((sl[0], sl[-1]), 0))
    return sorted(moves, key=rank)


def _negamax(board: RussianBoard, depth: int, alpha: int, beta: int,
             color: int, ply: int, deadline: float, tt: dict,
             killers: dict, history: dict) -> int:
    """Negamax + alpha-beta + transposition table + quiescence + killers/history."""
    if board.game_over:
        return color * _terminal_score(board, ply)

    use_tt = depth >= 1
    key = None
    tt_move = None
    if use_tt:
        # Fast, unique position key from bitboards + side to move (no FEN string).
        key = (board.white_men, board.white_kings, board.black_men,
               board.black_kings, board.turn.value)
        entry = tt.get(key)
        if entry is not None:
            e_depth, e_val, e_flag, e_move = entry
            if e_depth >= depth:
                if e_flag == _EXACT:
                    return e_val
                if e_flag == _LOWER and e_val > alpha:
                    alpha = e_val
                elif e_flag == _UPPER and e_val < beta:
                    beta = e_val
                if alpha >= beta:
                    return e_val
            tt_move = e_move

    moves = board.legal_moves
    forced_capture = bool(moves) and len(moves[0].captured_list) > 0

    # Leaf: quiescence — keep searching while captures are forced (no horizon effect).
    if depth <= 0:
        if not forced_capture or time.monotonic() >= deadline:
            return color * evaluate(board) + len(moves) * MOBILITY_WEIGHT
    elif time.monotonic() >= deadline:
        return color * evaluate(board) + len(moves) * MOBILITY_WEIGHT

    alpha_orig = alpha
    best = -INF
    best_move_sq = None
    kill = killers.get(ply)
    k1, k2 = (kill[0], kill[1]) if kill else (None, None)
    for move in _order(moves, tt_move, k1, k2, history):
        val = -_negamax(_child(board, move), depth - 1, -beta, -alpha, -color,
                        ply + 1, deadline, tt, killers, history)
        if val > best:
            best = val
            best_move_sq = move.square_list
        if best > alpha:
            alpha = best
        if alpha >= beta:
            # Beta-cutoff: reward this move so siblings/parents try it first next
            # time. Only quiet moves (captures are already ordered ahead).
            if not move.captured_list:
                sl = move.square_list
                if kill is None:
                    killers[ply] = [sl, None]
                elif kill[0] != sl:
                    kill[1] = kill[0]
                    kill[0] = sl
                edge = (sl[0], sl[-1])
                history[edge] = history.get(edge, 0) + depth * depth
            break  # cutoff

    if use_tt and best_move_sq is not None:
        if best <= alpha_orig:
            flag = _UPPER
        elif best >= beta:
            flag = _LOWER
        else:
            flag = _EXACT
        tt[key] = (depth, best, flag, best_move_sq)
    return best


def choose_move(fen: str, level: int = MEDIUM, *, seed: int | None = None) -> list[int]:
    """
    Choose the bot's move.

    Args:
        fen: RussianBoard FEN, or "startpos".
        level: EASY / MEDIUM / HARD.
        seed: optional RNG seed (blunder/tie-break reproducibility).

    Returns:
        The move as a 1-indexed square list [from, ..., to] (empty if no move).
    """
    board = RussianBoard() if fen == "startpos" else RussianBoard.from_fen(fen)
    moves = board.legal_moves
    if not moves:
        return []
    if len(moves) == 1:
        return [sq + 1 for sq in moves[0].square_list]

    depth, budget, blunder_prob = LEVEL_CONFIG.get(level, LEVEL_CONFIG[MEDIUM])
    rng = random.Random(seed)

    # Beginner mercy: occasionally play a random legal move.
    if blunder_prob and rng.random() < blunder_prob:
        chosen = rng.choice(moves)
        return [sq + 1 for sq in chosen.square_list]

    color = 1 if board.turn == Color.WHITE else -1
    deadline = time.monotonic() + budget
    tt: dict = {}
    killers: dict = {}
    history: dict = {}

    best_move = ordered_root = sorted(moves, key=lambda mv: -len(mv.captured_list))[0]
    ordered = sorted(moves, key=lambda mv: -len(mv.captured_list))
    for d in range(1, depth + 1):
        alpha, beta = -INF, INF
        local_best = None
        local_best_val = -INF
        scored: list[tuple[int, object]] = []
        completed = True
        for move in ordered:
            # Only START a root move if there's budget left. This guarantees we
            # never commit a move chosen from a HALF-searched iteration (whose
            # scores are static-eval garbage once the deadline is crossed) — the
            # bug that made the bot play near-randomly at high depth caps.
            if time.monotonic() >= deadline:
                completed = False
                break
            val = -_negamax(_child(board, move), d - 1, -beta, -alpha, -color, 1,
                            deadline, tt, killers, history)
            scored.append((val, move))
            if val > local_best_val:
                local_best_val, local_best = val, move
            if val > alpha:
                alpha = val

        if not completed or local_best is None:
            break  # out of time mid-iteration → keep the last completed depth's move

        best_move = local_best
        # Re-order by this depth's scores so the next iteration prunes better.
        ordered = [mv for _, mv in sorted(scored, key=lambda t: -t[0])]
        if abs(local_best_val) >= WIN_SCORE - 1000:
            break  # forced win/loss found

    return [sq + 1 for sq in best_move.square_list]
