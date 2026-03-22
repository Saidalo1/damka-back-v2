"""
Chat mixin — handles in-game chat messages.

Saves messages to DB with XOR constraint (authorized_sender OR guest_sender)
and broadcasts to both players.
"""
import logging

from channels.db import database_sync_to_async
from django.utils import timezone

from shared.django import ColorChoices

logger = logging.getLogger(__name__)


class ChatMixin:
    """Handles in-game chat messages."""

    async def handle_chat(self, message: str):
        """
        Process a chat message from a player.

        Args:
            message: the chat text content.
        """
        if not message or not isinstance(message, str):
            return

        # Truncate to 255 chars (model max_length)
        message = message.strip()[:255]
        if not message:
            return

        # Save to DB
        chat_entry = await self._save_chat_message(message)

        # Broadcast to both players
        chat_data = {
            "event": "chat",
            "message": message,
            "sender_color": self.player_color,
            "timestamp": chat_entry["timestamp"],
        }

        # Send to the game group (both players receive it)
        await self.channel_layer.group_send(
            str(self.game.id),
            {
                "type": "game.message",
                "data": chat_data,
                "broadcast": True,
            },
        )

    @database_sync_to_async
    def _save_chat_message(self, message: str) -> dict:
        """Save chat message to DB."""
        from apps.game.models import Chat

        user = self.scope.get("user")

        # Determine sender type
        if user and user.is_authenticated:
            chat = Chat.objects.create(
                game=self.game,
                authorized_sender=user,
                message=message,
            )
        else:
            # For anonymous users, use connection from ConnectionMixin
            connection = getattr(self, "connection", None)
            if connection is None:
                logger.warning("Chat: no connection for guest sender, skipping save")
                return {"timestamp": str(timezone.now()), "sender_color": self.player_color}
            chat = Chat.objects.create(
                game=self.game,
                guest_sender=connection,
                message=message,
            )

        return {
            "timestamp": str(chat.timestamp),
            "sender_color": self.player_color,
        }
