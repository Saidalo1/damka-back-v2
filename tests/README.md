# Tests

Two layers:

## 1. Unit tests (pytest) — no Django, no DB, no Docker

Pure logic: Russian-draughts **rules verification** and the **bot engine**.

```bash
.venv/Scripts/python.exe -m pytest
```

- `test_russian_rules.py` — mandatory capture, flying king, mid-row promotion,
  termination, FEN round-trip. This is the correctness safety net around
  py-draughts (our rules engine).
- `test_bot_engine.py` — move legality, evaluation, and that MEDIUM beats EASY.

## 2. Integration checks (WebSocket consumers, end-to-end)

Standalone scripts driven by Channels' `WebsocketCommunicator`. Set
`PYTHONPATH=.` and `PYTHONIOENCODING=utf-8` (Windows console).

**Bot** — no DB/Redis needed (in-memory game):
```bash
PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe tests/integration/run_bot.py
```

**Friend** — needs a DB. SQLite test settings work with no Docker:
```bash
# one-time: create the sqlite test DB
DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe manage.py migrate --skip-checks
PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.test .venv/Scripts/python.exe tests/integration/run_friend.py
```

**Online** (+ real Redis channel layer) — needs Postgres + Redis:
```bash
docker compose up -d postgres redis
PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.dockertest CELERY_EAGER=0 \
  .venv/Scripts/python.exe tests/integration/run_online.py
```

`run_bot.py` / `run_friend.py` also pass against the real stack with
`DJANGO_SETTINGS_MODULE=config.settings.dockertest`.

> Settings: `config.settings.test` = SQLite + in-memory channel layer;
> `config.settings.dockertest` = the local venv against dockerized Postgres+Redis.
