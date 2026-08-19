"""
Bot engine tests — legality, evaluation, and that stronger levels actually win.

Pure (no Django). The HARD level is not played to completion here (too slow for a
unit test); its search is exercised only for a legal opening move. Strength is
asserted with MEDIUM vs EASY, which is fast.
"""
import random

import pytest
from draughts import RussianBoard

from bot_ai.engine import EASY, HARD, MEDIUM, choose_move, evaluate


def _legal_square_lists(board):
    return [m.square_list for m in board.legal_moves]


def _is_legal(board, move_1indexed):
    return [sq - 1 for sq in move_1indexed] in _legal_square_lists(board)


@pytest.mark.parametrize("level", [EASY, MEDIUM, HARD])
def test_choose_move_returns_legal_from_startpos(level):
    move = choose_move("startpos", level=level, seed=1)
    assert move, "must return a move"
    assert _is_legal(RussianBoard(), move)


def test_forced_single_move_is_returned():
    fen = '[FEN "W:W:W22:B18"]'  # only legal move is 22x15
    move = choose_move(fen, level=HARD, seed=1)
    assert move == [22, 15]


def test_evaluate_startpos_is_symmetric():
    assert evaluate(RussianBoard()) == 0


def test_evaluate_rewards_material():
    # White has two men, black one → white should be clearly ahead.
    up = evaluate(RussianBoard.from_fen('[FEN "W:W:W22,23:B18"]'))
    assert up > 0
    # Mirror: black up material → negative.
    down = evaluate(RussianBoard.from_fen('[FEN "W:W:W22:B18,14"]'))
    assert down < 0


def test_king_worth_more_than_man():
    with_king = evaluate(RussianBoard.from_fen('[FEN "W:W:WK22:B18"]'))
    with_man = evaluate(RussianBoard.from_fen('[FEN "W:W:W22:B18"]'))
    assert with_king > with_man


def _play(white_level, black_level, seed, max_plies=160):
    from draughts import Color
    b = RussianBoard()
    s = seed
    for _ in range(max_plies):
        if b.game_over:
            break
        lvl = white_level if b.turn == Color.WHITE else black_level
        mv = choose_move(b.fen, level=lvl, seed=s)
        s += 1
        if not mv:
            break
        internal = [x - 1 for x in mv]
        target = next((m for m in b.legal_moves if m.square_list == internal), None)
        assert target is not None, f"engine returned illegal move {mv} at {b.fen}"
        b.push(target)
    return b.result if b.game_over else "timeout"


def test_medium_beats_easy_majority():
    """MEDIUM (depth 4) should beat EASY (depth 2 + blunders) more often than not."""
    medium_wins = 0
    decisive = 0
    for g in range(4):
        # MEDIUM as white
        r = _play(MEDIUM, EASY, seed=1000 + g * 30)
        if r in ("1-0", "0-1"):
            decisive += 1
            medium_wins += 1 if r == "1-0" else 0
        # MEDIUM as black
        r = _play(EASY, MEDIUM, seed=5000 + g * 30)
        if r in ("1-0", "0-1"):
            decisive += 1
            medium_wins += 1 if r == "0-1" else 0
    assert decisive >= 1, "expected at least one decisive game"
    assert medium_wins >= decisive / 2, f"MEDIUM won {medium_wins}/{decisive} decisive games"
