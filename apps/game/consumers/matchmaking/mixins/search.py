"""Search mixin — handles matchmaking search, cancel, and queue management."""
import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.game.models import Game, GameTypeChoices, GameTypesTime, ConnectionHistory
from apps.game.models.handbook import ConnectionStatusChoices
from apps.game.services.matchmaking import find_opponent, add_to_queue
from shared.django import RATING_LEVELS

logger = logging.getLogger(__name__)

SEARCH_MATCH_TIMEOUT = getattr(settings, "SEARCH_MATCH_TIMEOUT", 300)


class SearchMixin:
    """Handles search/cancel flow, unfinished game checks, queue management."""

    async def handle_search(self, message: dict):
        """Process a search request from the client."""
        if self.searching:
            return await self.send_json({
                "event": "error",
                "message": _("Already searching for a game."),
            })

        # Validate game_type_id
        game_type_id = message.get("game_type_id")
        if not game_type_id:
            return await self.send_json({
                "event": "error",
                "message": _("game_type_id is required."),
            })

        try:
            self.game_type = await GameTypesTime.objects.aget(pk=game_type_id)
        except GameTypesTime.DoesNotExist:
            return await self.send_json({
                "event": "error",
                "message": _("Game type not found."),
            })

        self.game_mode = await self.get_game_mode(self.game_type)

        # Determine rating
        if self.is_guest:
            rating_level_raw = message.get("rating_level")
            try:
                rating_level = int(rating_level_raw)
            except (TypeError, ValueError):
                rating_level = None

            logger.debug("Guest search: rating_level=%s (raw=%s)", rating_level, rating_level_raw)

            if rating_level is None or rating_level not in RATING_LEVELS:
                logger.warning("Invalid rating_level=%s for guest", rating_level_raw)
                return await self.send_json({
                    "event": "error",
                    "message": _("Valid rating_level (1-4) is required for guests."),
                })
            rating = RATING_LEVELS[rating_level]

            # Update guest connection status
            if self.connection:
                self.connection.status = ConnectionStatusChoices.ONLINE
                self.connection.was_failed = True
                self.connection.rating = rating
                await self.connection.asave(
                    update_fields=("status", "was_failed", "rating"),
                )
        else:
            rating = await self.get_user_rating(self.user, self.game_mode)

        # Check for unfinished games
        has_unfinished = await self._check_unfinished_games()
        if has_unfinished:
            return

        # Delete leftover games where opponent never joined
        await self._delete_abandoned_games()

        # Get token for Redis key
        my_token = self.token if self.is_guest else await self.get_auth_token()

        # Search for opponent via Lua script
        opponent = await find_opponent(
            self.redis,
            game_type_id=game_type_id,
            my_token=my_token,
            my_rating=rating,
        )

        if opponent:
            await self.create_and_notify_game(
                opponent=opponent,
                game_type=self.game_type,
                my_token=my_token,
                my_rating=rating,
            )
        else:
            # No opponent — add to queue and wait
            self.searching = True
            await add_to_queue(
                self.redis,
                game_type_id=game_type_id,
                token=my_token,
                rating=rating,
                channel_name=self.channel_name,
            )

            # Schedule Celery timeout
            self.celery_task_id = await self._schedule_search_timeout(
                my_token, game_type_id,
            )

            await self.send_json({
                "event": "searching",
                "message": _("Looking for an opponent..."),
                "user": self._build_current_user_info(),
            })

    async def handle_cancel(self):
        """Cancel the current search."""
        if not self.searching:
            return await self.send_json({
                "event": "error",
                "message": _("Not currently searching."),
            })

        await self.cleanup_search()
        await self.send_json({
            "event": "cancelled",
            "message": _("Search cancelled."),
        })

    # ===================================================================
    # Helpers
    # ===================================================================

    async def _check_unfinished_games(self) -> bool:
        """Check if the player has unfinished games. Returns True if blocked."""
        if self.is_guest and self.connection:
            pk = self.connection.pk
            query = Game.objects.filter(
                Q(has_ended=False) & (
                    Q(black_anonym_id=pk) | Q(white_anonym_id=pk)
                ),
            )
        elif self.user:
            uid = self.user.id
            query = Game.objects.filter(
                Q(has_ended=False) & (Q(black_id=uid) | Q(white_id=uid)),
            )
        else:
            return False

        games = await sync_to_async(list)(query[:1])
        if games:
            game = games[0]
            response = {
                "event": "error",
                "message": _("You have unfinished games!"),
                "game_id": str(game.id),
                "game_type": game.type,
            }
            if game.type == GameTypeChoices.PRIVATE:
                response["private_key"] = game.private_key
            await self.send_json(response)
            return True

        return False

    async def _delete_abandoned_games(self):
        """Delete games where only one player joined (opponent never connected)."""
        if self.is_guest and self.connection:
            pk = self.connection.pk
            await Game.objects.filter(
                Q(has_ended=False)
                & (Q(black_anonym_id=pk) | Q(white_anonym_id=pk))
                & (
                    (Q(white__isnull=True) & Q(white_anonym__isnull=True))
                    | (Q(black__isnull=True) & Q(black_anonym__isnull=True))
                ),
            ).adelete()
        elif self.user:
            uid = self.user.id
            await Game.objects.filter(
                Q(has_ended=False)
                & (Q(black_id=uid) | Q(white_id=uid))
                & (
                    (Q(white__isnull=True) & Q(white_anonym__isnull=True))
                    | (Q(black__isnull=True) & Q(black_anonym__isnull=True))
                ),
            ).adelete()

    @sync_to_async
    def _schedule_search_timeout(self, token: str, game_type_id: int) -> str:
        """Schedule a Celery task to timeout the search."""
        from datetime import datetime, timedelta
        from apps.game.tasks import check_matchmaking_timeout

        task = check_matchmaking_timeout.apply_async(
            args=[token, game_type_id],
            eta=datetime.now() + timedelta(seconds=SEARCH_MATCH_TIMEOUT),
        )
        return task.id

    def _build_current_user_info(self) -> dict:
        """Build user info dict for the current player."""
        if self.is_guest:
            return {
                "username": "guest",
                "avatar": None,
                "rating": self.connection.rating if self.connection else 0,
                "country": None,
                "is_you": True,
            }

        return {
            "username": self.user.username,
            "avatar": self.user.avatar.url if self.user.avatar else None,
            "rating": self.get_user_rating_sync(self.user, self.game_mode),
            "country": None,
            "is_you": True,
        }
