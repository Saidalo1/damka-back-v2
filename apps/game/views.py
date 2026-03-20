"""
Game REST API views — game types, leaderboard, active game check.

Endpoints:
- GET  /api/game/types/        — list game types with time controls
- GET  /api/game/leaderboard/  — player ratings leaderboard
- GET  /api/game/active/       — check if user has active game
"""
import logging

from django.core.paginator import Paginator
from django.db.models import Q
from django.utils.timezone import now
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.game.models import Game
from apps.game.models.handbook import GameTypes
from apps.game.serializers import (
    GameTypesSerializer,
    ActiveGameSerializer,
)
from apps.users.models import User

logger = logging.getLogger(__name__)


class GameTypesView(APIView):
    """List all game types with their time control options."""
    permission_classes = [AllowAny]

    def get(self, request):
        game_types = GameTypes.objects.prefetch_related("times").all()
        return Response(GameTypesSerializer(game_types, many=True).data)


class LeaderboardView(APIView):
    """
    Player ratings leaderboard with pagination.

    Query params:
    - mode: bullet|blitz|rapid (default: blitz)
    - page: page number (default: 1)
    - per_page: items per page (default: 20, max: 50)
    """
    permission_classes = [AllowAny]

    def get(self, request):
        mode = request.query_params.get("mode", "blitz").lower()
        if mode not in ("bullet", "blitz", "rapid"):
            return Response({"error": "Invalid mode"}, status=400)

        page_num = int(request.query_params.get("page", 1))
        per_page = min(int(request.query_params.get("per_page", 20)), 50)

        rating_field = f"{mode}_rating"

        # Get all users ordered by rating
        users = User.objects.filter(
            is_active=True, is_staff=False,
        ).order_by(f"-{rating_field}", "username").values(
            "id", "username", rating_field,
            "country__title", "country__code", "country__flag",
        )

        paginator = Paginator(users, per_page)
        page = paginator.get_page(page_num)

        # Build leaderboard entries with place numbers
        start_place = (page_num - 1) * per_page + 1
        ratings = []
        current_user = request.user

        for i, entry in enumerate(page):
            country = None
            if entry.get("country__title"):
                country = {
                    "title": entry["country__title"],
                    "code": entry.get("country__code", ""),
                    "flag": entry.get("country__flag", ""),
                }

            is_current_user = (
                current_user.is_authenticated and entry["id"] == current_user.id
            )

            ratings.append({
                "id": entry["id"],
                "username": entry["username"],
                "rating": entry[rating_field],
                "place": start_place + i,
                "country": country,
                "is_you": is_current_user,
            })

        # Stats
        today = now().date()
        todays_games = Game.objects.filter(created_at__date=today).count()
        active_games = Game.objects.filter(has_ended=False).count()

        # Current user's rating and rank
        current_user_data = None
        if current_user.is_authenticated:
            user_rating = getattr(current_user, rating_field, 1600)
            user_rank = User.objects.filter(
                is_active=True, is_staff=False,
                **{f"{rating_field}__gt": user_rating},
            ).count() + 1

            current_user_data = {
                "id": current_user.id,
                "username": current_user.username,
                "rating": user_rating,
                "place": user_rank,
            }

        return Response({
            "ratings": ratings,
            "current_user_rating": current_user_data,
            "total_players_count": paginator.count,
            "todays_games_count": todays_games,
            "active_games_count": active_games,
            "current_page": page_num,
            "total_pages": paginator.num_pages,
        })


class ActiveGameView(APIView):
    """Check if the current user has an active (unfinished) game."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_id = user.pk

        if user.is_authenticated:
            active = Game.objects.filter(
                Q(white_id=user_id) | Q(black_id=user_id),
                has_ended=False,
            ).first()
        else:
            active = Game.objects.filter(
                Q(white_anonym_id=user_id) | Q(black_anonym_id=user_id),
                has_ended=False,
            ).first()

        if active:
            return Response({
                "status": "exists",
                "message": "You have unfinished games!",
                "game": ActiveGameSerializer(active).data,
            })

        return Response({
            "status": "none",
            "message": "No active games",
        })
