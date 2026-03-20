"""
Users admin — Unfold-powered admin for User and Countries models.

Replaces default UserAdmin with Unfold styling + proper field layout.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from apps.users.models import User, Countries


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    """Custom user admin with ELO ratings and avatar preview."""
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    list_display = (
        "username", "phone_number",
        "bullet_rating", "blitz_rating", "rapid_rating",
        "avatar_preview", "is_active", "date_joined",
    )
    list_filter = ("is_active", "is_staff", "country")
    search_fields = ("username", "phone_number", "email")
    ordering = ("-date_joined",)
    list_per_page = 25

    fieldsets = (
        ("Account", {
            "fields": ("username", "phone_number", "email", "password"),
        }),
        ("Personal Info", {
            "fields": ("first_name", "last_name", "avatar", "country"),
        }),
        ("ELO Ratings", {
            "fields": (
                ("bullet_rating", "blitz_rating", "rapid_rating"),
                ("bullet_updated_at", "blitz_updated_at", "rapid_updated_at"),
            ),
        }),
        ("Integrations", {
            "fields": ("chat_id",),
            "classes": ("collapse",),
        }),
        ("Permissions", {
            "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("last_login", "date_joined"),
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "phone_number", "password1", "password2"),
        }),
    )

    @admin.display(description="Avatar")
    def avatar_preview(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" style="height:28px; width:28px; border-radius:50%; object-fit:cover;" />',
                obj.avatar.url,
            )
        return "—"


@admin.register(Countries)
class CountriesAdmin(ModelAdmin):
    """Admin for country reference data."""
    list_display = ("title", "code", "flag_preview")
    search_fields = ("title", "code")
    list_per_page = 50
    ordering = ("title",)

    @admin.display(description="Flag")
    def flag_preview(self, obj):
        if obj.flag:
            return format_html(
                '<img src="{}" style="height:20px;" />', obj.flag.url,
            )
        return "—"
