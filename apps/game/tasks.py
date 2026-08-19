"""
Celery tasks for game timer enforcement and matchmaking.

check_first_move — cancels game if first player doesn't move within timeout.
check_move_timeout — ends game when a player's time runs out.
check_matchmaking_timeout — removes player from queue after timeout.
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

    white_rating = getattr(white, f"{mode}_rating", 1600)
    black_rating = getattr(black, f"{mode}_rating", 1600)

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


@app.task(name="game.check_abandonment")
def check_abandonment(game_id: str, disconnected_color: int):
    """Decide a game after a player disconnected and the grace elapsed.

    Scheduled ~ABANDON_GRACE seconds after a player drops. Three outcomes:
      * that player is back online  → do nothing (blip recovered);
      * BOTH players still gone     → abort, no rating change;
      * only they are still gone    → they forfeit, opponent wins (rated).
    """
    import redis as sync_redis
    from django.conf import settings as django_settings

    from apps.game.models import Game
    from shared.django import ColorChoices

    redis_url = getattr(django_settings, "REDIS_URL", "redis://localhost:6379/0")
    redis_conn = sync_redis.from_url(redis_url, decode_responses=True)
    online = redis_conn.smembers(f"game_online:{game_id}") or set()

    if str(disconnected_color) in online:
        return  # they reconnected within the grace — nothing to do

    try:
        game = Game.objects.select_related(
            "white", "black", "type_of_game", "type_of_game__type",
        ).get(id=game_id)
    except (Game.DoesNotExist, ValueError):
        return
    if game.has_ended:
        return

    channel_layer = get_channel_layer()

    if not online:
        # Both players gone → abort, no rating.
        game.has_ended = True
        game.all_players_left = True
        game.color_win = ColorChoices.cancelled
        game.finished_time = timezone.now()
        game.save(update_fields=(
            "has_ended", "all_players_left", "color_win", "finished_time",
        ))
        if game.move_check_task_id:
            app.control.revoke(str(game.move_check_task_id), terminate=True)
        logger.info("Game %s aborted — both players left", game_id)
        async_to_sync(channel_layer.group_send)(
            str(game_id),
            {"type": "game.message",
             "data": {"event": "game_over", "winner": None, "reason": "aborted",
                      "message": "Game aborted — both players left"},
             "broadcast": True},
        )
        return

    # Opponent is present, the dropped player never came back → they forfeit.
    winner = (ColorChoices.white if disconnected_color == ColorChoices.black
              else ColorChoices.black)
    game.has_ended = True
    game.color_win = winner
    game.finished_time = timezone.now()
    mode = game.type_of_game.type.separate_var if game.type_of_game else "blitz"
    rating_data = _calculate_timeout_ratings(game, mode)
    game.rating_calculated = True
    game.save(update_fields=(
        "has_ended", "color_win", "finished_time", "rating_calculated",
    ))
    if game.move_check_task_id:
        app.control.revoke(str(game.move_check_task_id), terminate=True)
    logger.info("Game %s — player %d abandoned, %d wins", game_id, disconnected_color, winner)
    async_to_sync(channel_layer.group_send)(
        str(game_id),
        {"type": "game.over",
         "data": {"event": "game_over", "winner": winner, "reason": "abandoned",
                  "rating": rating_data}},
    )


@app.task(name="game.check_matchmaking_timeout")
def check_matchmaking_timeout(token: str, game_type_id: int):
    """
    Remove player from matchmaking queue after timeout.

    Called via apply_async(eta=...) when a player starts searching.
    If the player is still in the queue, removes them and sends a timeout event.
    """
    import redis as sync_redis
    from django.conf import settings as django_settings

    redis_url = getattr(django_settings, "REDIS_URL", "redis://localhost:6379/0")
    redis_conn = sync_redis.from_url(redis_url, decode_responses=True)

    dkey = f"mm:d:{game_type_id}:{token}"
    data = redis_conn.get(dkey)

    if data is None:
        return  # Player already matched or cancelled

    import json
    player_data = json.loads(data)
    channel_name = player_data.get("channel_name")

    # Remove from queue (ZSET member + payload)
    redis_conn.zrem(f"mm:z:{game_type_id}", token)
    redis_conn.delete(dkey)

    logger.info("Matchmaking timeout for token=%s, game_type=%d", token[:10], game_type_id)

    # Notify player via channel layer
    if channel_name:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.send)(channel_name, {
            "type": "matchmaking.timeout",
            "data": {
                "event": "timeout",
                "message": "No opponent found. Try again.",
            },
        })

