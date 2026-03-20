"""Game app URL configuration."""
from django.urls import path

from apps.game.views import (
    GameTypesView,
    LeaderboardView,
    ActiveGameView,
)

urlpatterns = [
    # Game type configs
    path("types/", GameTypesView.as_view(), name="game-types"),

    # Leaderboard
    path("leaderboard/", LeaderboardView.as_view(), name="leaderboard"),

    # Active game check
    path("active/", ActiveGameView.as_view(), name="active-game"),
]
