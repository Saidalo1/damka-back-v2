"""
Move mixin — handles move validation, board update, and broadcasting.

Replaces v1's move handling inlined in GameConsumer (part of 783 lines).
Uses event-based protocol: only sends delta (changed fields) per move.
"""
import json
import logging

from channels.db import database_sync_to_async
from django.utils import timezone

from shared.django import ColorChoices
from apps.game.services.board import create_board, get_legal_moves_as_lists, get_turn_color, make_move

logger = logging.getLogger(__name__)


class MoveMixin:
    """Handles move validation, execution, and broadcasting."""

    async def handle_move(self, message: list[int]):
        """
        Process a move from a player.

        Args:
            message: square_list [from_sq, to_sq, ...] from frontend.
        """
        # Capture timestamp BEFORE any DB queries
        # This ensures DB/Redis overhead is NOT counted as thinking time
        move_received_at = timezone.now()

        # Refresh game from DB to avoid stale state
        await self._refresh_game()

        # Validate it's this player's turn
        current_turn = get_turn_color(self.board)
        if current_turn != self.player_color:
            await self.send_json({"event": "error", "message": "Not your turn"})
            return

        if self.game.has_ended:
            await self.send_json({"event": "error", "message": "Game has ended"})
            return

        # Execute the move on the board
        try:
            move_result = make_move(self.board, message)
        except ValueError as e:
            await self.send_json({"event": "error", "message": str(e)})
            return

        # Update captured pieces count
        if move_result["is_capture"]:
            if self.player_color == ColorChoices.white:
                self.game.captured_pieces_count_by_white += move_result["captured_count"]
            else:
                self.game.captured_pieces_count_by_black += move_result["captured_count"]

        # Build PDN history entry
        history = json.loads(self.game.history) if self.game.history else {}
        move_number = len(history) + 1
        pdn_entry = {move_result["pdn"]: move_result["fen"]}

        # Track first move
        if not self.game.first_color_first_move_done and self.player_color == ColorChoices.white:
            self.game.first_color_first_move_done = True
        elif not self.game.second_color_first_move_done and self.player_color == ColorChoices.black:
            self.game.second_color_first_move_done = True

        # Update game state in DB
        await self._update_game_after_move(move_result, history, pdn_entry, move_number, message, move_received_at)

        # Check game over
        if move_result["game_over"]:
            await self._handle_game_over_by_board(move_result["winner"])
            return

        # Cancel previous timer, start new one
        await self.cancel_current_timer()
        await self.start_move_timer()

        # Send delta update to both players
        await self._broadcast_move(move_result, pdn_entry, message)

    async def _broadcast_move(self, move_result: dict, pdn_entry: dict, last_move: list[int]):
        """Send move event to both players — delta only, not full state."""
        next_turn = move_result["turn"]

        # Get possible moves for the player whose turn it is
        possible_moves = get_legal_moves_as_lists(self.board)

        # Base move data (shared between both players)
        base_data = {
            "event": "move",
            "fen": move_result["fen"],
            "turn": next_turn,
            "pdn": pdn_entry,
            "last_move": last_move,
            "times": {
                "white": int(self.game.remaining_time_white or 0),
                "black": int(self.game.remaining_time_black or 0),
            },
            "captured": {
                "white": self.game.captured_pieces_count_by_white,
                "black": self.game.captured_pieces_count_by_black,
            },
        }

        # Send to each player individually (not group_send)
        # Player whose turn → gets possible_moves
        # Player who just moved → no possible_moves
        for color in [ColorChoices.white, ColorChoices.black]:
            player_data = {**base_data}
            if color == next_turn:
                player_data["possible_moves"] = possible_moves
            await self._send_to_player(color, player_data)

    async def _send_to_player(self, color: int, data: dict):
        """Send message directly to a specific player by color."""
        if color == self.player_color:
            await self.send_json(data)
        else:
            # Send to opponent via channel layer group
            await self.channel_layer.group_send(
                str(self.game.id),
                {"type": "game.message", "data": data, "target_color": color},
            )

    async def game_message(self, event):
        """
        Handle game.message from channel layer — filter by target color.

        Also syncs local board state when receiving opponent's move.
        Supports broadcast=True for messages that go to all players (chat, rematch).
        """
        # Broadcast messages go to everyone
        if event.get("broadcast"):
            data = event["data"]
            await self.send_json(data)
            return

        # Targeted messages — filter by color
        if event.get("target_color") != self.player_color:
            return

        data = event["data"]

        # Sync board state when opponent made a move
        if data.get("event") == "move" and data.get("fen"):
            self.board = create_board(data["fen"])

        await self.send_json(data)

    @database_sync_to_async
    def _refresh_game(self):
        """Refresh game state from DB to avoid stale data between players."""
        from apps.game.models import Game
        self.game = Game.objects.select_related(
            "white", "black", "type_of_game", "type_of_game__type",
        ).get(id=self.game.id)
        # Rebuild board from latest FEN
        self.board = create_board(self.game.fen)

    @database_sync_to_async
    def _update_game_after_move(
        self, move_result: dict, history: dict, pdn_entry: dict,
        move_number: int, last_move: list[int], move_received_at
    ):
        """Update game record in DB after a valid move."""
        # Use the timestamp from when the move was received (before DB queries)
        # NOT timezone.now() — that would include DB/Redis processing overhead

        # Calculate time spent on this move
        if self.game.last_move_time:
            elapsed = (move_received_at - self.game.last_move_time).total_seconds()
        else:
            elapsed = 0

        # Update remaining time for the moving player (only after first move)
        # NOTE: Do NOT use int() here — truncation loses ~0.7s per move,
        # accumulating to 14+ seconds over a full game.
        # Round to int only when broadcasting to the client.
        if self.player_color == ColorChoices.white and self.game.first_color_first_move_done:
            self.game.remaining_time_white = max(
                0,
                self.game.remaining_time_white - elapsed + self.game.increment
            )
        elif self.player_color == ColorChoices.black and self.game.second_color_first_move_done:
            self.game.remaining_time_black = max(
                0,
                self.game.remaining_time_black - elapsed + self.game.increment
            )

        # Update game fields
        self.game.fen = move_result["fen"]
        self.game.turn = move_result["turn"]
        self.game.last_move = last_move
        self.game.last_move_time = move_received_at  # When player sent the move

        # Update history (JSON string in TextField)
        history[str(move_number)] = pdn_entry
        self.game.history = json.dumps(history)

        # Reset draw offers on move
        self.game.white_draw_offer = False
        self.game.black_draw_offer = False

        self.game.save(update_fields=[
            "fen", "turn", "last_move", "last_move_time", "history",
            "remaining_time_white", "remaining_time_black",
            "captured_pieces_count_by_white", "captured_pieces_count_by_black",
            "white_draw_offer", "black_draw_offer",
            "first_color_first_move_done", "second_color_first_move_done",
        ])
