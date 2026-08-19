"""
Board service — wrapper around py-draughts RussianBoard.

Provides a clean API for consumers to interact with the draughts engine.
Handles FEN format conversion and move validation.

py-draughts API notes:
- RussianBoard() — creates 8x8 Russian draughts board
- board.legal_moves — PROPERTY (not method!)
- board.turn — Color.WHITE (value=-1) or Color.BLACK (value=1)
- move.square_list — [from_sq, to_sq] (replaces old steps_move)
- str(move) — UCI notation ("21-17", "15x24")
- board.push(move) / board.pop() — apply/undo moves
- board.game_over — PROPERTY (not method!)
- board.fen — FEN string with numeric squares
"""
import logging
import re

from draughts import Color, RussianBoard

logger = logging.getLogger(__name__)

# PDN 1-indexed square → algebraic square name (matches the frontend getPosition
# map and V1 / live-site move notation, e.g. "21-17" → "a3-b4", "15x24" → "e5xg3").
_PDN_TO_ALG = {
    1: "b8", 2: "d8", 3: "f8", 4: "h8", 5: "a7", 6: "c7", 7: "e7", 8: "g7",
    9: "b6", 10: "d6", 11: "f6", 12: "h6", 13: "a5", 14: "c5", 15: "e5", 16: "g5",
    17: "b4", 18: "d4", 19: "f4", 20: "h4", 21: "a3", 22: "c3", 23: "e3", 24: "g3",
    25: "b2", 26: "d2", 27: "f2", 28: "h2", 29: "a1", 30: "c1", 31: "e1", 32: "g1",
}


def to_algebraic_pdn(pdn: str) -> str:
    """Convert numeric PDN to algebraic so move history reads like V1/live site."""
    return re.sub(r"\d+", lambda m: _PDN_TO_ALG.get(int(m.group()), m.group()), pdn)

# Map py-draughts Color to our ColorChoices values
COLOR_MAP = {
    Color.WHITE: 2,  # ColorChoices.WHITE
    Color.BLACK: 1,  # ColorChoices.BLACK
}

REVERSE_COLOR_MAP = {
    2: Color.WHITE,
    1: Color.BLACK,
}


def create_board(fen: str = "startpos") -> RussianBoard:
    """Create a RussianBoard from FEN or startpos."""
    if fen == "startpos":
        return RussianBoard()
    return RussianBoard.from_fen(fen)


def get_turn_color(board: RussianBoard) -> int:
    """Get current turn as ColorChoices value (1=black, 2=white)."""
    return COLOR_MAP[board.turn]


def get_legal_moves_as_lists(board: RussianBoard) -> list[list[int]]:
    """Get legal moves as 1-indexed square lists for frontend.

    py-draughts uses 0-indexed squares (0-31),
    PDN notation/frontend uses 1-indexed (1-32).
    """
    return [[sq + 1 for sq in move.square_list] for move in board.legal_moves]


def make_move(board: RussianBoard, square_list: list[int]) -> dict:
    """
    Validate and execute a move on the board.

    Args:
        board: Current board state.
        square_list: Move path as [from_sq, to_sq, ...].

    Returns:
        Dict with move info: pdn, is_capture, fen, game_over, winner.

    Raises:
        ValueError: If the move is not legal.
    """
    # Frontend sends 1-indexed (PDN), py-draughts uses 0-indexed → subtract 1
    internal_list = [sq - 1 for sq in square_list]

    # Find the matching legal move
    legal_moves = board.legal_moves
    target_move = None

    for move in legal_moves:
        if move.square_list == internal_list:
            target_move = move
            break

    if target_move is None:
        raise ValueError(
            f"Illegal move: {square_list} (internal: {internal_list}). "
            f"Legal moves: {[m.square_list for m in legal_moves]}"
        )

    # Check if it's a capture
    is_capture = len(target_move.captured_list) > 0
    pdn_str = to_algebraic_pdn(str(target_move))

    # Apply the move
    board.push(target_move)

    # Build result
    result = {
        "pdn": pdn_str,
        "is_capture": is_capture,
        "captured_count": len(target_move.captured_list),
        "fen": board.fen,
        "turn": get_turn_color(board),
        "game_over": board.game_over,
        "winner": None,
    }

    if board.game_over:
        result_str = board.result
        if result_str == "1-0":
            result["winner"] = 2  # White wins
        elif result_str == "0-1":
            result["winner"] = 1  # Black wins
        elif result_str == "1/2-1/2":
            result["winner"] = 0  # Draw

    return result


def is_game_over(board: RussianBoard) -> bool:
    """Check if the game is over."""
    return board.game_over


def get_winner(board: RussianBoard) -> int | None:
    """
    Get winner color as ColorChoices value.

    Returns:
        2 for white, 1 for black, 0 for draw, None if not over.
    """
    if not board.game_over:
        return None

    result_str = board.result
    if result_str == "1-0":
        return 2
    elif result_str == "0-1":
        return 1
    elif result_str == "1/2-1/2":
        return 0
    return None
