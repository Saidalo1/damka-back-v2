"""
Data migration — align game types seed data with v1 production.

Updates time control titles and adds missing entries to match
the production database at damka.uz exactly.
"""
from django.db import migrations


def align_with_v1(apps, schema_editor):
    """Update game types seed data to match v1 production exactly."""
    GameTypes = apps.get_model("game", "GameTypes")
    GameTypesTime = apps.get_model("game", "GameTypesTime")

    bullet = GameTypes.objects.get(separate_var="bullet")
    blitz = GameTypes.objects.get(separate_var="blitz")
    rapid = GameTypes.objects.get(separate_var="rapid")

    # --- Bullet ---
    # Update "1+0" → "1 min"
    GameTypesTime.objects.filter(
        type=bullet, time=60, increment=0,
    ).update(title="1 min")

    # Add missing "1+1" (60s, +1s increment)
    GameTypesTime.objects.get_or_create(
        type=bullet, time=60, increment=1,
        defaults={"title": "1+1"},
    )

    # --- Blitz ---
    # Update "3+0" → "3 min"
    GameTypesTime.objects.filter(
        type=blitz, time=180, increment=0,
    ).update(title="3 min")

    # Add missing "3+2" (180s, +2s increment)
    GameTypesTime.objects.get_or_create(
        type=blitz, time=180, increment=2,
        defaults={"title": "3+2"},
    )

    # Update "5+0" → "5 min"
    GameTypesTime.objects.filter(
        type=blitz, time=300, increment=0,
    ).update(title="5 min")

    # Remove "5+3" (does not exist in v1 production)
    GameTypesTime.objects.filter(
        type=blitz, time=300, increment=3,
    ).delete()

    # --- Rapid ---
    # Update "10+0" → "10 min"
    GameTypesTime.objects.filter(
        type=rapid, time=600, increment=0,
    ).update(title="10 min")

    # "15+10" stays the same

    # Add missing "30 min" (1800s, no increment)
    GameTypesTime.objects.get_or_create(
        type=rapid, time=1800, increment=0,
        defaults={"title": "30 min"},
    )


def reverse_align(apps, schema_editor):
    """Reverse — restore v2 original titles."""
    GameTypesTime = apps.get_model("game", "GameTypesTime")
    GameTypes = apps.get_model("game", "GameTypes")

    bullet = GameTypes.objects.get(separate_var="bullet")
    blitz = GameTypes.objects.get(separate_var="blitz")
    rapid = GameTypes.objects.get(separate_var="rapid")

    # Revert title changes
    GameTypesTime.objects.filter(type=bullet, time=60, increment=0).update(title="1+0")
    GameTypesTime.objects.filter(type=blitz, time=180, increment=0).update(title="3+0")
    GameTypesTime.objects.filter(type=blitz, time=300, increment=0).update(title="5+0")
    GameTypesTime.objects.filter(type=rapid, time=600, increment=0).update(title="10+0")

    # Remove added entries
    GameTypesTime.objects.filter(type=bullet, time=60, increment=1).delete()
    GameTypesTime.objects.filter(type=blitz, time=180, increment=2).delete()
    GameTypesTime.objects.filter(type=rapid, time=1800, increment=0).delete()

    # Re-add "5+3"
    GameTypesTime.objects.get_or_create(
        type=blitz, time=300, increment=3,
        defaults={"title": "5+3"},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0004_seed_game_types"),
    ]

    operations = [
        migrations.RunPython(align_with_v1, reverse_align),
    ]
