"""
Shared Django utilities — used across apps.

Extracted from v1's shared/django/__init__.py + shared/django/utils.py.
Includes all utilities needed by users app and game app.
"""
from random import choice, randint
from re import match
from secrets import token_urlsafe

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, validate_email
from django.db.models import IntegerChoices, Model, DateTimeField, Q
from django.utils.translation import gettext_lazy as _
from rest_framework.authtoken.models import Token
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import APIException, _get_error_details
from rest_framework.fields import CharField, EmailField
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.serializers import Serializer
from rest_framework.status import HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Abstract base model
# ---------------------------------------------------------------------------
class TimeBaseModel(Model):
    """Abstract model with created_at / updated_at timestamps."""
    created_at = DateTimeField(_('created at'), auto_now_add=True)
    updated_at = DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Color / Game type choices
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Validation error (v1 compat)
# ---------------------------------------------------------------------------
class CustomValidationError(APIException):
    """Custom validation error that accepts flexible detail formats."""
    status_code = HTTP_400_BAD_REQUEST
    default_detail = _('Invalid input.')
    default_code = 'invalid'

    def __init__(self, detail=None, code=None):
        if detail is None:
            detail = self.default_detail
        if code is None:
            code = self.default_code
        if (isinstance(detail, tuple) and len(detail) > 1 and not isinstance(detail, dict)
                and not isinstance(detail, list)):
            detail = list(detail)
        self.detail = _get_error_details(detail, code)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
class BaseEmailPhoneNumber(Serializer):
    """Base serializer for phone_number / email input."""
    email = EmailField(
        help_text=_("Email address"),
        validators=[validate_email],
        required=False,
        allow_null=True,
    )
    phone_number = CharField(
        validators=[RegexValidator(r'^\+998\d{9}$', _('Phone number must be valid!'))],
        help_text=_('Phone Number Format'),
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        if attrs.get('email', None) or attrs.get('phone_number', None):
            return super().validate(attrs)
        raise ValidationError(
            {'error': _('One of the following attributes must be provided!')},
        )


# ---------------------------------------------------------------------------
# Authentication / Permissions (v1 compat)
# ---------------------------------------------------------------------------
class CustomTokenAuthentication(TokenAuthentication):
    """Token authentication that does NOT raise on missing/invalid token."""
    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except Exception:
            return None


class CustomTokenPermission(BasePermission):
    """Allows access with valid token OR anonymous access."""
    def has_permission(self, request, view):
        return True


class UniqueNumberOrEmailPermission(BasePermission):
    """Placeholder permission — always allows (validation in serializer)."""
    def has_permission(self, request, view):
        return True


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
class PlayerRatingsPagination(PageNumberPagination):
    page_size = 10


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def validate_telegram_username(username):
    """Validate username: 5-32 chars, starts with letter, alphanumeric + underscore."""
    if not match(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$', username):
        raise ValidationError(
            _('Invalid username. Username must be 5-32 characters long, start with a letter, '
              'and contain only letters, numbers, and underscores.')
        )


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def generate_sms_code() -> str:
    """Generate a 4-digit SMS verification code."""
    return "".join([str(randint(0, 9)) for _ in range(4)])


def generate_private_key() -> str:
    """Generate a URL-safe private key for friend games."""
    return token_urlsafe(16)


def update_users_token(user_id) -> str:
    """Delete old token and create a new one. Returns the new key."""
    users_token = Token.objects.get(user_id=user_id)
    users_token.delete()
    new_key = users_token.generate_key()
    Token.objects.create(user_id=user_id, key=new_key)
    return new_key


def calculate_elo_rating(player_rating, opponent_rating, score, k_factor=32):
    """ELO rating calculation."""
    player_rating, opponent_rating = int(player_rating), int(opponent_rating)
    expected_score = 1 / (1 + pow(10, (opponent_rating - player_rating) / 400))
    new_rating = player_rating + k_factor * (score - expected_score)
    return max(0, new_rating)


def calculate_rating_benefit(old_rating, new_rating) -> dict:
    """Calculate rating change info."""
    old_rating, new_rating = int(old_rating), int(new_rating)
    return {
        'equilibrium': new_rating - old_rating,
        'new_rating': new_rating,
        'old_rating': old_rating,
    }


def send_verification_email(email, code, username):
    """Send verification email (placeholder — configure in production)."""
    from django.conf import settings
    if settings.DEBUG:
        print(f"[DEBUG] Verification email to {email}: code={code}")
        return
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    subject = 'Verification Code'
    from_email = settings.EMAIL_HOST_USER
    html_content = render_to_string('email/message.html', {'username': username, 'code': code})
    msg = EmailMultiAlternatives(subject, '', from_email, [email])
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def _eskiz_login(api, settings) -> str | None:
    """Log in to Eskiz and return a fresh bearer token (or None on failure)."""
    from requests import post
    resp = post(f"{api}/auth/login",
                data={"email": settings.ESKIZ_EMAIL, "password": settings.ESKIZ_PASSWORD},
                timeout=10)
    try:
        return resp.json().get("data", {}).get("token")
    except Exception:
        return None


def send_notification(phone, code) -> tuple:
    """Send an SMS verification code via Eskiz.uz.

    Returns (status_code, detail, raw_text, sent_message). In DEBUG we don't hit
    the network — the code is already surfaced in the registration response/logs.

    The bearer token is cached in Redis (key ``eskiz_token``, ~7 days). Unlike V1
    (which had no refresh path), a 401 from an expired-but-cached token triggers a
    single re-login + retry.
    """
    from django.conf import settings

    if settings.DEBUG:
        print(f"[DEBUG] SMS to {phone}: code={code}")
        return (200, "OK", "", f"Code: {code}")

    import redis as sync_redis
    from requests import post

    api = settings.ESKIZ_API_URL.rstrip("/")
    r = sync_redis.from_url(settings.REDIS_URL)

    cached = r.get("eskiz_token")
    token = cached.decode() if cached else None
    if not token:
        token = _eskiz_login(api, settings)
        if not token:
            return (502, "eskiz login failed", "", "")
        r.setex("eskiz_token", 60 * 60 * 24 * 7, token)

    def _send(tok):
        return post(
            f"{api}/message/sms/send",
            data={
                "from": settings.ESKIZ_FROM,
                "mobile_phone": str(phone).lstrip("+"),  # Eskiz wants 998XXXXXXXXX
                "message": settings.ESKIZ_MESSAGE.format(code=code),
            },
            headers={"Authorization": f"Bearer {tok}"},
            timeout=10,
        )

    resp = _send(token)
    if resp.status_code == 401:  # cached token expired → re-login once and retry
        r.delete("eskiz_token")
        token = _eskiz_login(api, settings)
        if token:
            r.setex("eskiz_token", 60 * 60 * 24 * 7, token)
            resp = _send(token)

    try:
        detail = resp.json().get("message", resp.text[:200])
    except Exception:
        detail = resp.text[:200]
    return (resp.status_code, detail, resp.text[:200], settings.ESKIZ_MESSAGE.format(code=code))

