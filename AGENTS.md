# HammerTime

Curling rink draw timer for Raspberry Pi kiosk displays. Python 3.11+ (FastAPI + Uvicorn) + SQLite (`sqlite3`), vanilla JS frontend.

This codebase is a **1-1 Python port of the original Node/Express server**. The `public/` frontend was not modified, so the browser is the contract: HTTP status codes, headers, JSON bodies and SSE frames must stay identical. The quirks that contract depends on are pinned by the test suite (`tests/test_api.py`, `tests/test_db.py`, `tests/visual/`).

## Developer commands

Run from the repo root. All paths (`data/`, `public/`, `db_migrations/`) are resolved relative to the working directory — same requirement as the Node version.

| Command | Purpose |
|---|---|
| `python3 -m venv .venv` | Create the virtualenv (once) |
| `./.venv/bin/python -m pip install -r requirements.txt` | Install runtime deps |
| `./.venv/bin/python -m pip install -r requirements-dev.txt` | Install test deps (pytest, httpx, Playwright) |
| `./.venv/bin/python -m playwright install chromium` | Fetch the browser for the visual tests (once) |
| `./.venv/bin/python -m hammertime.migrate` | Apply pending SQL migrations from `db_migrations/`; creates `data/schedule.db` and seeds the default admin user |
| `./.venv/bin/python -m hammertime` | Start the server, port `PORT` or `3000` |
| `./.venv/bin/python -m pytest` | Fast test suite (~35 s, incl. browser checks) |
| `./.venv/bin/python -m pytest -m slow` | Adds the 20 s heartbeat / 60 s state-tick checks (~3 min) |
| `./.venv/bin/python -m pytest -m visual` | Adds the screenshot-baseline comparisons (opt-in) |

**Required order:** create venv → install → `python -m hammertime.migrate` → `python -m hammertime`. The app fails on import if the DB schema doesn't exist (`hammertime/db.py` opens `./data/schedule.db` at import, like `db.js` did).

**Required env:** set `PORT` and `JWT_SECRET` (default `timertimertimer` — change in production). `.env` is gitignored but exists locally.

## Module map (old → new)

| Node | Python |
|---|---|
| `index.js` | `hammertime/main.py` + `hammertime/__main__.py` |
| `db.js` | `hammertime/db.py` |
| `auth.js` | `hammertime/auth.py` |
| `timerState.js` | `hammertime/timer_state.py` |
| `broadcast.js` | `hammertime/broadcast.py` |
| `util.js` | `hammertime/util.py` |
| `db_migrate.js` | `hammertime/migrate.py` |
| `routes/*.js` | `hammertime/routes/*.py` |
| `package.json` version | `hammertime/__init__.py` `__version__` |

## Database

- SQLite file: `./data/schedule.db` (relative to cwd — always run commands from the repo root)
- Migrations: `db_migrations/*.sql`, named by semver (e.g. `1.0.0.sql`, `1.5.0.sql`). `python -m hammertime.migrate` applies only migrations newer than the tracked `schema_version` and `<=` the version in `hammertime/__init__.py`; re-running is safe. **Bump `__version__` when adding a migration** — it gates which migrations apply.
- The connection is autocommit (`isolation_level=None`) and `PRAGMA foreign_keys = ON`, matching better-sqlite3's defaults. Row results are converted to plain dicts with `sqlite3.Row`.
- `data/.gitkeep` is tracked; `data/schedule.db` is local/untracked — **do not commit it**. It contains the club's real data, so be careful with mutating requests when smoke testing against it.
- Schema: `draws` (recurring weekly draws), `draw_overrides` (date-specific, e.g. bonspiels), `timer_config`, `users`.
- `tests/test_migrations.py` asserts the schema is byte-identical to the original Node migrator's output and that running migrations on a copy of an up-to-date database changes nothing.

## Auth

