# HammerTime

**A curling rink draw timer built for Raspberry Pi kiosk displays.**

HammerTime shows players and spectators the time remaining in the current draw, automatically transitioning through draw states — pre-draw countdown, active timer, and completion — based on a weekly schedule (or a local timer instance if running on a tablet). Date-specific overrides let you easily accommodate bonspiels or other special events without changing your regular schedule.

<a href="https://www.buymeacoffee.com/marksmakes" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a>

---

## Features

- **Full-screen countdown timer** designed to be displayed on a large screen at the rink
- **Automatic draw state management** — no manual intervention needed during the day
- **Local timer** — Tap screen running timer to start a disconnected local version (tablet)
- **Weekly recurring draws** configured once and repeated every week
- **Date-specific overrides** for bonspiels and special events that replace or supplement the regular schedule
- **Configurable display** — fully customizable colors and font sizes per timer state, managed through the admin panel
- **Admin panel** with a visual weekly calendar to manage draws and overrides

---

## Timer States

| State | Description |
|---|---|
| `idle` | No draws scheduled today |
| `waiting` | Next draw is more than 10 minutes away — shows the upcoming draw start time |
| `pre_draw` | Within 10 minutes of draw start — counts down to start time |
| `running` | Draw is in progress — counts down remaining time |
| `complete` | Draw has just ended — shown for up to 10 minutes after finish |

The display background and text colors change automatically as time runs low:

- **Warning** — triggered when a running draw has less than the configured warning threshold remaining (default: 15 minutes)
- **Critical** — triggered when the timer reaches zero

---

## Tech Stack

- **Runtime:** Python 3.11+
- **Server:** FastAPI + Uvicorn (ASGI)
- **Database:** SQLite (`sqlite3` from the standard library)
- **Auth:** JWT (`PyJWT`) in an httpOnly cookie
- **Frontend:** Vanilla HTML, CSS, and JavaScript (no build step)
- **Real-time updates:** Server-Sent Events
- **Deployment model:** Raspberry Pi running as a `systemd` service

---

## Getting Started

### Prerequisites

- Python 3.11 or newer (`python3-venv` on Raspberry Pi OS)
- sqlite3

### Installation

```bash
git clone https://github.com/CodeWilliamson/HammerTime.git
cd HammerTime
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

### Initialize the database

Run migrations to create the database schema and seed the default admin user:

```bash
./.venv/bin/python -m hammertime.migrate
```

This creates `data/schedule.db` and applies all pending SQL migrations from the `db_migrations/` directory.

### Start the server

```bash
./.venv/bin/python -m hammertime
```

The app will be available at [http://localhost:3000](http://localhost:3000).

> Run every command from the repository root: `data/`, `public/` and `db_migrations/` are resolved relative to the working directory.

---

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `PORT` | `3000` | Port the server listens on |
| `JWT_SECRET` | `timertimertimer` | Secret key for signing JWT tokens — **change this in production** |
| `DEBUG` | unset | When set (any non-empty value, including `false`), log SSE connects/disconnects and every broadcast |

Values are read from `.env` (see `.env.example`-style usage below) with real environment variables taking precedence:

```ini
PORT=3000
JWT_SECRET=change-me
DEBUG=1
```

> **Note for upgraders:** the previous Node version evaluated `JWT_SECRET` *before* loading
> `.env`, so `.env`'s value was silently ignored and the default secret was always used.
> The Python version honours `.env`, so existing login sessions are invalidated once on
> cutover (log in again and you are done).

---

## Usage

### Timer display

Open `http://<your-host>:3000` in a browser. The timer display is public — no login required. It receives live updates over Server-Sent Events and reconnects automatically.

### Admin panel

Navigate to `http://<your-host>:3000/admin` and log in with your admin credentials.

**Default credentials (change after first login):**

| Username | Password |
|---|---|
| `timer` | `timer` |

From the admin panel you can:

- **Manage weekly draws** — add, edit, or remove recurring draws for any day of the week. Each draw has a title, an optional message displayed on screen, a start time, and a duration.
- **Add date-specific overrides** — create a one-off draw for a specific date (e.g., a bonspiel). Overrides on a given date replace any regular weekly draw that overlaps with them.
- **Configure the timer display** — customize all colors (idle, running, warning, critical states) and font sizes. Changes take effect on the display within a few seconds without a page refresh.
- **Change your password** via the login page.

---

## Draw Overrides (Bonspiels)

When a date has one or more overrides defined, weekly draws that overlap with any override are automatically excluded for that date. Non-overlapping weekly draws still run as normal. This allows you to add bonspiel draws for a specific day without needing to remove or temporarily disable your regular schedule.

---

## Database Migrations

Migration files live in `db_migrations/` and are named using semantic versioning (e.g., `1.0.0.sql`, `1.1.0.sql`). The migration script tracks the current schema version in a `schema_version` table and only applies migrations newer than the current version — and not newer than the application version in `hammertime/__init__.py`.

**Bump `__version__` in `hammertime/__init__.py` when you add a migration**, otherwise the new file will be skipped.

To run migrations manually:

```bash
./.venv/bin/python -m hammertime.migrate
```

---

## Testing

The project has a parity + regression suite (no Node.js required to run it):

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest              # fast suite
./.venv/bin/python -m pytest -m slow      # 20 s heartbeat / 60 s state-tick checks
```

- `tests/parity/golden/` holds response fixtures captured from the original Node.js
  implementation, so the ported server is still checked against it.
- `tests/test_migrations.py` verifies the schema matches the original migrator's output
  and that re-running migrations leaves an up-to-date database untouched.
- The A/B tests (`test_ab_parity.py`, `test_sse_parity.py`) start both servers on
  throw-away database copies and diff status codes, headers, cookies, JSON bodies and SSE
  frames. They skip automatically when `index.js` is not present; to regenerate the golden
  fixtures, check the pre-port commit out into a scratch worktree, run
  `python -m tests.parity.capture_golden` and `python -m tests.parity.capture_schema`,
  and copy the resulting `tests/parity/golden/` back.

The tests never touch `data/schedule.db` — they build their own database from the
migrations in a temporary directory.

---

## Project Layout

```
hammertime/
  __main__.py        # python -m hammertime (server entrypoint)
  main.py            # app wiring: static files, /admin, /api/version, routers, /events
  config.py          # .env loading, cwd-relative paths, DEBUG flag
  db.py              # SQLite queries + weekly draw overlap validation
  auth.py            # login / change-password / require_auth
  timer_state.py     # idle / waiting / pre_draw / running / complete state machine
  broadcast.py       # SSE hub (hello snapshots, broadcasts, heartbeats)
  migrate.py         # python -m hammertime.migrate
  clock.py           # single source of "now" (test hook: HAMMERTIME_FAKE_NOW)
  util.py            # host IP discovery
  routes/            # timer, draws, draw-overrides REST routes
public/              # static frontend (kiosk, admin, settings, login)
db_migrations/       # versioned SQL migrations
tests/               # parity, golden, migration and unit tests
```
