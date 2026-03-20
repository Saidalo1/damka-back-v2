"""
Management command to seed test data for development and WS testing.

Creates:
- 2 test users with auth tokens
- Game types (Bullet, Blitz, Rapid) with time controls
- 1 test game between the two users

Usage:
  python manage.py seed_test_data
"""
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from apps.game.models import Game, GameTypes, GameTypesTime, GameTypeChoices
from apps.users.models import User


class Command(BaseCommand):
    help = "Seed test data for development (users, game types, test game)"

    def handle(self, *args, **options):
        self.stdout.write("Seeding test data...")

        # === Game Types ===
        bullet, _ = GameTypes.objects.get_or_create(
            separate_var="bullet",
            defaults={"title": "Bullet"},
        )
        blitz, _ = GameTypes.objects.get_or_create(
            separate_var="blitz",
            defaults={"title": "Blitz"},
        )
        rapid, _ = GameTypes.objects.get_or_create(
            separate_var="rapid",
            defaults={"title": "Rapid"},
        )
        self.stdout.write(f"  ✓ Game types: {bullet}, {blitz}, {rapid}")

        # === Time Controls ===
        bullet_1_0, _ = GameTypesTime.objects.get_or_create(
            type=bullet, time=60, increment=0,
            defaults={"title": "1+0"},
        )
        bullet_2_1, _ = GameTypesTime.objects.get_or_create(
            type=bullet, time=120, increment=1,
            defaults={"title": "2+1"},
        )
        blitz_3_0, _ = GameTypesTime.objects.get_or_create(
            type=blitz, time=180, increment=0,
            defaults={"title": "3+0"},
        )
        blitz_5_0, _ = GameTypesTime.objects.get_or_create(
            type=blitz, time=300, increment=0,
            defaults={"title": "5+0"},
        )
        blitz_5_3, _ = GameTypesTime.objects.get_or_create(
            type=blitz, time=300, increment=3,
            defaults={"title": "5+3"},
        )
        rapid_10_0, _ = GameTypesTime.objects.get_or_create(
            type=rapid, time=600, increment=0,
            defaults={"title": "10+0"},
        )
        rapid_15_10, _ = GameTypesTime.objects.get_or_create(
            type=rapid, time=900, increment=10,
            defaults={"title": "15+10"},
        )
        self.stdout.write(f"  ✓ Time controls created")

        # === Test Users ===
        user1, created1 = User.objects.get_or_create(
            phone_number="+998901234567",
            defaults={
                "username": "test_white",
                "first_name": "White",
                "last_name": "Player",
            },
        )
        if created1:
            user1.set_password("testpass123")
            user1.save()

        user2, created2 = User.objects.get_or_create(
            phone_number="+998901234568",
            defaults={
                "username": "test_black",
                "first_name": "Black",
                "last_name": "Player",
            },
        )
        if created2:
            user2.set_password("testpass123")
            user2.save()

        self.stdout.write(f"  ✓ Users: {user1.username}, {user2.username}")

        # === Auth Tokens ===
        token1, _ = Token.objects.get_or_create(user=user1)
        token2, _ = Token.objects.get_or_create(user=user2)
        self.stdout.write(f"  ✓ Token (white): {token1.key}")
        self.stdout.write(f"  ✓ Token (black): {token2.key}")

        # === Test Game ===
        game, created = Game.objects.get_or_create(
            white=user1,
            black=user2,
            has_ended=False,
            defaults={
                "type": GameTypeChoices.MATCHMAKING,
                "type_of_game": blitz_5_0,
                "fen": "startpos",
                "turn": 2,  # White starts
                "initial_time_white": 300,
                "initial_time_black": 300,
                "remaining_time_white": 300,
                "remaining_time_black": 300,
                "increment": 0,
                "created_by_authorized": user1,
            },
        )

        if created:
            self.stdout.write(f"  ✓ Test game: {game.id}")
        else:
            self.stdout.write(f"  ✓ Existing test game: {game.id}")

        # === Summary ===
        self.stdout.write(self.style.SUCCESS("\n=== SEED COMPLETE ==="))
        self.stdout.write(f"\nTo test with WS scripts:")
        self.stdout.write(f"  python test/play_random.py --game-id {game.id} --token {token1.key}")
        self.stdout.write(f"  python test/play_random.py --game-id {game.id} --token {token2.key}")
