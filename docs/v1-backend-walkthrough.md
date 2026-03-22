# V1 Backend — Complete Logic Walkthrough

> Source: `damka-back/game/consumers/russian.py` (783 lines),
> `damka-back/shared/django/consumers/russian.py` (633 lines, `GameBaseConsumer`),
> `damka-back/game/consumers/find_game.py` (304 lines, `MatchmakingConsumer`),
> `damka-back/game/signals.py` (92 lines, ELO rating)

---

## 1. Architecture Overview

```
GameConsumer (russian.py:783)
  └─ extends GameBaseConsumer (shared/consumers/russian.py:633)
       └─ extends AsyncUjsonWebsocketConsumer (shared/consumers/base.py)

MatchmakingConsumer (find_game.py:304)
  └─ extends AsyncUjsonWebsocketConsumer
```

All consumers use `ujson` for JSON encoding/decoding. Redis is used for:
- Channel name tracking (per player)
- Matchmaking queue (Lua script)
- Celery task ID storage
- Rematch offer tracking

---

## 2. Connection Flow (`connect()`, lines 68-270)

### Step-by-step:

1. **Extract scope data**: `game_uuid`, `type` (authorized/anonym), `user`, `private_key`
2. **Check for existing games** (`check_user_exists_game`):
   - If player has unfinished games AND opponent is present → **BLOCK** with `{error: "You have unfinished games!", id: game_id, type: game_type}`
   - If opponent is empty (abandoned PRIVATE game) → **DELETE** the old game
3. **Set connection to Redis**: Maps `user_str:token → channel_name`
4. **Load game from DB**: `Game.objects.aget(id=game_uuid)`
   - If game ended → close with error
   - If game not found → close with error
5. **Start game** (if not started):
   - Create board: `Board('russian', 'startpos')`
   - Save FEN to game
   - `update_game_started_status()` → sets `has_started=True`, `turn=board.turn`, assigns player to empty slot
   - Schedule first-move check: `set_and_check_time_to_move(game, WHITE, queue=1)` → Celery task with countdown=`ru_game_first_move_time`
6. **Private game handling**: Complex logic for friend games (join matching, color assignment)
7. **Determine colors**: `get_colors_of_players()` → resolves `white_player`, `black_player`, channel names from Redis
8. **Join channel group**: `group_add(game_uuid, channel_name)`
9. **Send initial state**: `get_data_to_response_at_connection()` returns full game state:

```python
response = {
    'fen': board.fen,
    'turn': current_turn,
    'remaining_time_white': white_time,
    'remaining_time_black': black_time,
    'has_ended': False,
    'users': [white_info, black_info],
    'increment': game.increment,
    'last_move': game.last_move,
    'chat': chat_history,       # DB query with annotated sender_color
    'has_started': bool(game.last_move),
    'history': json.loads(game.history),
    'captured_pieces_count_by_white': ...,
    'captured_pieces_count_by_black': ...,
    'mode': {id, title, additional_info: {id, title, time, increment}},
    'first_color_first_move_time': ...,   # Only before both first moves
    'second_color_first_move_time': ...,
    'draw': ColorChoices.white/black,     # If draw offer pending
    'your_color': 1 (black) or 2 (white),
    'possible_moves': [steps_move, ...]   # Only for current turn player
}
```

> **CRITICAL**: `possible_moves` uses `board.legal_moves()` which returns `steps_move` format (py-draughts V1). In V2, `legal_moves` is a PROPERTY returning `Move` objects with `square_list`.

---

## 3. Message Types (`receive()`, lines 272-783)

### 3.1 `move` (lines 301-482)

1. **Guard**: game must be started
2. **Load board**: `Board('russian', fen)` from current `self.game.fen`
3. **Turn check**: `current_turn == 2 and user == white_player` (or black)
4. **Timer calculation**:
   - `now = timezone.localtime(timezone.now()).replace(tzinfo=None)`
   - `elapsed_time = (now - game.last_move_time).total_seconds()`
   - First move: `elapsed_time = 0`, schedule black's first-move check
   - `first_color_first_move_done` → set on white's 1st move
   - `second_color_first_move_done` → set on black's 1st move, also sets `started_time`
   - White timer: `remaining_time_white = max(0, remaining - elapsed + increment)`
   - Black timer: similar
5. **Timeout check**: If remaining time ≤ 0, end game
6. **Execute move**:
   ```python
   move = Move(board, steps_move=moves)
   if move.has_captures:
       game.captured_pieces_count_by_* += len(move.captures)
   board.push(move)
   ```
7. **Game over check**: `if board.is_over(): clarify_game_details_if_game_over(board)`
8. **Save to DB**: FEN, turn, last_move, times, history, captures
9. **Broadcast**: Send to current turn player (with `possible_moves`) and opponent (without)
10. **History management**: `add_to_history_and_change_tasks()`:
    - History is a JSON dict: `{"1": {"21-17": "FEN..."}, "2": {"11-15": "FEN..."}, ...}`
    - Each key can have up to 2 entries (white move + black move)
    - Revokes old Celery timer, schedules new `check_game_time_to_end`

