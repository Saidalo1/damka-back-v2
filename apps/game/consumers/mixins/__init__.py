"""Consumer mixins — modular pieces of game consumer logic."""
from apps.game.consumers.mixins.chat import ChatMixin
from apps.game.consumers.mixins.connection import ConnectionMixin
from apps.game.consumers.mixins.game_end import GameEndMixin
from apps.game.consumers.mixins.move import MoveMixin
from apps.game.consumers.mixins.rematch import RematchMixin
from apps.game.consumers.mixins.timer import TimerMixin

__all__ = [
    "ChatMixin",
    "ConnectionMixin",
    "GameEndMixin",
    "MoveMixin",
    "RematchMixin",
    "TimerMixin",
]
