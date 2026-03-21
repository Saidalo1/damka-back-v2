from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from rest_framework.fields import EmailField
from rest_framework.serializers import CharField, Serializer, ModelSerializer
from rest_framework.status import HTTP_400_BAD_REQUEST

from shared.django import BaseEmailPhoneNumber, CustomValidationError
from apps.users.models import User


class AuthEmailPhoneNumberSerializer(BaseEmailPhoneNumber):
    """Serializer for registration."""
    password = CharField(min_length=8, max_length=128, help_text=_('Password'))

    def validate_phone_number(self, phone_number=None):
        if phone_number and self.context['session'].get(phone_number):
            raise CustomValidationError(_('A_CONFIRMATION_CODE_HAS_BEEN_SENT_ALREADY'))
        return phone_number

    def validate_email(self, email=None):
        if email and self.context['session'].get(email):
            raise CustomValidationError(_('A_CONFIRMATION_CODE_HAS_BEEN_SENT_ALREADY'))
        return email


class SMSVerificationSerializer(BaseEmailPhoneNumber):
    """Serializer for SMS verification."""
    user_entered_code = CharField(
        validators=[
            RegexValidator(r'^\d{4}$', _('VERIFICATION_CODE_MUST_BE_MESSAGE_TEXT'))
        ],
        help_text=_('4-digit verification code')
    )

    def validate_phone_number(self, phone_number=None):
        if phone_number:
            if self.context['session'].get(phone_number):
                pass
            else:
                raise CustomValidationError(_('THIS_PHONE_NUMBER_IS_NOT_IN_WAITING_VERIFICATION'),
                                            HTTP_400_BAD_REQUEST)
        return phone_number

    def validate_email(self, email=None):
        if email:
            if self.context['session'].get(email):
                pass
            else:
                raise CustomValidationError(_('THIS_EMAIL_IS_NOT_IN_WAITING_VERIFICATION'),
                                            HTTP_400_BAD_REQUEST)
        return email


class LoginSerializer(BaseEmailPhoneNumber):
    """Serializer for login."""
    password = CharField(min_length=8, max_length=128, help_text=_('Password'))


class CheckAccountByNumberOrEmailSerializer(BaseEmailPhoneNumber):
    pass


class PasswordResetRequestSerializer(BaseEmailPhoneNumber):
    """Serializer for password reset request."""
    pass


class PasswordResetVerificationSerializer(BaseEmailPhoneNumber):
    """Serializer for password reset verification."""
    verification_code = CharField(
        validators=[RegexValidator(r'^\d{4}$', _('Verification code must be a valid 4-digit number!'))],
        help_text=_('4-digit verification code.')
    )


class PasswordResetConfirmSerializer(Serializer):
    """Serializer for password reset confirmation."""
    new_password = CharField(write_only=True, min_length=8, max_length=128)


class UserUpdateModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = 'username', 'avatar', 'country', 'first_name', 'last_name'
        extra_kwargs = {
            'username': {'required': False},
            'avatar': {'required': False},
            'country': {'required': False},
            'first_name': {'required': False},
            'last_name': {'required': False},
        }


class UserUpdateEmailOrPhoneNumberModelSerializer(ModelSerializer):
    phone = CharField(
        validators=[RegexValidator(r'^\+998\d{9}$', _('Phone number format invalid!'))],
        help_text=_('Phone Number Format'), allow_null=True
    )
    email = EmailField(help_text=_('Email address'), allow_null=True)

    def validate(self, attrs):
        email, phone_number = attrs.get('email', None), attrs.get('phone', None)
        if email is not None or phone_number is not None:
            return super().validate(attrs)
        raise CustomValidationError({"error": _("One of these fields is required!")})

    class Meta:
        model = User
        fields = 'email', 'phone'
        extra_kwargs = {
            'phone': {'required': False},
            'email': {'required': False}
        }


class UpdateSMSVerificationSerializer(ModelSerializer):
    """Serializer for SMS verification when updating phone/email."""
    phone = CharField(
        validators=[RegexValidator(r'^\+998\d{9}$', _('Phone number format invalid!'))],
        help_text=_('Phone Number Format'), allow_null=True
    )
    email = EmailField(help_text=_('Email address'), allow_null=True)
    user_entered_code = CharField(
        validators=[
            RegexValidator(r'^\d{4}$', _('Verification code format is invalid!'))
        ],
        help_text=_('4-digit verification code.')
    )

    def validate(self, attrs):
        phone_number = attrs.get('phone', None)
        email = attrs.get('email', None)
        once = phone_number if phone_number is not None else email
        if once:
            session = self.context
            if session['session'].get(f"{once}_{session['user_id']}"):
                return super().validate(attrs)
            else:
                raise CustomValidationError({'error': _('This data is not waiting for verification!')},
                                            HTTP_400_BAD_REQUEST)
        else:
            raise CustomValidationError({'error': _('One of these fields is required!')})

    class Meta:
        model = User
        fields = 'phone', 'email', 'user_entered_code'
        extra_kwargs = {
            'phone': {'required': False},
            'email': {'required': False}
        }


class ChangePasswordSerializer(Serializer):
    """Serializer for password change."""
    old_password = CharField(required=True)
    new_password = CharField(required=True)

    @staticmethod
    def validate_new_password(value):
        try:
            validate_password(value)
        except Exception as error:
            raise CustomValidationError({'error': ''.join(error)})
        return value

    def validate(self, attrs):
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')
        if old_password and new_password and new_password == old_password:
            raise CustomValidationError({'error': _('New password should not match with old!')})
        return super().validate(attrs)


class CheckPasswordSerializer(ModelSerializer):
    """Serializer for check password endpoint."""
    class Meta:
        model = User
        fields = 'password',


class RemoveUserSerializer(Serializer):
    password = CharField(required=True, min_length=8, max_length=128, write_only=True)

    def validate_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise CustomValidationError({'error': _('Invalid password!')})
        return value
