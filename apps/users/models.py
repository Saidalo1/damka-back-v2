"""Custom User model for Damka.uz — phone-based authentication."""
from django.contrib.auth.models import AbstractUser
from django.db import models
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFill


class User(AbstractUser):
    """
    Custom user with phone-based auth and per-mode ELO ratings.

    USERNAME_FIELD = 'phone_number' — login via phone number.
    Supports avatar with auto-generated WebP thumbnails.
    """
    phone_number = models.CharField(max_length=13, unique=True, help_text="Format: +998XXXXXXXXX")

    # Avatar with WebP thumbnails
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    avatar_small = ImageSpecField(
        source="avatar",
        processors=[ResizeToFill(64, 64)],
        format="WEBP",
        options={"quality": 80},
    )
    avatar_medium = ImageSpecField(
        source="avatar",
        processors=[ResizeToFill(192, 192)],
        format="WEBP",
        options={"quality": 85},
    )
    avatar_large = ImageSpecField(
        source="avatar",
        processors=[ResizeToFill(512, 512)],
        format="WEBP",
        options={"quality": 90},
    )

    # Country
    country = models.ForeignKey(
        "Countries",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="users",
    )

    # ELO ratings — separate for each game type
    bullet_rating = models.IntegerField(default=1600)
    blitz_rating = models.IntegerField(default=1600)
    rapid_rating = models.IntegerField(default=1600)

    # Rating update timestamps (for leaderboard sorting)
    bullet_updated_at = models.DateTimeField(null=True, blank=True)
    blitz_updated_at = models.DateTimeField(null=True, blank=True)
    rapid_updated_at = models.DateTimeField(null=True, blank=True)

    # Telegram integration
    chat_id = models.CharField(max_length=50, null=True, blank=True, help_text="Telegram Chat ID")

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.username} ({self.phone_number})"

    def get_rating_for_mode(self, mode: str) -> int:
        """Get rating for a specific game mode (bullet/blitz/rapid)."""
        return getattr(self, f"{mode}_rating", 1600)

    def set_rating_for_mode(self, mode: str, rating: int) -> None:
        """Set rating for a specific game mode and save."""
        setattr(self, f"{mode}_rating", rating)
        self.save(update_fields=[f"{mode}_rating", f"{mode}_updated_at"])


class Countries(models.Model):
    """Country reference with flags."""
    code = models.CharField(max_length=5, unique=True)
    title = models.CharField(max_length=100)
    flag = models.ImageField(upload_to="flags/", null=True, blank=True)

    class Meta:
        verbose_name = "Country"
        verbose_name_plural = "Countries"
        ordering = ["title"]

    def __str__(self):
        return self.title
