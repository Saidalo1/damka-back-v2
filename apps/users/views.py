"""
User views — authentication, profile management.

Matches v1 API contract exactly:
- POST /api/users/register/      — request SMS code (phone/email + password)
- POST /api/users/sms/           — verify SMS + create account
- POST /api/users/login/         — login with phone/email + password
- POST /api/users/check/         — check if account exists
- GET  /api/users/check/<username>/  — check if username is taken
- POST /api/users/guest/         — generate anonymous token
- GET  /api/users/profile/       — get current user profile
- PATCH /api/users/profile/      — update profile
- POST /api/users/change-password/ — change password
- GET  /api/users/countries/     — list all countries
- POST /api/users/reset/account/ — request password reset
- POST /api/users/reset/sms/     — verify reset SMS code
- POST /api/users/reset/confirm/<uidb64>/<token>/ — set new password
"""
import logging
import uuid

from django.conf import settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import User, Countries
from apps.users.serializers import (
    RegisterSerializer,
    SMSVerifySerializer,
    LoginSerializer,
    CheckAccountSerializer,
    UserProfileSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
    CountrySerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    PasswordResetConfirmSerializer,
)

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    """
    Step 1: Request SMS verification code.

    V1 parity: accepts phone_number/email + password.
    Stores password in session, sends SMS code.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data.get("phone_number")
        email = serializer.validated_data.get("email")
        password = serializer.validated_data["password"]
        identifier = phone or email

        # Check if already registered
        if phone and User.objects.filter(phone_number=phone).exists():
            return Response(
                {"error": "Phone number already registered"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if email and User.objects.filter(email=email).exists():
            return Response(
                {"error": "Email already registered"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if SMS already sent (v1 parity)
        if request.session.get(identifier):
            return Response(
                {"detail": "A_CONFIRMATION_CODE_HAS_BEEN_SENT_ALREADY"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Generate 4-digit code
        import random
        code = f"{random.randint(1000, 9999)}"

        # Store in session (code + password for later verification)
        request.session[identifier] = {
            "code": code,
            "password": password,
            "phone_number": phone,
            "email": email,
        }

        # TODO: Send SMS via Eskiz.uz or email
        if settings.DEBUG:
            logger.info("DEBUG: SMS code for %s is %s", identifier, code)

        return Response({"message": "SMS code sent", "data": identifier})


class SMSVerifyView(APIView):
    """
    Step 2: Verify SMS code and create account.

    V1 parity: accepts phone_number/email + user_entered_code.
    Retrieves password from session, creates user, returns token + username.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SMSVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data.get("phone_number")
        email = serializer.validated_data.get("email")
        user_entered_code = serializer.validated_data["user_entered_code"]
        identifier = phone or email

        # Get stored registration data from session
        session_data = request.session.get(identifier)
        if not session_data:
            return Response(
                {"error": "No verification pending for this identifier"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify code (DEBUG: accept "0000")
        stored_code = session_data.get("code", "")
        if settings.DEBUG:
            # In debug mode, accept "0000" as valid code
            if user_entered_code != "0000" and user_entered_code != stored_code:
                return Response(
                    {"error": "Invalid verification code"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            if user_entered_code != stored_code:
                return Response(
                    {"error": "Invalid verification code"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Create user with password from session
        password = session_data.get("password", "")
        stored_phone = session_data.get("phone_number")
        stored_email = session_data.get("email")

        # Generate a default username (phone number, will be changed by user)
        default_username = stored_phone or stored_email or str(uuid.uuid4())[:8]

        user = User.objects.create_user(
            username=default_username,
            phone_number=stored_phone or "",
            email=stored_email or "",
            password=password,
        )
        token = Token.objects.create(user=user)

        # Clean up session
        del request.session[identifier]
        request.session.modified = True

        return Response({
            "token": token.key,
            "username": user.username,
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Login with phone number/email and password."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)

        return Response({
            "token": token.key,
            "username": user.username,
        })


class CheckAccountView(APIView):
    """Check if a phone number or email is already registered."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CheckAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data.get("phone_number")
        email = serializer.validated_data.get("email")

        if phone:
            exists = User.objects.filter(phone_number=phone).exists()
            identifier = phone
        else:
            exists = User.objects.filter(email=email).exists()
            identifier = email

        result = {"data": identifier, "is_registered": exists}
        if exists:
            try:
                user = (
                    User.objects.get(phone_number=phone)
                    if phone
                    else User.objects.get(email=email)
                )
                result["username"] = user.username
            except User.DoesNotExist:
                pass

        return Response(result)


class CheckUsernameView(APIView):
    """Check if a username is already taken."""
    permission_classes = [AllowAny]

    def get(self, request, username):
        is_taken = User.objects.filter(username=username).exists()
        return Response({"is_taken": is_taken})


class ProfileView(APIView):
    """Get or update current user profile."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserProfileSerializer(request.user).data)

    def patch(self, request):
        serializer = UserUpdateSerializer(
            request.user, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserProfileSerializer(request.user).data)


class ChangePasswordView(APIView):
    """Change password — requires old password verification."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(serializer.validated_data["old_password"]):
            return Response(
                {"error": "Wrong password"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        # Regenerate token after password change
        Token.objects.filter(user=user).delete()
        new_token = Token.objects.create(user=user)

        return Response({
            "message": "Password updated",
            "new_token": new_token.key,
        })


class CountriesView(APIView):
    """List all countries with flags."""
    permission_classes = [AllowAny]

    def get(self, request):
        countries = Countries.objects.all()
        return Response(CountrySerializer(countries, many=True).data)


class GuestTokenView(APIView):
    """Generate anonymous token for guest players."""
    permission_classes = [AllowAny]

    def post(self, request):
        from apps.game.models import ConnectionHistory

        anonym_token = str(uuid.uuid4())
        connection = ConnectionHistory.objects.create(
            anonym_token=anonym_token,
            status=ConnectionHistory.Status.ONLINE,
        )
        return Response({
            "token": anonym_token,
            "connection_id": connection.pk,
        })


class PasswordResetRequestView(APIView):
    """Request password reset — sends SMS/email code."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data.get("phone_number")
        email = serializer.validated_data.get("email")
        identifier = phone or email

        # Verify the account exists
        if phone and not User.objects.filter(phone_number=phone).exists():
            return Response(
                {"error": "Account not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if email and not User.objects.filter(email=email).exists():
            return Response(
                {"error": "Account not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if code already sent
        reset_key = f"reset_{identifier}"
        if request.session.get(reset_key):
            return Response(
                {"error": "A verification code has already been sent to this data."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Generate reset code
        import random
        code = f"{random.randint(1000, 9999)}"
        request.session[reset_key] = {"code": code}

        if settings.DEBUG:
            logger.info("DEBUG: Reset code for %s is %s", identifier, code)

        return Response({"message": "Verification code sent"})


class PasswordResetVerifyView(APIView):
    """Verify password reset SMS/email code."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data.get("phone_number")
        email = serializer.validated_data.get("email")
        verification_code = serializer.validated_data["verification_code"]
        identifier = phone or email

        reset_key = f"reset_{identifier}"
        session_data = request.session.get(reset_key)

        if not session_data:
            return Response(
                {"error": "No reset pending for this identifier"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stored_code = session_data.get("code", "")
        if settings.DEBUG:
            if verification_code != "0000" and verification_code != stored_code:
                return Response(
                    {"error": "Invalid verification code"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            if verification_code != stored_code:
                return Response(
                    {"error": "Invalid verification code"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Generate a reset token
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        user = (
            User.objects.get(phone_number=phone)
            if phone
            else User.objects.get(email=email)
        )
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # Clean up session
        del request.session[reset_key]
        request.session.modified = True

        return Response({
            "reset_link": f"/api/users/reset/confirm/{uidb64}/{token}/",
        })


class PasswordResetConfirmView(APIView):
    """Set new password using reset token."""
    permission_classes = [AllowAny]

    def post(self, request, uidb64, token):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_decode

        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {"error": "Invalid reset link"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"error": "Invalid or expired reset link"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        # Issue new token
        Token.objects.filter(user=user).delete()
        new_token = Token.objects.create(user=user)

        return Response({
            "new_token": new_token.key,
            "message": "Password reset successful",
        })
