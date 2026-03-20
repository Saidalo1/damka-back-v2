"""
Data migration — seed game types (Bullet, Blitz, Rapid) and time controls.

This ensures a fresh database has the default game type configurations
without requiring manual admin entry.
"""
from django.db import migrations


def seed_game_types(apps, schema_editor):
    """Create default game types and time control configurations."""
    GameTypes = apps.get_model("game", "GameTypes")
    GameTypesTime = apps.get_model("game", "GameTypesTime")

    # Game types
    bullet, _ = GameTypes.objects.get_or_create(
        separate_var="bullet", defaults={"title": "Bullet"},
    )
    blitz, _ = GameTypes.objects.get_or_create(
        separate_var="blitz", defaults={"title": "Blitz"},
    )
    rapid, _ = GameTypes.objects.get_or_create(
        separate_var="rapid", defaults={"title": "Rapid"},
    )

    # Time controls — get_or_create by type + time + increment
    time_controls = [
        # Bullet
        (bullet, "1+0", 60, 0),
        (bullet, "2+1", 120, 1),
        # Blitz
        (blitz, "3+0", 180, 0),
        (blitz, "5+0", 300, 0),
        (blitz, "5+3", 300, 3),
        # Rapid
        (rapid, "10+0", 600, 0),
        (rapid, "15+10", 900, 10),
    ]

    for game_type, title, time, increment in time_controls:
        GameTypesTime.objects.get_or_create(
            type=game_type, time=time, increment=increment,
            defaults={"title": title},
        )


def reverse_seed(apps, schema_editor):
    """Reverse migration — remove seeded data."""
    GameTypes = apps.get_model("game", "GameTypes")
    GameTypes.objects.filter(
        separate_var__in=["bullet", "blitz", "rapid"],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0003_alter_game_remaining_time_black_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_game_types, reverse_seed),
    ]
