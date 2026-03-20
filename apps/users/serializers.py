"""Serializers for the users app — registration, login, profile."""
from django.contrib.auth import authenticate
from rest_framework import serializers

from apps.users.models import User, Countries


class RegisterSerializer(serializers.Serializer):
    """Step 1: request SMS code for registration."""
    phone_number = serializers.CharField(max_length=13)
    username = serializers.CharField(max_length=150)


class SMSVerifySerializer(serializers.Serializer):
    """Step 2: verify SMS code + set password."""
    phone_number = serializers.CharField(max_length=13)
    code = serializers.CharField(max_length=6)
    password = serializers.CharField(min_length=6, write_only=True)


class LoginSerializer(serializers.Serializer):
    """Login with phone number + password."""
    phone_number = serializers.CharField(max_length=13)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(
            username=data["phone_number"],
            password=data["password"],
        )
        if not user:
            raise serializers.ValidationError("Invalid credentials")
        data["user"] = user
        return data


class CheckAccountSerializer(serializers.Serializer):
    """Check if phone number or email is already registered."""
    phone_number = serializers.CharField(max_length=13, required=False)
    email = serializers.EmailField(required=False)

    def validate(self, data):
        if not data.get("phone_number") and not data.get("email"):
            raise serializers.ValidationError("Provide phone_number or email")
        return data


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


class ChangePasswordSerializer(serializers.Serializer):
    """Change password — requires old password."""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=6, write_only=True)


class CountrySerializer(serializers.ModelSerializer):
    """Country list serializer."""

    class Meta:
        model = Countries
        fields = ["id", "title", "code", "flag"]
