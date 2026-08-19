"""Create a TEST superuser so a fresh dev/staging DB has a working admin.

⚠️  This runs in EVERY environment, production included. It is a DEV convenience:
  - idempotent — it never overwrites an existing admin (so changing the password
    in prod is safe; this migration won't reset it);
  - the password comes from TEST_ADMIN_PASSWORD (dev default below), so in prod
    set that env var to something strong — or better, delete this admin after
    creating your real one.

Login is by PHONE NUMBER (USERNAME_FIELD = 'phone_number'):
    phone: +998900000001   password: (TEST_ADMIN_PASSWORD or 'admin12345')
"""
import os

from django.contrib.auth.hashers import make_password
from django.db import migrations

ADMIN_PHONE = "+998900000001"
ADMIN_USERNAME = "testadmin"


def create_test_admin(apps, schema_editor):
    User = apps.get_model("users", "User")
    Countries = apps.get_model("users", "Countries")

    # Idempotent: never touch an existing account (don't clobber a prod password).
    if User.objects.filter(phone_number=ADMIN_PHONE).exists() or \
            User.objects.filter(username=ADMIN_USERNAME).exists():
        return

    password = os.environ.get("TEST_ADMIN_PASSWORD", "admin12345")

    kwargs = dict(
        username=ADMIN_USERNAME,
        phone_number=ADMIN_PHONE,
        password=make_password(password),
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    # country is a non-null FK; use an existing row if seeded, else let the
    # field default (Countries.get_default_pk) create the global default.
    country = Countries.objects.order_by("pk").first()
    if country is not None:
        kwargs["country_id"] = country.pk

    User.objects.create(**kwargs)


def remove_test_admin(apps, schema_editor):
    User = apps.get_model("users", "User")
    User.objects.filter(username=ADMIN_USERNAME, phone_number=ADMIN_PHONE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_alter_countries_options_alter_user_options_and_more"),
    ]

    operations = [
        migrations.RunPython(create_test_admin, remove_test_admin),
    ]
