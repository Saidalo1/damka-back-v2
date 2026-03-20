"""Serializers for the users app — registration, login, profile.

Matches v1 API contract exactly:
- Register: phone_number/email + password → sends SMS
- SMS Verify: phone_number/email + user_entered_code → creates user, returns token
- Login: phone_number/email + password → returns token
"""
from django.core.validators import RegexValidator
from rest_framework import serializers

from apps.users.models import User, Countries


class RegisterSerializer(serializers.Serializer):
    """Step 1: request SMS code for registration (phone/email + password)."""
    phone_number = serializers.CharField(max_length=13, required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_null=True)
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)

    def validate(self, data):
        if not data.get("phone_number") and not data.get("email"):
            raise serializers.ValidationError("Provide phone_number or email")
        return data


class SMSVerifySerializer(serializers.Serializer):
    """Step 2: verify SMS code to complete registration."""
    phone_number = serializers.CharField(max_length=13, required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_null=True)
    user_entered_code = serializers.CharField(
        max_length=4,
        validators=[
            RegexValidator(r'^\d{4}$', 'Verification code must be a 4-digit number')
        ],
    )

    def validate(self, data):
        if not data.get("phone_number") and not data.get("email"):
            raise serializers.ValidationError("Provide phone_number or email")
        return data


class LoginSerializer(serializers.Serializer):
    """Login with phone number/email + password."""
    phone_number = serializers.CharField(max_length=13, required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_null=True)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        if not data.get("phone_number") and not data.get("email"):
            raise serializers.ValidationError("Provide phone_number or email")

        from django.contrib.auth import authenticate

        # Try phone login first, then email
        user = None
        if data.get("phone_number"):
            user = authenticate(
                username=data["phone_number"],
                password=data["password"],
            )
        elif data.get("email"):
            # Find user by email, then authenticate
            try:
                email_user = User.objects.get(email=data["email"])
                user = authenticate(
                    username=email_user.phone_number or email_user.username,
                    password=data["password"],
                )
            except User.DoesNotExist:
                pass

        if not user:
            raise serializers.ValidationError("Invalid credentials")
        data["user"] = user
        return data


class CheckAccountSerializer(serializers.Serializer):
    """Check if phone number or email is already registered."""
    phone_number = serializers.CharField(max_length=13, required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_null=True)

    def validate(self, data):
        if not data.get("phone_number") and not data.get("email"):
            raise serializers.ValidationError("Provide phone_number or email")
        return data


class PasswordResetRequestSerializer(serializers.Serializer):
    """Request password reset — sends SMS/email code."""
    phone_number = serializers.CharField(max_length=13, required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_null=True)

    def validate(self, data):
        if not data.get("phone_number") and not data.get("email"):
            raise serializers.ValidationError("Provide phone_number or email")
        return data


class PasswordResetVerifySerializer(serializers.Serializer):
    """Verify password reset SMS code."""
    phone_number = serializers.CharField(max_length=13, required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_null=True)
    verification_code = serializers.CharField(
        max_length=4,
        validators=[
            RegexValidator(r'^\d{4}$', 'Verification code must be a 4-digit number')
        ],
    )

    def validate(self, data):
        if not data.get("phone_number") and not data.get("email"):
            raise serializers.ValidationError("Provide phone_number or email")
        return data


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Confirm password reset with new password."""
    new_password = serializers.CharField(write_only=True, min_length=8, max_length=128)


class UserProfileSerializer(serializers.ModelSerializer):
    """User profile — read-only representation."""
    ratings = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name",
            "phone_number", "email", "avatar",
            "ratings", "country", "date_joined",
        ]
        read_only_fields = fields

    def get_ratings(self, obj):
        return {
            "bullet": obj.bullet_rating,
            "blitz": obj.blitz_rating,
            "rapid": obj.rapid_rating,
        }

    def get_country(self, obj):
        if not obj.country:
            return None
        return {
            "title": obj.country.title,
            "code": obj.country.code,
            "flag": obj.country.flag.url if obj.country.flag else None,
        }


class UserUpdateSerializer(serializers.ModelSerializer):
    """Update user profile (username, avatar, country, names)."""

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "avatar", "country"]
        extra_kwargs = {
            "username": {"required": False},
            "first_name": {"required": False},
            "last_name": {"required": False},
            "avatar": {"required": False},
            "country": {"required": False},
        }


class ChangePasswordSerializer(serializers.Serializer):
    """Change password — requires old password."""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=6, write_only=True)


class CountrySerializer(serializers.ModelSerializer):
    """Country list serializer."""

    class Meta:
        model = Countries
        fields = ["id", "title", "code", "flag"]
