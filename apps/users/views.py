"""
User views — authentication, profile management.

Endpoints:
- POST /api/users/register/     — request SMS code
- POST /api/users/verify/       — verify SMS + create account
- POST /api/users/login/        — login with phone + password
- GET  /api/users/profile/      — get current user profile
- PATCH /api/users/profile/     — update profile
- POST /api/users/password/     — change password
- POST /api/users/check/        — check if account exists
- GET  /api/users/countries/    — list all countries
- POST /api/users/guest-token/  — generate anonymous token
"""
import logging

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
)

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    """Step 1: Request SMS verification code for phone number."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone_number"]

        if User.objects.filter(phone_number=phone).exists():
            return Response(
                {"error": "Phone number already registered"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # TODO: Generate code, send SMS via Eskiz.uz, store in Redis
        # For now, return success stub
        logger.info("SMS requested for %s", phone)
        return Response({"message": "SMS code sent", "phone_number": phone})


class SMSVerifyView(APIView):
    """Step 2: Verify SMS code and create account."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SMSVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone_number"]
        code = serializer.validated_data["code"]
        password = serializer.validated_data["password"]

        # TODO: Verify code from Redis
        # For now, accept any code in DEBUG mode
        if not settings.DEBUG:
            return Response(
                {"error": "SMS verification not implemented yet"},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        # Create user
        user = User.objects.create_user(
            username=phone,  # Will be updated by client
            phone_number=phone,
            password=password,
        )
        token = Token.objects.create(user=user)

        return Response({
            "token": token.key,
            "user": UserProfileSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Login with phone number and password."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)

        return Response({
            "token": token.key,
            "user": UserProfileSerializer(user).data,
        })


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
                user = User.objects.get(
                    phone_number=phone) if phone else User.objects.get(email=email)
                result["username"] = user.username
            except User.DoesNotExist:
                pass

        return Response(result)


class CountriesView(APIView):
    """List all countries with flags."""
    permission_classes = [AllowAny]

    def get(self, request):
        countries = Countries.objects.all()
        return Response(CountrySerializer(countries, many=True).data)


class GuestTokenView(APIView):
    """
    Generate anonymous token for guest players.

    Creates a ConnectionHistory entry and returns its token.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from apps.game.models import ConnectionHistory
        import uuid

        anonym_token = str(uuid.uuid4())
        connection = ConnectionHistory.objects.create(
            anonym_token=anonym_token,
            status=ConnectionHistory.Status.ONLINE,
        )
        return Response({
            "token": anonym_token,
            "connection_id": connection.pk,
        })
