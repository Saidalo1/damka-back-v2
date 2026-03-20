"""
User auth views — direct port from v1.

Differences from v1:
- Uses Django session instead of STRICT_REDIS for SMS code storage
  (TODO: migrate to Redis when Celery SMS sending is integrated)
- In DEBUG mode, SMS code is logged to console and "0000" is always accepted
- Uses apps.users.models instead of users.models
"""
import logging
from json import dumps, loads
from secrets import token_urlsafe

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db.models import F, Value
from django.db.models.functions import Concat, Lower
from django.http import JsonResponse
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.translation import gettext_lazy as _
from rest_framework.authtoken.models import Token
from rest_framework.generics import CreateAPIView, GenericAPIView, UpdateAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_200_OK, HTTP_201_CREATED, HTTP_404_NOT_FOUND
from rest_framework.views import APIView

from apps.users.models import User, Countries
from apps.users.serializers import (
    AuthEmailPhoneNumberSerializer,
    SMSVerificationSerializer,
    LoginSerializer,
    CheckAccountByNumberOrEmailSerializer,
    UserUpdateModelSerializer,
    ChangePasswordSerializer,
    CheckPasswordSerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerificationSerializer,
    PasswordResetConfirmSerializer,
)
from apps.users.tokens import account_activation_token
from shared.django import generate_sms_code

logger = logging.getLogger(__name__)

# Verification code TTL in seconds (5 minutes)
VERIFICATION_CODE_TTL = 300


# ---------- Helpers ----------

def _store_sms_data(session, identifier: str, code: str, extra: dict = None):
    """Store SMS verification code + extra data in session (keyed by raw identifier like v1 Redis)."""
    data = {'code': code}
    if extra:
        data.update(extra)
    session[identifier] = dumps(data)


def _get_sms_data(session, identifier: str) -> dict | None:
    """Retrieve SMS verification data from session."""
    raw = session.get(identifier)
    if raw:
        return loads(raw)
    return None


def _clear_sms_data(session, identifier: str):
    """Remove SMS verification data from session."""
    if identifier in session:
        del session[identifier]


def _send_sms_code(phone_number: str, code: str):
    """
    Send SMS code to phone number.

    In DEBUG: log to console only.
    In production: TODO — integrate Eskiz.uz via Celery task.
    """
    if settings.DEBUG:
        logger.info("DEBUG SMS code for %s: %s", phone_number, code)
    else:
        # TODO: send_notification.apply_async(kwargs={"phone": phone_number, "code": code})
        logger.warning("SMS sending not implemented in production yet!")


def _verify_code(session, identifier: str, user_code: str) -> tuple[bool, dict | None, str]:
    """
    Verify SMS code. Returns (success, sms_data, error_message).

    In DEBUG mode, "0000" is always accepted.
    """
    sms_data = _get_sms_data(session, identifier)

    if not sms_data:
        return False, None, str(_('This identifier is not waiting for verification'))

    saved_code = sms_data.get('code')

    # DEBUG mode: accept "0000"
    if settings.DEBUG and user_code == "0000":
        return True, sms_data, ""

    if saved_code and user_code == saved_code:
        return True, sms_data, ""

    # Track attempts
    attempts_key = f"{identifier}_attempts"
    attempts = session.get(attempts_key, 0) + 1
    session[attempts_key] = attempts

    if attempts >= 5:
        _clear_sms_data(session, identifier)
        if attempts_key in session:
            del session[attempts_key]
        return False, None, str(_('You have no more attempts, try again!'))

    return False, None, str(_('Wrong SMS Code'))


def _update_users_token(user_pk: int) -> str:
    """Delete old token and create a new one for the user."""
    Token.objects.filter(user_id=user_pk).delete()
    new_token = Token.objects.create(user_id=user_pk)
    return new_token.key


# ==================== Registration ====================

class SMSRequestView(CreateAPIView):
    """Registration step 1: phone/email + password → send SMS code."""
    serializer_class = AuthEmailPhoneNumberSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            context={'session': request.session},
        )
        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            email = serializer.validated_data.get('email', None)
            identifier = phone_number or email

            code = generate_sms_code()

            # Store code + password in session
            _store_sms_data(request.session, identifier, code, {
                'password': serializer.validated_data['password'],
            })

            if phone_number:
                _send_sms_code(phone_number, code)
            else:
                # TODO: send_verification_email(email, code, _('User'))
                logger.info("DEBUG email code for %s: %s", email, code)

            return Response({'message': _('SMS code sent'), 'data': identifier}, HTTP_201_CREATED)
        return Response(serializer.errors, HTTP_400_BAD_REQUEST)


