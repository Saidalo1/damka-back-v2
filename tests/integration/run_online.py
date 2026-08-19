"""Online-game smoke test on the REAL stack (Postgres + Redis channel layer).

Validates: two players connect to GameConsumer, exchange moves through the real
Redis channel layer, and the event protocol matches what the bot consumer emits.
Run with CELERY_EAGER=0 so move timers only enqueue (no premature timeout).
"""
import os
import asyncio

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dockertest")


async def main():
    from channels.testing import WebsocketCommunicator
    from channels.db import database_sync_to_async
    from channels.routing import URLRouter
    from rest_framework.authtoken.models import Token

    from apps.shared.middleware.ws_auth import TokenAuthMiddleware
    from apps.game.routing import websocket_urlpatterns
    from apps.game.models import Game, GameTypesTime, GameTypeChoices
    from apps.users.models import User
    from shared.django import ColorChoices

    app = TokenAuthMiddleware(URLRouter(websocket_urlpatterns))

    @database_sync_to_async
    def setup():
        from django.utils import timezone
        u1, _ = User.objects.get_or_create(username="online_white", defaults={"phone_number": "+998901110001"})
        u2, _ = User.objects.get_or_create(username="online_black", defaults={"phone_number": "+998901110002"})
        t1, _ = Token.objects.get_or_create(user=u1)
        t2, _ = Token.objects.get_or_create(user=u2)
        gt = GameTypesTime.objects.select_related("type").first()
        Game.objects.filter(white=u1, has_ended=False).delete()
        g = Game.objects.create(
            type_of_game=gt, type=GameTypeChoices.MATCHMAKING,
            white=u1, black=u2, turn=ColorChoices.white.value,
            increment=gt.increment,
            initial_time_white=gt.time, initial_time_black=gt.time,
            remaining_time_white=gt.time, remaining_time_black=gt.time,
            has_started=True, last_move_time=timezone.now(),
        )
        return t1.key, t2.key, str(g.id)

    tok_w, tok_b, gid = await setup()
    print(f"game {gid[:8]} ready")

    white = WebsocketCommunicator(app, f"/ws/game/{gid}/?authorization={tok_w}")
    black = WebsocketCommunicator(app, f"/ws/game/{gid}/?authorization={tok_b}")
    okw, _ = await white.connect()
    okb, _ = await black.connect()
    assert okw and okb, "connect failed"

    init_w = await white.receive_json_from(timeout=10)
    init_b = await black.receive_json_from(timeout=10)
    assert init_w["event"] == "init" and init_w["your_color"] == ColorChoices.white.value
    assert init_b["event"] == "init" and init_b["your_color"] == ColorChoices.black.value
    assert init_w.get("possible_moves"), "white should have opening moves"
    print(f"[init] white pm={len(init_w['possible_moves'])} black pm={len(init_b.get('possible_moves', []))}")

    # White plays its first legal move.
    move = init_w["possible_moves"][0]
    await white.send_json_to({"type": "move", "message": move})

    # White gets its own echo (no possible_moves — not its turn now).
    echo_w = await white.receive_json_from(timeout=10)
    assert echo_w["event"] == "move" and echo_w["turn"] == ColorChoices.black.value
    assert "possible_moves" not in echo_w
    # Black receives the move WITH its possible_moves (real Redis delivery).
    ev_b = await black.receive_json_from(timeout=10)
    assert ev_b["event"] == "move" and ev_b["turn"] == ColorChoices.black.value
    assert ev_b.get("possible_moves"), "black should now have moves"
    assert "fen" in ev_b and "pdn" in ev_b and "last_move" in ev_b
    print(f"[move] white moved {move}; black received via Redis, pm={len(ev_b['possible_moves'])}")

    # Black replies.
    bmove = ev_b["possible_moves"][0]
    await black.send_json_to({"type": "move", "message": bmove})
    echo_b = await black.receive_json_from(timeout=10)
    assert echo_b["event"] == "move" and echo_b["turn"] == ColorChoices.white.value
    ev_w = await white.receive_json_from(timeout=10)
    assert ev_w["event"] == "move" and ev_w.get("possible_moves")
    print(f"[move] black moved {bmove}; white received via Redis, pm={len(ev_w['possible_moves'])}")

    await white.disconnect()
    await black.disconnect()
    print("\nONLINE SMOKE TEST PASSED (real Redis channel layer + protocol parity with bot)")


if __name__ == "__main__":
    import django
    django.setup()
    asyncio.run(main())
