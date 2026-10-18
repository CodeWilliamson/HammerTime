# HammerTime

Curling rink draw timer for Raspberry Pi kiosk displays. Node.js (ESM) + Express 5 + SQLite (`better-sqlite3`), vanilla JS frontend.

## Developer commands

Run from the repo root. The app uses ES modules (`"type": "module"`) — use `import`/`export`, no `require()`.

| Command | Purpose |
|---|---|
| `npm install` | Install dependencies (node_modules is present locally) |
| `npm run migrate` | Apply pending SQL migrations from `db_migrations/`; creates `data/schedule.db` and seeds the default admin user |
| `npm start` | Start the server (`node index.js`), port `PORT` or `3000` |

**Required order:** `npm install` → `npm run migrate` → `npm start`. The app will fail on startup if the DB schema doesn't exist (`data/schedule.db` is created by migrations).

**Required env:** set `PORT` and `JWT_SECRET` (default `timertimertimer` — change in production). `.env` is gitignored but exists locally.

## Database

- SQLite file: `./data/schedule.db` (relative to cwd — always run commands from the repo root)
- Migrations: `db_migrations/*.sql`, named by semver (e.g. `1.0.0.sql`, `1.3.0.sql`). `npm run migrate` applies only migrations newer than the tracked `schema_version` and `<= ` the version in `package.json`; re-running is safe. **Bump `package.json` version when adding a migration** — it gates which migrations apply.
- `data/.gitkeep` is tracked; `data/schedule.db` is local/untracked — **do not commit it**. It contains the club's real data, so be careful with mutating requests when smoke testing against it.
- Schema: `draws` (recurring weekly draws), `draw_overrides` (date-specific, e.g. bonspiels), `timer_config`, `users`.

## Auth

- JWT in an httpOnly cookie (`/auth/login`), `requireAuth` middleware guards admin APIs.
- Default admin credentials: `timer` / `timer` (change after first login). Seeded by the `1.0.0` migration.
- The `/events` SSE stream and `/api/timer/state` are **public** (the kiosk display must work without a login).

## Real-time updates: Server-Sent Events

Live updates use SSE at `GET /events` (`broadcast.js`). There are **no WebSockets** — the `ws` dependency was removed in Oct 2026 after a poll→WS→SSE migration history. Don't reintroduce polling or WS without a strong reason.

- Events are named snapshots, sent as `event: <type>` + `data: <json>`:
  - `hello` — full snapshot on every (re)connect: `{ timer_state, config }`.
  - `timer_state` — current timer state; consumed by the kiosk (`public/app.js`).
  - `config` — display config; consumed by `public/settings.js`.
- **Snapshots, not an event log**: there is no `Last-Event-ID` replay. On reconnect the server just resends current state, which is both simpler and correct. Keep payloads full-state, never diffs.
- Server pushes:
  - `broadcastTimerState()` after every draw/override/config mutation (routes in `routes/*.js`) — this is what lets kiosks react to admin edits instantly.
  - A **60s unconditional** `broadcastTimerState()` (`startTimers()` in `broadcast.js`). Time-driven transitions (running → complete → next draw's pre_draw) are not tied to any REST write, so without this the kiosk freezes on "Time's Up!" forever. Do not remove it.
- Client-side reconnection: `EventSource` handles blips automatically. Both clients have a 10s reopen guard for the one fatal case — a non-2xx response permanently closes an `EventSource` (e.g. catching the server mid-restart as a 500).
- SSE caveats: each open stream permanently consumes one of the browser's **6 HTTP/1.1 connections per origin** (WS was exempt from this). One tab per kiosk display is fine; 7+ tabs of timer/settings pages in one browser would starve. A REST fallback poll is the agreed remedy if this ever bites.
- `heartbeat()` writes a `: keep-alive` comment every 20s; server responses set `X-Accel-Buffering: no` in case a reverse proxy is ever added.
- `DEBUG=1` logs SSE connect/disconnect and every broadcast — useful when troubleshooting a display that "isn't updating".

## Timer state machine

- `getTimerState()` in `timerState.js` is the **single source of truth** (statuses: `idle`, `waiting`, `pre_draw`, `running`, `complete`). Both `/api/timer/state` and the SSE broadcasts compute through it.
- Windows: `pre_draw` starts 10 min before a draw; `complete` lingers 10 min after one ends; then `waiting` (next draw known) or `idle` (none left today).
- The kiosk (`public/app.js`) mirrors transitions locally in a 1s `tick()` so the display is smooth and survives disconnects, **but `tick()` is the sole writer of `timeRemaining` during a countdown** — letting both `tick()` and server pushes write it caused visible flicker (see commit history). Server pushes only re-adopt `timeRemaining` on a status change.
- `fetchState()` (REST, `/api/timer/state?lastConfigSeenAt=…`) primes the kiosk on load and provides config deltas; it is not a poll loop.

## Frontend

- `public/` is served statically by Express. No build step — edit HTML/CSS/JS directly.
- Entry pages: `index.html` (kiosk timer, public), `login.html`, `admin.html`, `settings.html`.
- `public/app.js` (kiosk): SSE stream + 1s `tick()` + local timer feature. **Local timer**: stored in `localStorage` (`localTimer`), overrides the central timer per-browser (curling sheets without a networked display); expires `LOCAL_COMPLETE_MS` (10 min) after its target.
- `public/admin.js`: has **no live connection** — it fetches the schedule via REST (`loadDraws()`) on load/resize and immediately after its own save/delete. Other admins' changes only appear on next page load (accepted trade-off; the schedule is not broadcast).
- `public/settings.js`: SSE for `config` only, so config edits sync across clients live.
- Most DOM elements are fetched at module scope — client JS requires the DOM element ids in its HTML to exist; check both when adding UI.

## Smoke testing (there is no test suite)

```sh
DEBUG=1 PORT=3999 node index.js
curl -N http://localhost:3999/events          # should print an "event: hello" snapshot
```

To exercise a broadcast: log in (`curl -c cookies -X POST /auth/login -H 'Content-Type: application/json' -d '{"username":"timer","password":"timer"}'`), then `PUT /api/timer/config` with an existing value — the connected `/events` client should receive `event: config` and `event: timer_state`. Prefer writing back existing config values so the club's display settings aren't altered.

## What does NOT exist

- No test suite, no linter, no formatter, no typecheck (plain JS). `npm test`, `npm run lint`, etc. are not defined — don't run them.
- No CI beyond deployment: `.github/workflows/main.yml` runs on push to `main` on a self-hosted Raspberry Pi (`git pull`, `npm install`, `npm run migrate`, `sudo systemctl restart curling-timer.service`).

## Gotchas

- `getCurrentDraw()` in `db.js` uses the **local timezone** for the current date — behavior depends on the host's TZ (and each kiosk's own clock for `tick()`; the server's `targetTime` is authoritative).
- Weekly draws overlapping a same-day override are excluded for that date; non-overlapping weekly draws still run.
- Anything that must move the kiosk's display **over time** (not triggered by a write) has to go through a server-side push (`broadcastTimerState`) — the client will not re-derive new draws on its own.
- Draw validation: weekly draws may not overlap other weekly draws (`validateWeeklyDraw`); overrides may overlap anything and take precedence on their date.
