"""
Celery tasks for game timer enforcement.

check_first_move — cancels game if first player doesn't move within timeout.
check_move_timeout — ends game when a player's time runs out.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from config.celery import app

logger = logging.getLogger(__name__)

# Time limit for first move (in seconds)
FIRST_MOVE_TIMEOUT = 30


@app.task(name="game.check_first_move")
def check_first_move(game_id: str, color: int, queue: int):
    """
    Check if the player made their first move within the timeout.

    If not, cancel the game (no winner — color_win = cancelled).
    Runs after FIRST_MOVE_TIMEOUT seconds via apply_async(eta=...).
    """
    from apps.game.models import Game
    from shared.django import ColorChoices

    try:
        game = Game.objects.get(id=game_id)
    except (Game.DoesNotExist, ValueError):
        return

    # Check if first move was already made
    if queue == ColorChoices.white and game.first_color_first_move_done:
        return
    if queue == ColorChoices.black and game.second_color_first_move_done:
        return

    # Cancel the game
    game.has_ended = True
    game.all_players_left = True
    game.color_win = ColorChoices.cancelled
    game.finished_time = timezone.now()
    game.save(update_fields=(
        "has_ended", "all_players_left", "color_win", "finished_time",
    ))

    logger.info("Game %s cancelled — first move timeout (color=%d)", game_id, color)

    # Notify both players via channel layer
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        str(game_id),
        {
            "type": "game.message",
            "data": {
                "event": "game_over",
                "winner": None,
                "reason": "first_move_timeout",
                "message": "Game cancelled — first move not made in time",
            },
            "broadcast": True,
        },
    )


@app.task(name="game.check_move_timeout")
def check_move_timeout(game_id: str, last_pdn: str, last_fen: str, history_len: int, current_turn: int):
    """
    Check if the current player's time has run out.

    Compares current game state (last move, fen, history length)
    with the state when the task was scheduled. If they match,
    the player hasn't moved and loses on time.
    """
    import json

    from apps.game.models import Game
    from shared.django import ColorChoices

    try:
        game = Game.objects.select_related(
            "white", "black", "type_of_game", "type_of_game__type",
        ).get(id=game_id)
    except (Game.DoesNotExist, ValueError):
        return

    if game.has_ended:
        return

    # Verify game state hasn't changed since task was scheduled
    history = json.loads(game.history) if game.history else {}
    if len(history) != history_len:
        return  # Player made a move — task is stale

    # Check last move matches
    if history:
        last_entry = list(history.values())[-1]
        last_moves = list(last_entry.keys())
        last_fens = list(last_entry.values())

        state_matches = False
        if len(last_moves) >= 1 and last_moves[-1] == last_pdn and last_fens[-1] == last_fen:
            state_matches = True

        if not state_matches:
            return  # State changed — stale task

    # Time expired — declare winner
    turn_is_white = current_turn == ColorChoices.white
    game.has_ended = True

    if turn_is_white:
        game.color_win = ColorChoices.black
        game.remaining_time_white = 0
    else:
        game.color_win = ColorChoices.white
        game.remaining_time_black = 0

    game.finished_time = timezone.now()

    # Calculate ratings
    mode = game.type_of_game.type.separate_var if game.type_of_game else "blitz"
    rating_data = _calculate_timeout_ratings(game, mode)

    game.rating_calculated = True
    game.save(update_fields=(
        "has_ended", "color_win", "finished_time",
        "remaining_time_white", "remaining_time_black",
        "rating_calculated",
    ))

    logger.info(
        "Game %s ended — timeout (turn=%d, winner=%d)",
        game_id, current_turn, game.color_win,
    )

    # Notify players
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        str(game_id),
        {
            "type": "game.over",
            "data": {
                "event": "game_over",
                "winner": game.color_win,
                "reason": "timeout",
                "rating": rating_data,
            },
        },
    )


def _calculate_timeout_ratings(game, mode: str) -> dict:
    """Calculate and apply ELO ratings for a timeout win."""
    from apps.game.services.elo import calculate_elo_rating

    white = game.white
    black = game.black

    if not white or not black:
        return {}

    white_rating = white.get_rating_for_mode(mode)
    black_rating = black.get_rating_for_mode(mode)

    if game.color_win == 1:  # Black wins
        white_new = calculate_elo_rating(white_rating, black_rating, 0)
        black_new = calculate_elo_rating(black_rating, white_rating, 1)
    else:  # White wins
        white_new = calculate_elo_rating(white_rating, black_rating, 1)
        black_new = calculate_elo_rating(black_rating, white_rating, 0)

    # Save new ratings
    setattr(white, f"{mode}_rating", white_new)
    white.save(update_fields=[f"{mode}_rating"])
    setattr(black, f"{mode}_rating", black_new)
    black.save(update_fields=[f"{mode}_rating"])

    return {
        "white": {"old": white_rating, "new": white_new, "diff": white_new - white_rating},
        "black": {"old": black_rating, "new": black_new, "diff": black_new - black_rating},
    }
