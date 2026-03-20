"""
Game model — the core model for a draughts match.

V2 improvements over v1:
- TextField for history (PostgreSQL jsonb sorts keys alphabetically)
- Cleaner field naming and help_text
- Removed redundant authorized_winner/guest_winner FKs — color_win + player FKs is enough
- get_remaining_times property for time calculation
- DB constraints from v1 preserved
"""
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from mptt.models import MPTTModel, TreeForeignKey

from shared.django import ColorChoices


class GameTypeChoices(models.IntegerChoices):
    """How the game was created."""
    MATCHMAKING = 0, "Matchmaking"
    PRIVATE = 1, "Private"
    TOURNAMENT = 2, "Tournament"


class Game(MPTTModel):
    """
    A single draughts game between two players.

    Uses MPTT tree for rematch chains: each rematch creates a child
    node of the original game, enabling session score tracking.
    """
    # === Primary Key ===
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # === Players (Authorized) ===
    white = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="games_as_white",
    )
    black = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="games_as_black",
    )

    # === Players (Anonymous) ===
    white_anonym = models.ForeignKey(
        "ConnectionHistory",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="games_as_white",
    )
    black_anonym = models.ForeignKey(
        "ConnectionHistory",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="games_as_black",
    )

    # === Game Creator ===
    created_by_authorized = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="created_games",
    )
    created_by_anonym = models.ForeignKey(
        "ConnectionHistory",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="created_games",
    )

    # === Game Type and Time Control ===
    type = models.PositiveIntegerField(choices=GameTypeChoices.choices)
    type_of_game = models.ForeignKey(
        "GameTypesTime",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="games",
    )

    # === Board State ===
    fen = models.CharField(max_length=200, null=True, blank=True)
    turn = models.PositiveIntegerField(null=True, blank=True)
    history = models.TextField(
        null=True, blank=True,
        help_text="JSON string of move history. TextField because PostgreSQL "
                  "jsonb sorts keys alphabetically, which breaks move order.",
    )
    last_move = models.JSONField(default=list, null=True, blank=True)

    # === Game Lifecycle ===
    has_started = models.BooleanField(default=False)
    has_ended = models.BooleanField(default=False)
    color_win = models.PositiveIntegerField(null=True, blank=True)
    all_players_left = models.BooleanField(default=False)

    # === Time Control ===
    initial_time_white = models.PositiveIntegerField(null=True, blank=True, help_text="Seconds")
    initial_time_black = models.PositiveIntegerField(null=True, blank=True, help_text="Seconds")
    remaining_time_white = models.FloatField(null=True, blank=True, help_text="Seconds (float for precision)")
    remaining_time_black = models.FloatField(null=True, blank=True, help_text="Seconds (float for precision)")
    increment = models.PositiveIntegerField(default=0, help_text="Seconds per move")
    started_time = models.DateTimeField(null=True, blank=True)
    finished_time = models.DateTimeField(null=True, blank=True)
    last_move_time = models.DateTimeField(null=True, blank=True)

    # === Captured Pieces ===
    captured_pieces_count_by_white = models.PositiveIntegerField(default=0)
    captured_pieces_count_by_black = models.PositiveIntegerField(default=0)

    # === First Move Tracking ===
    first_color_first_move_done = models.BooleanField(default=False)
    second_color_first_move_done = models.BooleanField(default=False)
    first_move_check_task_id = models.UUIDField(null=True, blank=True)
    first_move_check_task_time = models.DateTimeField(null=True, blank=True)

    # === Timer Task (Celery revoke needs task ID) ===
    move_check_task_id = models.UUIDField(null=True, blank=True)

    # === Draw Offers ===
    white_draw_offer = models.BooleanField(default=False)
    black_draw_offer = models.BooleanField(default=False)

    # === Rating ===
    rating_calculated = models.BooleanField(default=False)

    # === Rematch Tree (MPTT) ===
    parent = TreeForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="children",
    )

    # === Private Game Key ===
    private_key = models.CharField(max_length=64, null=True, blank=True)

    # === Timestamps ===
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class MPTTMeta:
        order_insertion_by = ["created_at"]

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["has_ended", "has_started"]),
            models.Index(fields=["white", "has_ended"]),
            models.Index(fields=["black", "has_ended"]),
        ]

    def __str__(self):
        white_name = self.white.username if self.white else "Anonym"
        black_name = self.black.username if self.black else "Anonym"
        return f"{white_name} vs {black_name}"

    @property
    def get_remaining_times_of_colors_with_calculating(self) -> tuple:
        """
        Calculate remaining time for both players based on last_move_time.

        Returns (remaining_time_white, remaining_time_black) in seconds.
        """
        turn = self.turn
        now = timezone.localtime(timezone.now()).replace(tzinfo=None)
        last_move_time = (
            self.last_move_time.replace(tzinfo=None) if self.last_move_time else None
        )

        if turn == ColorChoices.black:
            if self.second_color_first_move_done and self.remaining_time_black is not None:
                elapsed = (now - last_move_time).total_seconds() if last_move_time else 0
                remaining_time_black = max(0, int(self.remaining_time_black - elapsed))
            else:
                remaining_time_black = self.initial_time_black
            remaining_time_white = self.remaining_time_white
        elif turn == ColorChoices.white:
            if self.first_color_first_move_done and self.remaining_time_white is not None:
                elapsed = (now - last_move_time).total_seconds() if last_move_time else 0
                remaining_time_white = max(0, int(self.remaining_time_white - elapsed))
            else:
                remaining_time_white = self.initial_time_white
            remaining_time_black = self.remaining_time_black
        else:
            remaining_time_white = self.remaining_time_white
            remaining_time_black = self.remaining_time_black

        return remaining_time_white, remaining_time_black


class Chat(models.Model):
    """In-game chat message."""
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="chat_history")
    authorized_sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
    )
    guest_sender = models.ForeignKey(
        "ConnectionHistory",
        on_delete=models.CASCADE,
        null=True, blank=True,
    )
    message = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]
        constraints = [
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_sender_xor",
                condition=(
                    models.Q(authorized_sender__isnull=True, guest_sender__isnull=False)
                    | models.Q(authorized_sender__isnull=False, guest_sender__isnull=True)
                ),
            )
        ]

    def __str__(self):
        sender = self.authorized_sender or self.guest_sender
        return f"{self.game_id} → {sender} → {self.message[:30]}"