- JWT in an httpOnly cookie named `token` (1 hour, `SameSite=Strict`), signed HS256 with `JWT_SECRET`. `require_auth` is a FastAPI dependency that raises `AuthError`, rendered as `403 {"error": ...}`.
- Token expiry is checked against `hammertime.clock.now()` (not PyJWT's internal wall clock) so it behaves like `jsonwebtoken`'s `Date.now()` and stays testable.
- Default admin credentials: `timer` / `timer` (change after first login). Seeded by the `1.0.0` migration (bcrypt hash, cost 10 — compatible with Python `bcrypt`).
- The `/events` SSE stream, `/api/timer/state` and `/api/timer/closest-draw-duration` are **public** (the kiosk display must work without a login).
- `.env`'s `JWT_SECRET` **is** honoured (the Node version read it before `dotenv.config()` ran, so it always used the default).

## Real-time updates: Server-Sent Events

Live updates use SSE at `GET /events` (`hammertime/broadcast.py`). There are **no WebSockets** — the `ws` dependency was removed in Oct 2026 after a poll→WS→SSE migration history. Don't reintroduce polling or WS without a strong reason.

- Events are named snapshots, sent as `event: <type>` + `data: <json>`:
  - `hello` — full snapshot on every (re)connect: `{ timer_state, config, adminUrl }`.
  - `timer_state` — current timer state; consumed by the kiosk (`public/app.js`).
  - `config` — display config; consumed by `public/settings.js`.
- **Snapshots, not an event log**: there is no `Last-Event-ID` replay. On reconnect the server just resends current state, which is both simpler and correct. Keep payloads full-state, never diffs.
- Server pushes (`broadcast_timer_state()` / `broadcast_config()`):
  - after every draw/override/config mutation (routes in `hammertime/routes/*.py`) — this is what lets kiosks react to admin edits instantly.
  - a **60s unconditional** `broadcast_timer_state()` (started lazily with the first SSE client by `_start_timers()`). Time-driven transitions (running → complete → next draw's pre_draw) are not tied to any REST write, so without this the kiosk freezes on "Time's Up!" forever. Do not remove it.
- Fan-out: one `asyncio.Queue` per connected page; broadcasts are `put_nowait` of pre-serialized frames (`json.dumps(..., ensure_ascii=False, separators=(",", ":"))` to stay byte-identical with `JSON.stringify`).
- Client-side reconnection: `EventSource` handles blips automatically. Both clients have a 10s reopen guard for the one fatal case — a non-2xx response permanently closes an `EventSource` (e.g. catching the server mid-restart as a 500).
- SSE caveats: each open stream permanently consumes one of the browser's **6 HTTP/1.1 connections per origin** (WS was exempt from this). One tab per kiosk display is fine; 7+ tabs of timer/settings pages in one browser would starve. A REST fallback poll is the agreed remedy if this ever bites.
- `heartbeat()` pushes `: keep-alive\n\n` into every client queue every 20s; responses set `X-Accel-Buffering: no` in case a reverse proxy is ever added.
- `DEBUG` (any non-empty value) logs SSE connect/disconnect and every broadcast — useful when troubleshooting a display that "isn't updating".

## Timer state machine

- `get_timer_state()` in `hammertime/timer_state.py` is the **single source of truth** (statuses: `idle`, `waiting`, `pre_draw`, `running`, `complete`). Both `/api/timer/state` and the SSE broadcasts compute through it.
- Windows: `pre_draw` starts 10 min before a draw; `complete` lingers 10 min after one ends; then `waiting` (next draw known) or `idle` (none left today).
- Per-status payload key sets differ and the kiosk depends on them: `running` has no `endTime`, `pre_draw` does; `waiting` uses `nextDrawStart/nextDrawTitle/nextDrawMessage`; `targetTime` is formatted like `Date#toISOString()` (`2026-10-21T19:00:00.000Z`) via `js_isoformat()`.
- The kiosk (`public/app.js`) mirrors transitions locally in a 1s `tick()` so the display is smooth and survives disconnects, **but `tick()` is the sole writer of `timeRemaining` during a countdown** — letting both `tick()` and server pushes write it caused visible flicker (see commit history). Server pushes only re-adopt `timeRemaining` on a status change.
- `fetchState()` (REST, `/api/timer/state?lastConfigSeenAt=…`) primes the kiosk on load and provides config deltas; it is not a poll loop.

## Frontend

- `public/` is served statically by Starlette (`hammertime/responses.py::StaticFiles`, which restores Express's content types, e.g. `application/json; charset=utf-8`). No build step — edit HTML/CSS/JS directly.
- Entry pages: `index.html` (kiosk timer, public), `login.html`, `admin.html`, `settings.html`.
- `public/app.js` (kiosk): SSE stream + 1s `tick()` + local timer feature. **Local timer**: stored in `localStorage` (`localTimer`), overrides the central timer per-browser (curling sheets without a networked display); expires `LOCAL_COMPLETE_MS` (10 min) after its target.
- `public/admin.js`: has **no live connection** — it fetches the schedule via REST (`loadDraws()`) on load/resize and immediately after its own save/delete. Other admins' changes only appear on next page load (accepted trade-off; the schedule is not broadcast).
- `public/settings.js`: SSE for `config` only, so config edits sync across clients live.
- Most DOM elements are fetched at module scope — client JS requires the DOM element ids in its HTML to exist; check both when adding UI.

## Testing (no Node.js required)

```sh
./.venv/bin/python -m pytest            # fast suite: units, db, api, sse, migrations, browser
./.venv/bin/python -m pytest -m slow    # adds the 20 s heartbeat / 60 s state-tick checks
./.venv/bin/python -m pytest -m visual  # opt-in screenshot baselines
```

- `tests/support.py` — sandbox helpers: builds a database from `db_migrations/` in a temp dir, seeds `WEEKLY_DRAWS`/`OVERRIDES`, and starts the server on a free port with `HAMMERTIME_FAKE_NOW`. Frozen instants (`WAITING`, `PRE_DRAW`, `RUNNING`, `WARNING`, `COMPLETE`, `LATE_RUNNING`, `IDLE`) live here; add a scenario here rather than hand-testing.
- `tests/conftest.py` — fixtures: `template_db` (session), `server`/`server_factory`, `client`, `auth_client`, `db` (swaps `hammertime.db._conn` to a sandbox copy for in-process tests), `freeze`. It also pins `TZ=America/Toronto` before `hammertime` is imported, so frozen instants mean the same thing everywhere.
- `tests/test_db.py`, `test_timer_state.py`, `test_api.py`, `test_sse.py`, `test_migrations.py` — the named module is the thing under test.
- `tests/visual/` — Playwright/Chromium. The browser clock is frozen (`page.clock.install` + `pause_at`) at the same instant as the server's, so countdown digits and colours can be asserted exactly. Behaviour assertions run by default; screenshots are `visual`-marked and compared with a pixel tolerance against `tests/visual/baselines/` (`--update-baselines` regenerates; baselines are machine-specific).
- Never point the tests at `data/schedule.db`; they always build a database in a temp directory from the migrations.
- Odd original behaviours (nested `{"id":{"id":N}}`, override-before-weekly ordering, week-view `start_time` dedupe, 204-on-missing-draw) are pinned as ordinary assertions in `test_db.py`/`test_api.py` — keep them when refactoring.

Smoke test:

```sh
DEBUG=1 PORT=3999 ./.venv/bin/python -m hammertime
curl -N http://localhost:3999/events          # should print an "event: hello" snapshot
```

To exercise a broadcast: log in (`curl -c cookies -X POST /auth/login -H 'Content-Type: application/json' -d '{"username":"timer","password":"timer"}'`), then `PUT /api/timer/config` with an existing value — the connected `/events` client should receive `event: config` and `event: timer_state`. Prefer writing back existing config values so the club's display settings aren't altered.

## What does NOT exist

- No linter, formatter or typecheck. `ruff`, `black`, `mypy` are not configured — don't run them.
- No CI beyond deployment: `.github/workflows/main.yml` runs on push to `main` on a self-hosted Raspberry Pi (`git pull`, venv + `pip install`, `python -m hammertime.migrate`, `sudo systemctl restart curling-timer.service`).
- `install.sh` is the supported Pi install/upgrade path: it installs the **latest GitHub release** (release tarball via the GitHub API, falling back to the newest semver tag), records it in `<dir>/.release`, swaps the app tree in place (keeping `data/`, `.env`, `.venv`), then does deps → backup → migrations → systemd → health check. It **deletes `.git`**, so the `git pull` deployment above only works on a directory that was never release-installed. `--check` exits 0/10 (up to date/update available); `--tag` pins a release; migrations still gate on `__version__`.

## Gotchas

- `get_current_draw()` uses the **local timezone** for the current date — behavior depends on the host's TZ (and each kiosk's own clock for `tick()`; the server's `targetTime` is authoritative). Weekday names come from a hardcoded English tuple, not `strftime`, so locale can't change them.
- Weekly draws overlapping a same-day override are excluded for that date (overlap test). The **admin week view** instead suppresses a weekly draw when an override has the *same `start_time`* — that inconsistency is original behaviour and is pinned by `tests/test_db.py`.
- `get_current_draw()` puts override rows (rowid order, no `ORDER BY`) before weekly draws; that order decides which draw counts as "next". Don't "tidy" it.
- `POST /api/draws` / `POST /api/draw-overrides` respond with a nested id — `{"id": {"id": 5, "override": false}}` — because the original handler wrapped the data-layer return value. Preserved for the browser contract; the admin UI ignores it.
- Anything that must move the kiosk's display **over time** (not triggered by a write) has to go through a server-side push (`broadcast_timer_state`) — the client will not re-derive new draws on its own.
- Draw validation: weekly draws may not overlap other weekly draws (`validate_weekly_draw`); overrides may overlap anything and take precedence on their date.
- Known, accepted differences from the Node version (framework-level only): unmatched URLs and malformed JSON bodies return a JSON error instead of Express's HTML page; `HEAD` requests get 405 (Express routes them to the GET handler); `SameSite`/content-type attribute casing differs internally; DST fold/gap handling of wall-clock draw times uses naive local datetimes. No client depends on any of these.
- Trailing slashes: `hammertime/middleware.py` rewrites `/api/draws/` → `/api/draws` before routing because Express's non-strict routing accepts both. This matters — `public/admin.js` POSTs to `/api/draws/` when creating a draw, and without the rewrite the static mount answers it with 405. Don't remove that middleware.