class SMSVerificationView(CreateAPIView):
    """Registration step 2: phone/email + user_entered_code → create user + return token."""
    serializer_class = SMSVerificationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            context={'session': request.session},
        )
        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            email = serializer.validated_data.get('email', None)
            identifier = phone_number or email
            user_entered_code = serializer.validated_data['user_entered_code']

            success, sms_data, error_msg = _verify_code(
                request.session, identifier, user_entered_code
            )

            if success and sms_data:
                # Generate unique username (v1 logic)
                user_count = User.objects.count()
                unique_username = f"User{user_count}"
                while User.objects.filter(username=unique_username).exists():
                    user_count += 1
                    unique_username = f"User{user_count}"

                # Create user
                if phone_number:
                    user = User(phone_number=phone_number, username=unique_username)
                else:
                    user = User(email=email, username=unique_username)
                user.set_password(sms_data.get('password'))
                user.save()

                token, created = Token.objects.get_or_create(user=user)
                _clear_sms_data(request.session, identifier)

                return Response({
                    'message': _('Successful'),
                    'token': token.key,
                    'username': unique_username,
                }, HTTP_200_OK)
            else:
                return Response({'error': error_msg}, HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, HTTP_400_BAD_REQUEST)


# ==================== Login ====================

class LoginView(GenericAPIView):
    """Login with phone/email + password → return token."""
    serializer_class = LoginSerializer

    def post(self, request, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            password = serializer.validated_data.get('password')

            if phone_number:
                user = authenticate(phone_number=phone_number, password=password)
            else:
                email = serializer.validated_data.get('email')
                user = authenticate(email=email, password=password)

            if user:
                token, created = Token.objects.get_or_create(user=user)
                return Response({
                    "token": token.key,
                    "message": _("Successful"),
                }, HTTP_200_OK)
            else:
                return Response({
                    "token": None,
                    "message": "Wrong password",
                }, HTTP_400_BAD_REQUEST)


# ==================== Check account ====================

class CheckExistingAccountByNumberOrEmail(GenericAPIView):
    """Check if phone/email is already registered."""
    serializer_class = CheckAccountByNumberOrEmailSerializer

    def post(self, request, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            if phone_number is None:
                email = serializer.validated_data.get('email', None)
                once = email
            else:
                once = phone_number

            response = {'data': once}

            try:
                user = (
                    User.objects.get(phone_number=once) if phone_number
                    else User.objects.get(email=once)
                )
                response.update({
                    'is_registered': True,
                    'full_name': user.username,
                })
            except User.DoesNotExist:
                response.update({
                    'is_registered': False,
                    'full_name': None,
                })

            return Response(response)


class CheckExistingAccountByUsername(APIView):
    """Check if username is taken."""
    @staticmethod
    def get(request, **kwargs):
        username = kwargs.get('username')
        try:
            User.objects.get(username=username)
            return Response({'is_taken': True})
        except User.DoesNotExist:
            return Response({'is_taken': False})


# ==================== Profile ====================

class UserUpdateView(UpdateAPIView):
    """Update user profile (username, avatar, etc.)."""
    serializer_class = UserUpdateModelSerializer
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)

    def get_object(self):
        return self.request.user


class UserDetailAPIView(APIView):
    """Get authenticated user profile."""
    permission_classes = (IsAuthenticated,)

    @staticmethod
    def get(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return Response({'is_guest': True})

        result = {
            'id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'ratings': {
                'bullet': user.bullet_rating,
                'blitz': user.blitz_rating,
                'rapid': user.rapid_rating,
            },
            'avatar': f"{user.avatar.url}" if user.avatar else None,
            'date_joined': user.date_joined,
            'is_guest': False,
        }

        if user.phone_number:
            result['phone_number'] = user.phone_number
        elif user.email:
            result['email'] = user.email

        return Response(result)


class ChangePasswordView(GenericAPIView):
    """Change password endpoint."""
    serializer_class = ChangePasswordSerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        user = request.user
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            if not user.check_password(serializer.data.get("old_password")):
                return Response({"error": _("Wrong password.")}, HTTP_400_BAD_REQUEST)
            user.set_password(serializer.data.get("new_password"))
            user.save(update_fields=('password',))
            new_token = _update_users_token(user.pk)
            return Response({
                'message': _('Your password updated successfully!'),
                'new_token': new_token,
            }, HTTP_200_OK)
        return Response(serializer.errors, HTTP_400_BAD_REQUEST)


class CheckPasswordView(GenericAPIView):
    """Check current password endpoint."""
    serializer_class = CheckPasswordSerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        user = request.user
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            if not user.check_password(serializer.data.get("password")):
                return Response({"error": _("Wrong password!")}, HTTP_400_BAD_REQUEST)
            return Response({'message': _('Correct password!')}, HTTP_200_OK)
        return Response(serializer.errors, HTTP_400_BAD_REQUEST)


# ==================== Password reset ====================

class PasswordResetRequestView(GenericAPIView):
    """Password reset step 1: phone/email → send verification code."""
    serializer_class = PasswordResetRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            email = serializer.validated_data.get('email', None)
            identifier = phone_number or email

            # Check if already sent
            existing = _get_sms_data(request.session, f"password_reset:{identifier}")
            if existing:
                return Response(
                    {'error': _('A verification code has already been sent to this data.')},
                    HTTP_400_BAD_REQUEST,
                )

            # Check user exists
            try:
                if phone_number:
                    User.objects.get(phone_number=identifier)
                else:
                    User.objects.get(email=identifier)
            except User.DoesNotExist:
                return Response(
                    {'message': _('User with this data does not exist!')},
                    HTTP_404_NOT_FOUND,
                )

            code = generate_sms_code()

            if phone_number:
                _send_sms_code(phone_number, code)
            else:
                logger.info("DEBUG reset email code for %s: %s", email, code)

            _store_sms_data(request.session, f"password_reset:{identifier}", code)

            return Response({'message': _('Verification code sent successfully!')}, HTTP_200_OK)


class PasswordResetVerificationView(GenericAPIView):
    """Password reset step 2: phone/email + verification_code → get reset link."""
    serializer_class = PasswordResetVerificationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            email = serializer.validated_data.get('email', None)
            identifier = phone_number or email
            user_entered_code = serializer.validated_data['verification_code']

            success, sms_data, error_msg = _verify_code(
                request.session, f"password_reset:{identifier}", user_entered_code
            )

            if success:
                # Mark as verified
                request.session[f"password_reset_verified:{identifier}"] = True

                user = (
                    User.objects.get(phone_number=identifier) if phone_number
                    else User.objects.get(email=identifier)
                )
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = account_activation_token.make_token(user)
                current_site = request.build_absolute_uri('/')[:-1]
                reset_link = current_site + reverse('password_reset_confirm', args=(uid, token))

                _clear_sms_data(request.session, f"password_reset:{identifier}")

                return Response({
                    'message': _('Successfully verified!'),
                    'reset_link': reset_link,
                }, HTTP_200_OK)
            else:
                return Response({'error': error_msg}, HTTP_400_BAD_REQUEST)


class PasswordResetConfirmView(GenericAPIView):
    """Password reset step 3: uidb64 + token + new_password → reset password."""
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request, uidb64=None, token=None, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            try:
                uid = urlsafe_base64_decode(uidb64).decode()
                user = User.objects.get(pk=uid)
            except (TypeError, ValueError, OverflowError, User.DoesNotExist):
                user = None

            if user is not None and account_activation_token.check_token(user, token):
                phone_number, email = user.phone_number, user.email
                verified_phone = request.session.get(f"password_reset_verified:{phone_number}")
                verified_email = request.session.get(f"password_reset_verified:{email}")

                if verified_phone or verified_email:
                    new_password = serializer.validated_data['new_password']
                    user.set_password(new_password)
                    user.save()

                    # Cleanup session
                    for key in [
                        f"password_reset_verified:{phone_number}",
                        f"password_reset_verified:{email}",
                    ]:
                        if key in request.session:
                            del request.session[key]

                    new_token = _update_users_token(user.pk)
                    return Response({
                        'message': _('Password has been reset successfully!'),
                        'new_token': new_token,
                    }, HTTP_200_OK)
                else:
                    return Response({'error': _('Verification limit expired!')}, HTTP_400_BAD_REQUEST)
            else:
                return Response({'error': _('Invalid reset link!')}, HTTP_400_BAD_REQUEST)


# ==================== Countries ====================

class CountriesView(APIView):
    """Get all countries list."""
    @staticmethod
    def get(request, *args, **kwargs):
        countries = Countries.objects.values('title', 'code')
        return Response(list(countries))


# ==================== Anonymous token ====================

class AnonymousTokenView(APIView):
    """Generate a unique token for anonymous users."""
    def get(self, request, *args, **kwargs):
        token = token_urlsafe(32)
        return JsonResponse({'token': token})
