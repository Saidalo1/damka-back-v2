"""E2E test for GameWithFriendConsumer on the SQLite test DB (no Docker).

Runs the real TokenAuthMiddleware + URLRouter so auth + private_key flow are
exercised exactly as in production.
"""
import os
import asyncio

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")


async def main():
    from channels.testing import WebsocketCommunicator
    from channels.db import database_sync_to_async
    from rest_framework.authtoken.models import Token

    from apps.shared.middleware.ws_auth import TokenAuthMiddleware
    from channels.routing import URLRouter
    from apps.game.routing import websocket_urlpatterns
    from apps.game.models import Game, GameTypesTime, GameTypeChoices
    from apps.users.models import User

    app = TokenAuthMiddleware(URLRouter(websocket_urlpatterns))

    @database_sync_to_async
    def setup():
        Game.objects.all().delete()
        u1, _ = User.objects.get_or_create(username="tester_one", defaults={"phone_number": "+998901112233"})
        u2, _ = User.objects.get_or_create(username="tester_two", defaults={"phone_number": "+998901112244"})
        t1, _ = Token.objects.get_or_create(user=u1)
        t2, _ = Token.objects.get_or_create(user=u2)
        gt = GameTypesTime.objects.select_related("type").first()
        return t1.key, t2.key, gt.id

    @database_sync_to_async
    def fetch_game(game_id):
        g = Game.objects.get(id=game_id)
        return {
            "type": g.type,
            "white_id": g.white_id,
            "black_id": g.black_id,
            "private_key": g.private_key,
            "has_ended": g.has_ended,
        }

    tok1, tok2, gt_id = await setup()
    print(f"tokens ready, game_type_id={gt_id}")

    # --- Creator ---
    creator = WebsocketCommunicator(app, f"/ws/friend/?authorization={tok1}")
    ok, _ = await creator.connect()
    assert ok, "creator failed to connect"
    await creator.send_json_to({"type": "game_type", "message": {"color": 2, "game_type": gt_id}})
    created = await creator.receive_json_from(timeout=10)
    assert created["event"] == "created", created
    game_id = created["game_id"]
    pkey = created["private_key"]
    assert created["your_color"] == 2 and created["waiting"] is True
    print(f"[creator] created game {game_id[:8]} key={pkey} your_color={created['your_color']}")

    # --- Joiner ---
    joiner = WebsocketCommunicator(app, f"/ws/friend/?authorization={tok2}&private_key={pkey}")
    ok2, _ = await joiner.connect()
    assert ok2, "joiner failed to connect"
    start_joiner = await joiner.receive_json_from(timeout=10)
    assert start_joiner["event"] == "start", start_joiner
    assert start_joiner["game_id"] == game_id
    print(f"[joiner] start game {start_joiner['game_id'][:8]} your_color={start_joiner.get('your_color')}")

    # --- Creator should also get 'start' via the group ---
    start_creator = await creator.receive_json_from(timeout=10)
    assert start_creator["event"] == "start", start_creator
    assert start_creator["game_id"] == game_id
    print(f"[creator] received start for {start_creator['game_id'][:8]}")

    # --- DB: both seats filled, still unfinished, PRIVATE ---
    g = await fetch_game(game_id)
    assert g["type"] == GameTypeChoices.PRIVATE
    assert g["white_id"] is not None and g["black_id"] is not None, g
    assert g["has_ended"] is False
    print(f"[db] both seats filled: white={g['white_id']} black={g['black_id']} type=PRIVATE ✓")

    await creator.disconnect()
    await joiner.disconnect()

    # --- Guest is rejected ---
    guest_token = "g" * 44  # >=43 → treated as anonymous
    guest = WebsocketCommunicator(app, f"/ws/friend/?authorization={guest_token}")
    okg, _ = await guest.connect()
    # consumer accepts then sends error + closes
    if okg:
        msg = await guest.receive_json_from(timeout=10)
        assert msg["event"] == "error" and msg.get("need_register") is True, msg
        print(f"[guest] correctly gated: {msg['message']}")
    await guest.disconnect()

    print("\nALL FRIEND CONSUMER TESTS PASSED")


if __name__ == "__main__":
    import django
    django.setup()
    asyncio.run(main())
