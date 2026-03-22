# V2 vs V1 — Gap Analysis

> This document lists every feature/behavior present in V1 that is either missing,
> partially implemented, or implemented differently in V2.
> Priority: 🔴 Critical (blocks UX), 🟡 Important, 🟢 Nice-to-have

---

## 🔴 Critical Gaps

### 1. `has_ended=True` in DB but game not cleaned up
**V1**: When game ends → `has_ended=True` saved in DB, `finished_time` set.
  When player tries matchmaking → `check_user_exists_game` / middleware checks
  `/api/has-game/active/` → finds `has_ended=False` games only → allows new game.
**V2**: Game ends → `has_ended=True` saved. BUT there's **no active game check
  before matchmaking**. Frontend has no middleware like `02.check-active-game.global.ts`.
  → User gets redirected to old game because frontend/backend thinks it's still active.

**Fix needed**:
- Backend: Add `/api/has-game/active/` endpoint (or equivalent check in matchmaking WS)
- Frontend: Add middleware or matchmaking guard that checks for unfinished games
- Backend matchmaking: Block if user has `has_ended=False` game (V1 `find_game.py:71-96` does this)

### 2. Game Over Broadcast Incomplete
**V1**: On game over, sends to BOTH players:
  - `has_ended: true`
  - `winner`
  - `white_score`, `black_score` (session scores)
  - `ended_information` (rating change for each player individually)
  - `gave_up_player_color` (for resign)
  - FEN and times frozen

**V2**: `game_end.py._end_game()` sends `game_over` event with `winner`, `reason`,
  `session_score`. Rating info is personalized per player ✅. BUT:
  - Missing `gave_up_player_color` field (frontend can use `reason === "resign"` + `winner`)
  - `finished_time` never set on game model
  - `all_players_left` never managed → cleanup of game room doesn't happen
  - `wait_for_end()` Celery task (cleanup on disconnect delay) not implemented

