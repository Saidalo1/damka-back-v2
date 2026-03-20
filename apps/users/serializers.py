"""
Serializers for the users app — direct port from v1.

Uses BaseEmailPhoneNumber pattern from v1's shared.django.serializers.
"""
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator, validate_email
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError
from rest_framework.fields import CharField, EmailField
from rest_framework.serializers import Serializer, ModelSerializer
from rest_framework.status import HTTP_400_BAD_REQUEST

from apps.users.models import User, Countries


# ---------- Base serializer (v1: shared.django.serializers.BaseEmailPhoneNumber) ----------

class BaseEmailPhoneNumber(Serializer):
    """Base serializer requiring at least one of email/phone_number."""
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
            HTTP_400_BAD_REQUEST,
        )


class CustomValidationError(ValidationError):
    """Custom validation error allowing status code override."""
    def __init__(self, detail=None, status_code=None):
        super().__init__(detail)
        if status_code:
            self.status_code = status_code


# ---------- Registration ----------

class AuthEmailPhoneNumberSerializer(BaseEmailPhoneNumber):
    """Registration step 1: phone/email + password → send SMS."""
    password = CharField(min_length=8, max_length=128, help_text=_('Password'))

    def validate_phone_number(self, phone_number=None):
        if phone_number and self.context.get('session', {}).get(phone_number):
            raise CustomValidationError(_('A_CONFIRMATION_CODE_HAS_BEEN_SENT_ALREADY'))
        return phone_number

    def validate_email(self, email=None):
        if email and self.context.get('session', {}).get(email):
            raise CustomValidationError(_('A_CONFIRMATION_CODE_HAS_BEEN_SENT_ALREADY'))
        return email


class SMSVerificationSerializer(BaseEmailPhoneNumber):
    """Registration step 2: phone/email + user_entered_code → verify."""
    user_entered_code = CharField(
        validators=[
            RegexValidator(r'^\d{4}$', _('Verification code must be a 4-digit number'))
        ],
        help_text=_('4-digit verification code'),
    )

    def validate_phone_number(self, phone_number=None):
        if phone_number:
            session = self.context.get('session', {})
            if not session.get(phone_number):
                raise CustomValidationError(
                    _('This phone number is not waiting for verification'),
                    HTTP_400_BAD_REQUEST,
                )
        return phone_number

    def validate_email(self, email=None):
        if email:
            session = self.context.get('session', {})
            if not session.get(email):
                raise CustomValidationError(
                    _('This email is not waiting for verification'),
                    HTTP_400_BAD_REQUEST,
                )
        return email


# ---------- Login ----------

class LoginSerializer(BaseEmailPhoneNumber):
    """Login: phone/email + password."""
    password = CharField(min_length=8, max_length=128, help_text=_('Password'))


# ---------- Check account ----------

class CheckAccountByNumberOrEmailSerializer(BaseEmailPhoneNumber):
    """Check if phone/email is already registered."""
    pass


# ---------- Password reset ----------

class PasswordResetRequestSerializer(BaseEmailPhoneNumber):
    """Password reset: request code."""
    pass


class PasswordResetVerificationSerializer(BaseEmailPhoneNumber):
    """Password reset: verify code."""
    verification_code = CharField(
        validators=[RegexValidator(r'^\d{4}$', _('Verification code must be a valid 4-digit number!'))],
        help_text=_('4-digit verification code.'),
    )


class PasswordResetConfirmSerializer(Serializer):
    """Password reset: confirm with new password."""
    new_password = CharField(write_only=True, min_length=8, max_length=128)


# ---------- Profile ----------

class UserUpdateModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ('username', 'avatar', 'country', 'first_name', 'last_name')
        extra_kwargs = {
            'username': {'required': False},
            'avatar': {'required': False},
            'country': {'required': False},
            'first_name': {'required': False},
            'last_name': {'required': False},
        }


class ChangePasswordSerializer(Serializer):
    """Password change endpoint."""
    old_password = CharField(required=True)
    new_password = CharField(required=True)

    @staticmethod
    def validate_new_password(value):
        try:
            validate_password(value)
        except Exception as error:
            raise CustomValidationError({'error': ''.join(str(e) for e in error)})
        return value

    def validate(self, attrs):
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')
        if old_password and new_password and new_password == old_password:
            raise CustomValidationError({'error': _('New password should not match with old!')})
        return super().validate(attrs)


class CheckPasswordSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ('password',)
