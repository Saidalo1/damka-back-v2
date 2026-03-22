# V1 Frontend — Complete Logic Walkthrough

> Source: `damka-front/pages/online/[gameId].vue` (489 lines),
> `damka-front/pages/online/index.vue` (363 lines),
> `damka-front/middleware/02.check-active-game.global.ts` (48 lines)

---

## 1. Active Game Guard (middleware)

**File**: `middleware/02.check-active-game.global.ts`

On every navigation: calls `/api/has-game/active/` and:

| `response.type` | Has opponent? | Action |
|---|---|---|
| `0` (MATCHMAKING) | — | Redirect to `/online/{id}` |
| `1` (PRIVATE) | `has_opponent=true` | Redirect to `/friend/{id}?key={private_key}` |
| `1` (PRIVATE) | `has_opponent=false` | Redirect to `/friend` (waiting screen) |
| No game | — | Continue to destination |

This is how V1 prevents players from starting new games while they have unfinished ones.

---

## 2. Matchmaking Page (`pages/online/index.vue`)

### WebSocket Connection:
```
ws://HOST/ws/matchmaking/{game_type_id}/?authorization={token}&rating_level={level}
```

### State:
- `status`: `0` = searching, `1` = found, `2` = not found
- `selectedTime`: from cookie `userPreferredTime`

### Message handling:
| Status | Response | Action |
|---|---|---|
| `"waiting"` | `{user}` | Show searching UI, store user info |
| `"found"` | `{game_id, users}` | Animate match found → navigate to `/online/{game_id}` after 3s |
| `error` | `{error, id}` | Navigate to `/online/{id}` (existing game) |
| `"Not found!"` | — | Show "no opponent found" overlay |

### UI during search:
- Board shows static board (`SectionMainBoard`)
- Animated overlay when match found: opponent username slides from top, player from bottom
- Cancel button → `closeConnection()`
- Search again button → `closeConnection()` + `connect()`

---

## 3. Game Page (`pages/online/[gameId].vue`)

### WebSocket:
```
ws://HOST/ws/game/russian/{gameId}/?authorization={token}
```

### State variables (ALL refs):
```javascript
fen             // Current board FEN string
yourColor       // 1=black, 2=white (from server)
turn            // Current turn (1=black, 2=white)
history         // {key: fen, ...} — full move history
firstTimeWhite  // Countdown for white's first move
firstTimeBlack  // Countdown for black's first move
timeWhite       // White's remaining time
timeBlack       // Black's remaining time
gameInfo        // {id, title, additional_info} — game mode
capturedWhite   // Pieces captured by white
capturedBlack   // Pieces captured by black
hasStarted      // Boolean
hasEnded        // Boolean
possibleMoves   // Array of step arrays (only when it's your turn)
lastMove        // Last move made (for highlighting)
draw            // Pending draw offer color
drawInside      // Whether draw came with a board update or standalone
chats           // Array of {message, datetime, sender_color}
gaveUp          // Boolean — someone resigned
winner          // Color that won (0=draw, 1=black, 2=white)
endedInfo       // Rating change info
rematch         // Rematch offer color
whiteScore      // Session score for white
blackScore      // Session score for black
```

### Message handling (`watch(messages, ...)`, lines 83-262):

**Generic updates** (always applied if present):
- `remaining_time_black` → `timeBlack`
- `remaining_time_white` → `timeWhite`
- `captured_pieces_count_by_*` → `capturedBlack`/`capturedWhite`
- `has_started` → `hasStarted`
- `your_color` → `yourColor`
- `turn` → `turn`
- `fen` → `fen`
- `mode` → `gameInfo`

**History** (`val.message.history`): Full history loaded at connection
**PDN** (`val.message.pdn`): Single move added to history + play move/capture audio

**Possible moves**: Updated when `fen` is present:
- If `possible_moves` in message → set `possibleMoves`
- Else → clear `possibleMoves` (not your turn)

**First move timers**: Same pattern, set or clear `firstTimeWhite`/`firstTimeBlack`

**Draw**: Two contexts:
- `draw` WITH `fen` → `drawInside = true` (draw accepted, game ended)
- `draw` WITHOUT `fen` → `drawInside = false` (new draw offer)

**Users**: Assigns `thisUser`/`otherUser` by `is_you` flag

**Chat**: Appends to `chats` array (both `chat` array and `letter` single)

**Resign** (`gave_up_player_color`): `gaveUp = true`, `winner = opponent`

**Game Over** (`has_ended`): Opens modal (modal.active=3, modal.status=true)

**Error handling**:
- `"Game has ended already!"` → navigate home
- Other errors → console.error

**Rematch offer** (`rematch_offer`): stored in `rematch` ref

**New game** (`game`): Navigate to `/friend/{id}` or `/online/{id}` based on `type_of_game_id`

### User actions:
| Action | WebSocket message |
|---|---|
| Make move | `{type: "move", message: [from, to]}` |
| Resign | `{type: "lose"}` |
| Draw offer | `{type: "draw"}` |
| Chat | `{type: "chat", message: "text"}` (max 200 chars) |
| Rematch | `{type: "rematch"}` |

### History navigation:
- `goToPreviousHistory()` / `goToNextHistory()` — step through FENs
- When viewing old position: `possibleMoves` cleared (can't move from history view)

### Template structure:
```
LayoutHeader
Container
  ├── Opponent User info (SectionOnlineUser)
  │     ├── avatar, username, rating
  │     ├── timer (opponent's remaining time)
  │     └── captured pieces
  ├── Board (SectionOnlineBoard)
  │     ├── fen, turn, your_color
  │     ├── possible_moves (disabled during history navigation)
  │     └── last_move highlights
  ├── Your User info (SectionOnlineUser)
  └── Sidebar (SectionOnlineSidebar)
        ├── Move history (scrollable, clickable)
        ├── History navigation arrows (prev/next)
        ├── Resign button
        ├── Draw button
        └── Chat input

Modal (SectionOnlineModalsModal) — shown when game ends:
  ├── Winner/draw info
  ├── Rating change
  ├── Rematch button
  └── Session scores
```

---

## 4. Key V1 Board Component (`Section/Online/Board/Board.vue`)

The board uses `steps_move` format from V1 py-draughts. Key points:
- Receives `possible-moves` as prop — array of step arrays
- Uses `v-model` to emit moves back to parent
- Click handling: select piece → show valid destinations → click destination → emit move
- `your-color` determines board orientation (white at bottom or black at bottom)
- `last-move` highlighting
- `has-ended` disables interaction

---

## 5. Session Score Tracking

V1 tracks session scores across rematches:
- `white_score` / `black_score` — cumulative wins in the session
- Maintained via `_calculate_session_scores()` using MPTT parent chain
- Displayed in game-end modal