### 3.2 `lose` / resign (lines 486-569)

1. **Set winner**: opposing color
2. **Set `authorized_winner` or `guest_winner`** based on opponent's auth status
3. **Save**: `has_ended=True`, `color_win=winner`, `finished_time`
4. **Response** includes:
   - `gave_up_player_color`: which color resigned
   - `ended_information`: rating change (only for authorized players)
   - Each player gets their own `your_color` and `ended_information`
5. **Cleanup**: Revoke move timer, schedule `wait_for_end` Celery task

### 3.3 `draw` (lines 573-680)

Two-step process:
1. **Offer**: If opponent hasn't offered → set `white_draw_offer=True`, notify both players `{draw: ColorChoices.white}`
2. **Accept**: If opponent already offered → `color_win=0`, `has_ended=True`, notify with rating changes
3. **Duplicate check**: If already offered → error "You have ALREADY applied"

### 3.4 `rematch` (lines 681-724)

1. **Guard**: game must be ended, player must be participant
2. **Track offers in Redis**: `{game_uuid}_rematch_white`, `{game_uuid}_rematch_black`
3. **When both offered**:
   - Mark `all_players_left = True`
   - Create new game: `get_and_create_rematch_game()` → same players, same type, `parent_id=game.id` (MPTT tree for session tracking)
   - Send `{game: new_game_id, type_of_game_id, private_key, white_score, black_score}` to both
   - Disconnect old game

### 3.5 `chat` (lines 725-757)

- Save `Chat` to DB (message, authorized_sender or guest_sender)
- Send `{letter: {message, datetime, sender_color}}` to both players

### 3.6 `time` (lines 758-779)

Two modes:
- **Before both first moves**: returns `first_color_first_move_time` and `second_color_first_move_time` (countdown to first move timeout)
- **After both first moves**: returns `white_time`, `black_time` with `both_first_move_done=True`

---

## 4. Disconnect & Cleanup (lines 580-633)

1. **Refresh from DB**: `game.arefresh_from_db()`
2. **Mark `all_players_left`**: If game ended and player is participant
3. **Group discard + close**
4. **Redis cleanup**: Delete channel mapping, rematch offers
5. **Celery cleanup**: Revoke pending timer tasks
6. **ConnectionHistory**: Set status=OFFLINE, was_failed=False

---

## 5. Matchmaking (`find_game.py`)

### Flow:
1. **Validate**: game_type_id, rating_level (for guests)
2. **Delete orphaned games**: Games where opponent slot is empty
3. **Block if unfinished games**: `{error: "You have unfinished games!", id: game_id}`
4. **Find match**: Lua script on Redis with ±200 rating range
5. **If matched**:
   - Create Game with random color assignment
   - Send `{status: "found", game_id, users}` to both
   - Close both WebSocket connections
6. **If not matched**:
   - Store in Redis with Celery timeout task
   - Send `{status: "waiting", user}` to searcher
7. **Matchmaking timeout**: `check_matchmaking` Celery task → sends `{status: "Not found!"}`

### Cancel: `disconnect` → cleanup Redis + revoke Celery

---

## 6. ELO Rating (`signals.py`)

- `post_save` signal on `Game`
- Only when `has_ended=True` AND `rating_calculated=False`
- Calculates per mode: bullet, blitz, rapid
- Uses `calculate_elo_rating(player_rating, opponent_rating, score)`
- Sets `rating_calculated = True` to prevent double-calc

---

## 7. Key Differences: V1 API vs V2 API

### Move format:
| V1 | V2 |
|----|-----|
| `Move(board, steps_move=moves)` | `make_move(board, square_list)` |
| `move.steps_move` → list format | `move.square_list` → `[from, to]` 0-indexed |
| `board.legal_moves()` → METHOD | `board.legal_moves` → PROPERTY |
| `move.pdn_move` → string | `str(move)` → UCI notation |
| `board.turn` → `2=WHITE, 1=BLACK` | `board.turn` → `Color.WHITE (-1), Color.BLACK (1)` |
| `board.winner()` → returns color | Check via `board.is_over()` + logic |
| `Board('russian', fen)` | `RussianBoard.from_fen(fen)` |

### Response format:
| V1 (all in `message` wrapper) | V2 (has `event` field) |
|------|------|
| `{fen, turn, has_ended, ...}` | `{event: "init/move/error/game_over", ...}` |
| `{gave_up_player_color}` | Not implemented yet |
| `{draw: color}` | Partially implemented |
| `{rematch_offer: color}` | Partially implemented |
| `{letter: {message, datetime, sender_color}}` | Implemented in ChatMixin |
| `{game: new_id}` → navigate to rematch | Implemented in RematchMixin |
