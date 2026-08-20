"""
Game REST API views — game types, leaderboard, active game check.

Endpoints:
- GET  /api/game/types/        — list game types with time controls
- GET  /api/game/leaderboard/  — player ratings leaderboard
- GET  /api/game/active/       — check if user has active game
"""
import logging

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils.timezone import now
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.game.models import Game
from apps.game.models.handbook import GameTypes, ConnectionHistory
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
        game_types = GameTypes.objects.prefetch_related(
            "time_controls",
        ).order_by("title")
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
        updated_field = f"{mode}_updated_at"

        # Get all users ordered by rating (matching v1 SQL ordering)
        users = User.objects.filter(
            is_active=True, is_staff=False,
        ).order_by(
            f"-{rating_field}", f"-{updated_field}", "date_joined", "-last_login",
        ).values(
            "id", "username", "avatar", rating_field,
            "country__id", "country__title", "country__code",
        )

        paginator = Paginator(users, per_page)
        page = paginator.get_page(page_num)

        # Build leaderboard entries with place numbers
        start_place = (page_num - 1) * per_page + 1
        results = []
        current_user = request.user

        for i, entry in enumerate(page):
            code = entry.get("country__code", "")
            province = {
                "id": entry.get("country__id"),
                "title": entry.get("country__title", ""),
                "code": code,
                "flag": settings.STATIC_URL + f"flag/{code.lower()}.gif" if code else "",
            }

            # Build avatar URL (manifestation)
            avatar = entry.get("avatar")
            manifestation = None
            if avatar and avatar != "":
                manifestation = settings.MEDIA_URL + avatar

            is_current_user = (
                current_user.is_authenticated and entry["id"] == current_user.id
            )

            results.append({
                "id": entry["id"],
                "username": entry["username"],
                "manifestation": manifestation,
                "rating": entry[rating_field],
                "place": start_place + i,
                "province": province,
                "is_you": is_current_user,
            })

        # Top 3 players (separate query, matching v1)
        top_three_qs = User.objects.filter(
            is_active=True, is_staff=False,
        ).order_by(
            f"-{rating_field}", f"-{updated_field}", "date_joined", "-last_login",
        ).values(
            "id", "username", "avatar", rating_field,
            "country__id", "country__title", "country__code",
        )[:3]

        first_three_players = []
        for i, entry in enumerate(top_three_qs):
            code = entry.get("country__code", "")
            avatar = entry.get("avatar")
            first_three_players.append({
                "id": entry["id"],
                "username": entry["username"],
                "manifestation": settings.MEDIA_URL + avatar if avatar and avatar != "" else None,
                "rating": entry[rating_field],
                "place": i + 1,
                "province": {
                    "id": entry.get("country__id"),
                    "title": entry.get("country__title", ""),
                    "code": code,
                    "flag": settings.STATIC_URL + f"flag/{code.lower()}.gif" if code else "",
                },
                "is_you": current_user.is_authenticated and entry["id"] == current_user.id,
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

            user_avatar = current_user.avatar.name if current_user.avatar else None
            current_user_data = {
                "id": current_user.id,
                "username": current_user.username,
                "manifestation": settings.MEDIA_URL + user_avatar if user_avatar and user_avatar != "" else None,
                "rating": user_rating,
                "place": user_rank,
                "is_you": True,
            }

        return Response({
            "results": results,
            "first_three_players": first_three_players,
            "current_user_rating": current_user_data,
            "count": paginator.count,
            "total_pages": paginator.num_pages,
            "todays_games_count": todays_games,
            "current_games_count": active_games,
        })


class ActiveGameView(APIView):
    """Check if the current user has an active (unfinished) game.

    Works for BOTH registered users (DRF token → request.user) and guests
    (43-char anonym_token → ConnectionHistory). AllowAny is deliberate: guests
    play matchmaking too, so requiring auth here 401'd on every guest navigation
    (the frontend check-active-game middleware runs site-wide). The old code even
    had a guest branch, but it was unreachable behind IsAuthenticated and keyed
    on user.pk (None for a guest) instead of the guest's connection id.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user

        if user.is_authenticated:
            active = Game.objects.filter(
                Q(white_id=user.pk) | Q(black_id=user.pk),
                has_ended=False,
            ).first()
        else:
            conn = self._guest_connection(request)
            if conn is None:
                return Response({"status": "none", "message": "No active games"})
            active = Game.objects.filter(
                Q(white_anonym_id=conn.id) | Q(black_anonym_id=conn.id),
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

    @staticmethod
    def _guest_connection(request):
        """Resolve a guest's ConnectionHistory from the Authorization header.

        REST sends "Authorization: Token <token>"; for a guest that token is the
        anonym_token (token_urlsafe(32) → 43 chars, see ws_auth.is_anonym_token).
        """
        raw = request.META.get("HTTP_AUTHORIZATION", "")
        parts = raw.split()
        token = parts[1] if len(parts) == 2 else (parts[0] if parts else "")
        if not token or len(token) < 43:
            return None
        return ConnectionHistory.objects.filter(anonym_token=token).first()
