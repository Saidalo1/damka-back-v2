"""Game consumer mixins — modular pieces of game logic."""
from apps.game.consumers.game.mixins.chat import ChatMixin
from apps.game.consumers.game.mixins.connection import ConnectionMixin
from apps.game.consumers.game.mixins.game_end import GameEndMixin
from apps.game.consumers.game.mixins.move import MoveMixin
from apps.game.consumers.game.mixins.rematch import RematchMixin
from apps.game.consumers.game.mixins.timer import TimerMixin

__all__ = [
    "ChatMixin",
    "ConnectionMixin",
    "GameEndMixin",
    "MoveMixin",
    "RematchMixin",
    "TimerMixin",
]