**Fix needed**:
- Set `finished_time` in `_finalize_game`
- Frontend: Map `reason === "resign"` to gaveUp visual state
- Backend: Implement disconnect cleanup (V1's `all_players_left` + `wait_for_end`)

### 3. Matchmaking "Unfinished Game" Block
**V1 matchmaking** (`find_game.py:71-96`):
1. Deletes orphaned games (player has game but opponent slot is empty)
2. Checks for active games → sends `{error: "You have unfinished games!", id, type}` + closes WS
3. Frontend handles error → redirects to `/online/{id}`

**V2 matchmaking**: No unfinished-game check at all. Players can start infinite games.

**Fix needed**:
- Add unfinished-game check in matchmaking consumer `connect()`
- Delete orphaned games (no opponent) on new matchmaking connect

### 4. Timer "First Move" Countdown (Pre-game timer)
**V1**: Two-phase timer system:
  - **Phase 1**: `first_color_first_move_time` / `second_color_first_move_time` — countdown
    for each player's first move (separate timer, usually higher like 30s or 60s)
  - **Phase 2**: Regular game timers after both first moves done
  - Celery task `check_starting_game` fires if first move not made on time → auto-loss
  - Frontend shows different timer when `first_color_first_move_done` is false

**V2**: `start_first_move_timer()` exists but:
  - Never called from anywhere (not wired in `connect()`)
  - Frontend doesn't handle `first_color_first_move_time` / `second_color_first_move_time`
  - No separate pre-game countdown shown

**Fix needed**:
- Wire `start_first_move_timer()` in connection flow
- Send first-move countdown in `init` event
- Frontend: Show separate countdown timer before both players move

---

## 🟡 Important Gaps

### 5. Disconnect / Cleanup Logic
**V1**: Complex flow:
1. `game.arefresh_from_db()` — get latest state
2. If game ended + player is participant → set `all_players_left=True` → notify group → disconnect all
3. Redis cleanup: delete channel name mapping, rematch offers
4. Celery cleanup: revoke any pending timer tasks
5. ConnectionHistory: set `status=OFFLINE`, `was_failed=False`

**V2**: Minimal `handle_disconnect()` just does `group_discard`. No Redis/Celery cleanup.

**Fix needed**:
- Revoke timer tasks on disconnect
- Clean up Redis channel mappings
- Handle `all_players_left` flow
- Clean ConnectionHistory status

### 6. Connection → Existing Game Detection
**V1** (`connect()` lines 42-59):
When connecting to a game, if this player has OTHER unfinished games:
- If opponent is empty → delete the old game
- If opponent exists → error with redirect to old game

**V2** (`connection.py`): No such check. Players can open multiple game pages.

**Fix needed**: Add unfinished-game check in `setup_connection()`

### 7. Frontend Active-Game Middleware
**V1**: `middleware/02.check-active-game.global.ts` — runs on EVERY navigation:
- Calls `/api/has-game/active/`
- Redirects to unfinished game if exists

**V2**: No such middleware exists.

**Fix needed**: Create equivalent middleware in V2 frontend

### 8. Move History Format
**V1**: History stored as: `{"1": {"21-17": "FEN"}, "2": {"11-15": "FEN", "23-19": "FEN"}, ...}`
  - Each key has up to 2 entries (white move + black move in same turn)

**V2**: History stored as: `{"1": {"e3-d4": "FEN"}, "2": {"f6-g5": "FEN"}, ...}`
  - Each key has exactly 1 entry (one move per key)
  - Uses UCI/algebraic notation instead of PDN numbers

This difference affects:
- Frontend history sidebar rendering
- History navigation (prev/next)

**Status**: V2 frontend already handles both formats. No fix needed BUT verify display is correct.

### 9. Draw Offer with Fen Context
**V1**: Draw offer comes in two contexts:
  - `draw` WITH `fen` → `drawInside = true` (draw accepted, part of move response)
  - `draw` WITHOUT `fen` → `drawInside = false` (standalone draw offer notification)

**V2**: Uses `event: "draw_offer"` for offers. Draw acceptance goes through `_end_game` with `reason=draw`.
  Frontend handles both but `drawInside` logic may need verification.

### 10. Time Sync Request
**V1**: Client sends `{type: "time"}` → server responds with current times.
  Two modes: pre-first-moves (countdown) vs post-first-moves (regular).

**V2**: `handle_time_request()` exists in TimerMixin ✅. Returns `{event: "time_sync", times, turn}`.
  But missing pre-first-move countdown handling.

---

## 🟢 Nice-to-Have / Minor Gaps

### 11. Rating Change Display
**V1**: `ended_information` contains `calculate_rating_benefit(old, new)` — sent per player.
**V2**: `rating` dict sent per player via `_send_to_player` ✅. But format may differ from V1.

### 12. Session Score Display in Modal
**V1**: `white_score`/`black_score` displayed in end-game modal.
**V2**: `session_score` included in `game_over` event ✅. Frontend maps to `whiteScore`/`blackScore` ✅.

### 13. Chat sender_color
**V1**: Chat messages include `sender_color` (white=2, black=1).
**V2**: Chat messages include `is_authorized` but NOT `sender_color`.

**Fix needed**: Add `sender_color` to chat messages in V2 `ChatMixin`.

### 14. Board Sound Effects
**V1**: Move → `move.ogg`, Capture → `capture.ogg`. Detection: if PDN contains `-` → move, else capture.
**V2**: Same logic in frontend ✅. Audio refs exist.

### 15. Rematch Color Swap
**V1**: Rematch keeps SAME colors (no swap). New game has: `white=game.white, black=game.black`
**V2**: Rematch SWAPS colors: `white=game.black, black=game.white`

**Note**: V2 behavior is actually better (fair). Just be aware of the difference.

### 16. Error Handling "Game has ended already!"
**V1**: Backend sends this exact string. Frontend catches → navigates to home.
**V2**: Backend sends `{event: "error", message: "Game has ended"}`. Frontend handles ✅.

---

## Summary Priority Table

| # | Feature | Priority | Backend | Frontend |
|---|---------|----------|---------|----------|
| 1 | Unfinished game block (matchmaking) | 🔴 | ❌ Missing | ❌ Missing |
| 2 | Game over broadcast (finished_time, cleanup) | 🔴 | ⚠️ Partial | ⚠️ Partial |
| 3 | Matchmaking unfinished-game check | 🔴 | ❌ Missing | ❌ Missing |
| 4 | First-move countdown timer | 🔴 | ⚠️ Written but unwired | ❌ Missing |
| 5 | Disconnect cleanup (Redis, Celery, ConnectionHistory) | 🟡 | ❌ Missing | N/A |
| 6 | Connection → unfinished game check | 🟡 | ❌ Missing | N/A |
| 7 | Active-game middleware | 🟡 | Need API | ❌ Missing |
| 8 | Move history format | 🟡 | ✅ Different but OK | ✅ Handled |
| 9 | Draw offer context (drawInside) | 🟡 | ✅ Works | ⚠️ Verify |
| 10 | Time sync (pre-first-move) | 🟡 | ⚠️ Partial | ❌ Missing |
| 11 | Rating change display | 🟢 | ✅ Works | ⚠️ Format check |
| 12 | Session score in modal | 🟢 | ✅ Works | ✅ Handled |
| 13 | Chat sender_color | 🟢 | ❌ Missing | N/A |
| 14 | Sound effects | 🟢 | N/A | ✅ Works |
| 15 | Rematch color swap | 🟢 | ✅ (better UX) | N/A |
| 16 | Error handling | 🟢 | ✅ Works | ✅ Handled |
