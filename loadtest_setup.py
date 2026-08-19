"""Pre-create N ready-to-play games (bypassing matchmaking) for the load test.

Writes loadtest_games.json = [{game_id, white, black}, ...].
Usage:  python loadtest_setup.py [N]
"""
import json
import os
import secrets
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
import django  # noqa: E402

django.setup()

from apps.game.models import (  # noqa: E402
    ConnectionHistory,
    Game,
    GameTypeChoices,
    GameTypesTime,
)
from shared.django import ColorChoices  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
gt = GameTypesTime.objects.get(pk=4)  # 5 min

games = []
for _ in range(N):
    wt, bt = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    wc = ConnectionHistory.objects.create(anonym_token=wt, status=1, rating=1200)
    bc = ConnectionHistory.objects.create(anonym_token=bt, status=1, rating=1200)
    g = Game.objects.create(
        type_of_game=gt,
        type=GameTypeChoices.MATCHMAKING,
        turn=ColorChoices.white.value,
        increment=gt.increment,
        initial_time_white=gt.time, initial_time_black=gt.time,
        remaining_time_white=gt.time, remaining_time_black=gt.time,
        white_anonym=wc, black_anonym=bc, created_by_anonym=wc,
    )
    games.append({"game_id": str(g.pk), "white": wt, "black": bt})

with open("loadtest_games.json", "w") as f:
    json.dump(games, f)
print(f"created {len(games)} games -> loadtest_games.json")
