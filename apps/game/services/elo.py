"""
ELO rating service — fixed version.

Old bug (v1): black ELO was calculated as black_rating vs black_rating
instead of black_rating vs white_rating. This version fixes that.
"""
from django.conf import settings
from django.utils import timezone


def calculate_elo_rating(player_rating: int, opponent_rating: int, score: float, k: int = None) -> int:
    """
    Calculate new ELO rating.

    Args:
        player_rating: Current rating of the player.
        opponent_rating: Current rating of the opponent.
        score: 1.0 for win, 0.0 for loss, 0.5 for draw.
        k: K-factor (default from settings).

    Returns:
        New rating (rounded to int).
    """
    if k is None:
        k = settings.ELO_K_FACTOR

    expected = 1 / (1 + 10 ** ((opponent_rating - player_rating) / 400))
    new_rating = player_rating + k * (score - expected)
    return round(new_rating)


def update_ratings_after_game(game) -> dict:
    """
    Update both players' ELO ratings after a game ends.

    Returns dict with rating changes for both players.

    Only updates ratings for:
    - Matchmaking games (not private/tournament)
    - When both players are authorized (not anonymous)
    - When rating hasn't been calculated yet
    """
    from apps.game.models import GameTypeChoices

    if game.rating_calculated:
        return {}

    if game.type != GameTypeChoices.MATCHMAKING:
        return {}

    white_player = game.white
    black_player = game.black

    if not white_player or not black_player:
        return {}

    # Determine the game mode (bullet/blitz/rapid)
    mode = game.type_of_game.type.separate_var

    white_rating = getattr(white_player, f"{mode}_rating", 1600)
    black_rating = getattr(black_player, f"{mode}_rating", 1600)

    # Determine scores
    if game.color_win == 2:  # White wins
        white_score, black_score = 1.0, 0.0
    elif game.color_win == 1:  # Black wins
        white_score, black_score = 0.0, 1.0
    elif game.color_win == 0:  # Draw
        white_score, black_score = 0.5, 0.5
    else:
        return {}

    # Calculate new ratings — FIXED: uses opponent's rating correctly
    white_new = calculate_elo_rating(white_rating, black_rating, white_score)
    black_new = calculate_elo_rating(black_rating, white_rating, black_score)

    # Update players
    now = timezone.now()
    setattr(white_player, f"{mode}_rating", white_new)
    setattr(white_player, f"{mode}_updated_at", now)
    white_player.save(update_fields=[f"{mode}_rating", f"{mode}_updated_at"])

    setattr(black_player, f"{mode}_rating", black_new)
    setattr(black_player, f"{mode}_updated_at", now)
    black_player.save(update_fields=[f"{mode}_rating", f"{mode}_updated_at"])

    # Mark game as calculated
    game.rating_calculated = True
    game.save(update_fields=["rating_calculated"])

    return {
        "white": {"old": white_rating, "new": white_new, "diff": white_new - white_rating},
        "black": {"old": black_rating, "new": black_new, "diff": black_new - black_rating},
    }
