"""Handbook models — game types, time controls, connection tracking."""
from django.db import models


class GameTypes(models.Model):
    """Game category: Bullet, Blitz, Rapid."""
    title = models.CharField(max_length=50)
    separate_var = models.CharField(
        max_length=20,
        unique=True,
        help_text="Variable name for rating field: bullet, blitz, rapid",
    )
    icon = models.ImageField(upload_to="game_types/", null=True, blank=True)

    class Meta:
        verbose_name = "Game Type"
        verbose_name_plural = "Game Types"

    def __str__(self):
        return self.title


class GameTypesTime(models.Model):
    """Specific time control configuration within a game type."""
    type = models.ForeignKey(GameTypes, on_delete=models.CASCADE, related_name="time_controls")
    title = models.CharField(max_length=20, help_text="Display name, e.g. '5+3'")
    time = models.IntegerField(help_text="Initial time in seconds")
    increment = models.IntegerField(default=0, help_text="Increment per move in seconds")

    class Meta:
        verbose_name = "Time Control"
        verbose_name_plural = "Time Controls"
        ordering = ["type", "time", "increment"]

    def __str__(self):
        return f"{self.type.title} — {self.title}"


class ConnectionStatusChoices(models.IntegerChoices):
    """Status of anonymous player connection."""
    OFFLINE = 0, "Offline"
    ONLINE = 1, "Online"


class ConnectionHistory(models.Model):
    """Tracks anonymous (guest) player connections and their rating."""
    anonym_token = models.CharField(max_length=100, unique=True)
    status = models.IntegerField(
        choices=ConnectionStatusChoices.choices,
        default=ConnectionStatusChoices.OFFLINE,
    )
    was_failed = models.BooleanField(default=False)
    rating = models.IntegerField(default=1600)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Connection History"
        verbose_name_plural = "Connection Histories"

    def __str__(self):
        return f"Anonym {self.anonym_token[:8]}... (rating: {self.rating})"
