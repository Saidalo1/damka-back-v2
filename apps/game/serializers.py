"""Serializers for the game app — game types, leaderboard."""
from rest_framework import serializers

from apps.game.models import Game
from apps.game.models.handbook import GameTypes, GameTypesTime


class GameTypesTimeSerializer(serializers.ModelSerializer):
    """Time control option for a game type."""

    class Meta:
        model = GameTypesTime
        fields = ["id", "title", "time", "increment"]


class GameTypesSerializer(serializers.ModelSerializer):
    """Game type (Bullet/Blitz/Rapid) with time control options."""
    time_controls = GameTypesTimeSerializer(many=True, read_only=True)

    class Meta:
        model = GameTypes
        fields = ["id", "title", "icon", "separate_var", "time_controls"]


class ActiveGameSerializer(serializers.ModelSerializer):
    """Minimal game info for active game check."""
    has_opponent = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = ["id", "type", "private_key", "has_opponent"]

    def get_has_opponent(self, obj):
        white_present = obj.white_id is not None or obj.white_anonym_id is not None
        black_present = obj.black_id is not None or obj.black_anonym_id is not None
        return white_present and black_present


class LeaderboardEntrySerializer(serializers.Serializer):
    """Single entry in the leaderboard."""
    id = serializers.IntegerField()
    username = serializers.CharField()
    rating = serializers.IntegerField()
    place = serializers.IntegerField()
    country = serializers.DictField(required=False)
    is_you = serializers.BooleanField(default=False)
