from typing import Union

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinLengthValidator
from django.db import ProgrammingError
from django.db.models import (
    CharField, ImageField, PositiveIntegerField, UniqueConstraint,
    ForeignKey, PROTECT, DateTimeField, Q, Model,
)
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from imagekit.exceptions import MissingSource
from imagekit.models import ImageSpecField
from pilkit.processors import ResizeToFill
from rest_framework.authtoken.models import Token

from config.settings.base import STATIC_URL
from shared.django import RATING_LEVELS, GameType
from shared.django import validate_telegram_username


GLOBAL_COUNTRY_CODE = 'UZ'
COUNTRIES_OVERRIDE = {
    'UZ': 'Uzbekistan',
}


class Countries(Model):
    title = CharField(max_length=255, verbose_name=_('title'))
    code = CharField(max_length=2, verbose_name=_('code'), unique=True)

    @property
    def flag(self):
        return STATIC_URL + f"flag/{self.code.lower()}.gif"

    @classmethod
    def get_default_pk(cls):
        try:
            exam, created = cls.objects.get_or_create(
                title=COUNTRIES_OVERRIDE[GLOBAL_COUNTRY_CODE], code=GLOBAL_COUNTRY_CODE
            )
            return exam.pk
        except (ProgrammingError, Countries.DoesNotExist):
            return None

    class Meta:
        verbose_name = _('country')
        verbose_name_plural = _('countries')

    def __str__(self):
        return self.title


class User(AbstractUser):
    username = CharField(max_length=32, verbose_name=_('username'), unique=True,
                         validators=[validate_telegram_username, MinLengthValidator(5)])
    first_name = CharField(max_length=150, null=True, blank=True, verbose_name=_('first_name'))
    last_name = CharField(max_length=150, null=True, blank=True, verbose_name=_('last_name'))
    avatar = ImageField(upload_to='images/users/avatar', null=True, blank=True, verbose_name=_('avatar'))
    avatar_small = ImageSpecField(source='avatar', processors=[ResizeToFill(64, 64)],
                                  format='Webp', options={'quality': 60})
    avatar_middle = ImageSpecField(source='avatar', processors=[ResizeToFill(192, 192)],
                                   format='Webp', options={'quality': 60})
    avatar_large = ImageSpecField(source='avatar', processors=[ResizeToFill(512, 512)],
                                  format='Webp', options={'quality': 60})
    country = ForeignKey('users.Countries', PROTECT, default=Countries.get_default_pk, verbose_name=_('country'))
    phone_number = CharField(max_length=13, validators=[
        RegexValidator(regex=r'^\+998\d{9}$', message=_(
            'Phone number is not valid! Please, enter a valid phone number in the format "+998XXXXXXXXX".'))],
                             verbose_name=_('phone_number'), null=True, blank=True)
    bullet_rating = PositiveIntegerField(_('bullet rating'), default=RATING_LEVELS[3], db_index=True)
    blitz_rating = PositiveIntegerField(_('blitz rating'), default=RATING_LEVELS[3], db_index=True)
    rapid_rating = PositiveIntegerField(_('rapid rating'), default=RATING_LEVELS[3], db_index=True)
    updated_at = DateTimeField(_('updated at'), auto_now=True)
    chat_id = CharField(max_length=50, verbose_name=_("chat id"), unique=True, null=True,
                        blank=True)  # telegram chat id
    bullet_updated_at = DateTimeField(_('bullet rating updated at'), auto_now_add=True, null=True)
    blitz_updated_at = DateTimeField(_('blitz rating updated at'), auto_now_add=True, null=True)
    rapid_updated_at = DateTimeField(_('rapid rating updated at'), auto_now_add=True, null=True)

    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = []

    @property
    def avatar_sm(self):
        try:
            name = self.avatar_small.name
            return self.avatar_small.url if name is not None and name != '' else None
        except (FileNotFoundError, MissingSource):
            return None

    @property
    def avatar_md(self):
        try:
            name = self.avatar_middle.name
            return self.avatar_middle.url if name is not None and name != '' else None
        except (FileNotFoundError, MissingSource):
            return None

    @property
    def avatar_lg(self):
        try:
            name = self.avatar_large.name
            return self.avatar_large.url if name is not None and name != '' else None
        except (FileNotFoundError, MissingSource):
            return None

    def rating(self, mode: int):
        if mode == GameType.bullet:
            return self.bullet_rating
        elif mode == GameType.blitz:
            return self.blitz_rating
        elif mode == GameType.rapid:
            return self.rapid_rating
        return

    def clean(self):
        pk = self.pk
        if any((self.phone_number, self.email)):
            if self.phone_number and User.objects.filter(phone_number=self.phone_number).exclude(pk=pk).exists():
                raise ValidationError(
                    _('Phone number %(phone_number)s already exists') % {'phone_number': self.phone_number}
                )
            elif self.email != '' and self.email is not None and User.objects.filter(email=self.email).exclude(
                    pk=pk).exists():
                raise ValidationError(_('Email %(email)s already exists') % {'email': self.email})
            return super().clean()
        raise ValidationError(
            _('You must provide a phone number or an email address (one of them) to create a new account!'))

    @property
    def token_key(self) -> Union[str, None]:
        try:
            return self.auth_token.key
        except Token.DoesNotExist:
            return None

    class Meta:
        constraints = [
            UniqueConstraint(Lower('username'), name='unique_username_lower',
                             violation_error_message=_('User with this username already exists!')),
            UniqueConstraint(
                fields=['phone_number'],
                name='unique_phone_number_not_blank_or_null',
                condition=Q(phone_number__isnull=False) & ~Q(phone_number=''),
                violation_error_message=_('This phone number is already in use!')
            ),
        ]
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def __str__(self):
        full_name = self.get_full_name()
        return full_name if full_name != 'None None' else self.username
