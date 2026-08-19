import uuid

from django.contrib import admin as dj_admin
from django.contrib.admin import register
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.users.forms import CustomUserCreationForm
from apps.users.models import User, Countries


class UsernameOrPhoneAdminLoginForm(AdminAuthenticationForm):
    """Relabel the admin login field — it now accepts a username or a phone."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Username or phone")


dj_admin.site.login_form = UsernameOrPhoneAdminLoginForm


@register(User)
class CustomUserAdmin(ModelAdmin, UserAdmin):
    add_form = CustomUserCreationForm
    fieldsets = (None, {"fields": ('phone_number', 'username')}), (
        _("Personal info"), {"fields": ("first_name", "last_name", "email", "country", "avatar")}), (
        _("Permissions"),
        {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            ),
        },
    ), (_("Important dates"), {"fields": ("last_login", "date_joined")}), (
        _("Game information"), {"fields": ('bullet_rating', 'blitz_rating', 'rapid_rating')})

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": fieldsets[0][1]['fields'][:4] + fieldsets[1][1]['fields'] + ("password1", "password2"),
            },
        ),
    )

    list_display = 'username', 'first_name', 'last_name', 'phone_number', 'is_active', 'is_staff', 'is_superuser'
    readonly_fields = 'date_joined', 'last_login'

    def save_model(self, request, obj, form, change):
        if not obj.username:
            unique_username = str(uuid.uuid4().hex)
            while User.objects.filter(username=unique_username).exists():
                unique_username = str(uuid.uuid4().hex)
            obj.username = unique_username
        super().save_model(request, obj, form, change)


@register(Countries)
class CountriesAdmin(ModelAdmin):
    list_display = 'title', 'code'
    search_fields = 'title', 'code'
