"""
WebSocket consumers for the game application.

Each consumer is a package with its own mixins:
- game/        → GameConsumer (active game: moves, timer, chat, rematch)
- matchmaking/ → MatchmakingConsumer (player matching)
- friend/      → GameWithFriendConsumer (private games)
"""
