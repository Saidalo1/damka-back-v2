"""
Game admin — Unfold-powered admin for Game, GameTypes, and related models.

Provides: list views with filters, search, inline time controls,
and human-readable display columns.
"""
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.game.models import Game, Chat
from apps.game.models.handbook import GameTypes, GameTypesTime, ConnectionHistory


# ── Inlines ──────────────────────────────────────────────────────

class GameTypesTimeInline(TabularInline):
    """Inline for time control configs within a GameType."""
    model = GameTypesTime
    extra = 1
    fields = ("title", "time", "increment")


class ChatInline(TabularInline):
    """Inline for chat messages within a Game."""
    model = Chat
    extra = 0
    readonly_fields = ("authorized_sender", "guest_sender", "message", "timestamp")
    fields = ("message", "authorized_sender", "guest_sender", "timestamp")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


# ── GameTypes ────────────────────────────────────────────────────

@admin.register(GameTypes)
class GameTypesAdmin(ModelAdmin):
    """Admin for game categories (Bullet, Blitz, Rapid)."""
    list_display = ("title", "separate_var", "time_controls_count", "icon_preview")
    search_fields = ("title",)
    inlines = [GameTypesTimeInline]

    @admin.display(description="Time Controls")
    def time_controls_count(self, obj):
        return obj.time_controls.count()

    @admin.display(description="Icon")
    def icon_preview(self, obj):
        if obj.icon:
            return format_html('<img src="{}" style="height:24px;" />', obj.icon.url)
        return "—"


# ── GameTypesTime ────────────────────────────────────────────────

@admin.register(GameTypesTime)
class GameTypesTimeAdmin(ModelAdmin):
    """Admin for individual time control configurations."""
    list_display = ("title", "type", "formatted_time", "increment")
    list_filter = ("type",)
    search_fields = ("title",)

    @admin.display(description="Time")
    def formatted_time(self, obj):
        minutes = obj.time // 60
        seconds = obj.time % 60
        if seconds:
            return f"{minutes}m {seconds}s"
        return f"{minutes}m"


# ── Game ─────────────────────────────────────────────────────────

@admin.register(Game)
class GameAdmin(ModelAdmin):
    """Admin for individual games — the main model."""
    list_display = (
        "short_id",
        "type_of_game",
        "white_player",
        "black_player",
        "color_win_display",
        "has_ended",
        "formatted_time_white",
        "formatted_time_black",
        "created_at",
    )
    list_filter = ("has_ended", "type_of_game", "color_win", "type")
    search_fields = ("id",)
    readonly_fields = (
        "id", "fen", "history", "last_move",
        "created_at", "started_time", "finished_time",
        "first_move_check_task_id", "move_check_task_id",
    )
    list_per_page = 25
    date_hierarchy = "created_at"

    fieldsets = (
        ("Game Info", {
            "fields": ("id", "type_of_game", "type", "private_key"),
        }),
        ("Players", {
            "fields": (
                ("white", "white_anonym"),
                ("black", "black_anonym"),
            ),
        }),
        ("State", {
            "fields": (
                "fen", "turn", "last_move", "history",
                "has_started", "has_ended", "all_players_left",
            ),
        }),
        ("Result", {
            "fields": (
                "color_win", "authorized_winner", "guest_winner",
                "rating_calculated",
            ),
        }),
        ("Timers", {
            "fields": (
                ("remaining_time_white", "remaining_time_black"),
                ("initial_time_white", "initial_time_black"),
                "increment", "last_move_time",
            ),
        }),
        ("First Move Tracking", {
            "fields": (
                "first_color_first_move_done",
                "second_color_first_move_done",
                "first_move_check_task_id",
                "first_move_check_task_time",
            ),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "started_time", "finished_time"),
        }),
    )

    inlines = [ChatInline]

    @admin.display(description="ID")
    def short_id(self, obj):
        return str(obj.id)[:8] + "…"

    @admin.display(description="White")
    def white_player(self, obj):
        if obj.white:
            return obj.white.username
        if obj.white_anonym:
            return f"Guest #{obj.white_anonym_id}"
        return "—"

    @admin.display(description="Black")
    def black_player(self, obj):
        if obj.black:
            return obj.black.username
        if obj.black_anonym:
            return f"Guest #{obj.black_anonym_id}"
        return "—"

    @admin.display(description="Winner")
    def color_win_display(self, obj):
        if obj.color_win is None:
            return "—"
        labels = {1: "⚫ Black", 2: "⚪ White", 0: "Draw", 3: "Cancelled"}
        return labels.get(obj.color_win, str(obj.color_win))

    @admin.display(description="W Time")
    def formatted_time_white(self, obj):
        if obj.remaining_time_white is None:
            return "—"
        return f"{int(obj.remaining_time_white)}s"

    @admin.display(description="B Time")
    def formatted_time_black(self, obj):
        if obj.remaining_time_black is None:
            return "—"
        return f"{int(obj.remaining_time_black)}s"


# ── Chat ─────────────────────────────────────────────────────────

@admin.register(Chat)
class ChatAdmin(ModelAdmin):
    """Admin for in-game chat messages."""
    list_display = ("game_short_id", "sender_display", "message_preview", "timestamp")
    list_filter = ("timestamp",)
    readonly_fields = ("game", "authorized_sender", "guest_sender", "message", "timestamp")
    list_per_page = 50

    @admin.display(description="Game")
    def game_short_id(self, obj):
        return str(obj.game_id)[:8] + "…"

    @admin.display(description="Sender")
    def sender_display(self, obj):
        if obj.authorized_sender:
            return obj.authorized_sender.username
        if obj.guest_sender:
            return f"Guest #{obj.guest_sender_id}"
        return "—"

    @admin.display(description="Message")
    def message_preview(self, obj):
        return obj.message[:50] + "…" if len(obj.message) > 50 else obj.message


# ── ConnectionHistory ────────────────────────────────────────────

@admin.register(ConnectionHistory)
class ConnectionHistoryAdmin(ModelAdmin):
    """Admin for anonymous player connections."""
    list_display = ("short_token", "status_display", "rating", "was_failed", "created_at")
    list_filter = ("status", "was_failed")
    search_fields = ("anonym_token",)
    readonly_fields = ("anonym_token", "created_at")
    list_per_page = 50

    @admin.display(description="Token")
    def short_token(self, obj):
        return obj.anonym_token[:12] + "…"

    @admin.display(description="Status")
    def status_display(self, obj):
        return "🟢 Online" if obj.status == 1 else "⚫ Offline"
