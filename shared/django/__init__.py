"""
Shared Django utilities — used across apps.

Extracted from v1's shared/django/__init__.py + shared/django/utils.py.
"""
from random import choice
from secrets import token_urlsafe

from django.db.models import IntegerChoices
from django.utils.translation import gettext_lazy as _


class ColorChoices(IntegerChoices):
    """
    Color constants for players.

    In v1 these mapped to pydraughts BLACK=1, WHITE=2.
    In v2 with py-draughts: Color.BLACK.value=1, Color.WHITE.value=-1,
    but we keep the DB values as 1=black, 2=white for compatibility.
    """
    black = 1, _("Black")
    white = 2, _("White")
    random = 0, _("Random")
    cancelled = 3, _("Cancelled")

    @staticmethod
    def random_value():
        """Return a random color (white or black)."""
        return choice((ColorChoices.white.value, ColorChoices.black.value))


class ColorTextChoices:
    """String representations for colors."""
    black = "black"
    white = "white"


class ConnectionTypes(IntegerChoices):
    """Connection type for WebSocket auth."""
    anonym = 0, _("Anonym")
    authorized = 1, _("Authorized")


class GameType(IntegerChoices):
    """Game mode categories."""
    bullet = 0, _("Bullet")
    blitz = 1, _("Blitz")
    rapid = 2, _("Rapid")


# Rating levels for anonymous players
RATING_LEVELS = {
    1: 400,
    2: 800,
    3: 1200,
    4: 1600,
}


def generate_private_key() -> str:
    """Generate a URL-safe private key for friend games."""
    return token_urlsafe(16)


def generate_sms_code() -> str:
    """Generate a 4-digit SMS verification code."""
    from random import randint
    return "".join([str(randint(0, 9)) for _ in range(4)])
