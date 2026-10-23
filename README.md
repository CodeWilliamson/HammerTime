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

For a Raspberry Pi deployment use [`install.sh`](#raspberry-pi-install--upgrade-script) — it
installs from the latest GitHub release. The manual steps below are for development:

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

### Raspberry Pi: install / upgrade script

`install.sh` installs from the **latest published GitHub release** (a release tarball, not a
git checkout) and is idempotent — run it again to upgrade:

```bash
# fresh machine — installs the latest release and sets up the systemd service
curl -fsSL https://raw.githubusercontent.com/CodeWilliamson/HammerTime/main/rpi_setup/install.sh | bash

# or from an installed copy
./rpi_setup/install.sh
```

Each run asks GitHub for the latest release and compares it with the release recorded in
`<dir>/.release`:

- **same version** → nothing is downloaded; `.venv`, `.env`, the database and the service are
  still checked/repaired
- **newer version** → the release tarball is downloaded, unpacked into a staging directory and
  swapped in (`data/`, `.env` and `.venv` are kept, stale files are removed), then dependencies,
  migrations and the service are updated
- **older version** → refused unless `--force` (downgrades are pointless: migrations are not reversible)

```bash
./rpi_setup/install.sh --check         # report only: exit 0 = up to date, 10 = update available
./rpi_setup/install.sh --tag v1.5.0    # install/pin a specific release
./rpi_setup/install.sh --force         # reinstall, or allow a downgrade
./rpi_setup/install.sh --no-restart    # update files + migrations, leave the service running
./rpi_setup/install.sh --no-nginx      # don't touch nginx; the app stays on its own port
./rpi_setup/install.sh --help          # all options
```

It also checks Python ≥ 3.11, `tar` and `python3-venv` (apt-installing what is missing), creates
`.env` with a random `JWT_SECRET` (an existing `.env` is never overwritten), backs up
`data/schedule.db` into `data/backups/` (last 10 kept), applies pending migrations, installs
`/etc/systemd/system/hammertime.service`, restarts it and waits for `/api/version` to answer.

### nginx on port 80

The last step puts nginx in front of the app, so a kiosk only needs `http://<pi>/`. nginx is
installed if missing, and `/etc/nginx/sites-available/hammertime.conf` (symlinked into
`sites-enabled/`) proxies port 80 to `127.0.0.1:<PORT>`. The Debian `default` site is disabled,
because HammerTime claims port 80 as `default_server` and two of those are a config error. The new
config must pass `nginx -t` before nginx is reloaded; if it doesn't, the previous config is put back
and the installer stops.

The proxy is set up for the `/events` SSE stream — `proxy_buffering off`, `proxy_cache off`,
`proxy_http_version 1.1`, `Connection ""`, a one hour read timeout — because a buffering proxy holds
frames back and the kiosk silently stops updating. Re-running the installer rewrites the file when
`PORT` changes. Use `--no-nginx` to skip this step entirely and keep the app on its own port.

Options are `--dir`, `--repo OWNER/NAME`, `--tag`, `--port`, `--service`, `--token`, `--check`,
`--force`, `--no-restart` and `--no-nginx`; each is also an `HAMMERTIME_*` environment variable
(e.g. `HAMMERTIME_SERVICE_NAME=curling-timer.service`, `HAMMERTIME_NGINX=0`,
`HAMMERTIME_GITHUB_TOKEN` for private repos).
`data/` and `.env` survive every upgrade; the kiosk browser unit is not managed by the installer.
The listening port comes from `PORT` in `.env`, so change it there rather than with `--port`.

> The install directory is **not** a git checkout — `.git` is removed on the first release
> install. If the repository has no published releases, the newest semver tag is used instead.

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

The suite is plain pytest — unit, data-layer, HTTP and browser tests. No Node.js is
required:

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m playwright install chromium   # once, for the browser tests
./.venv/bin/python -m pytest              # fast suite (~35 s)
./.venv/bin/python -m pytest -m slow      # adds the 20 s heartbeat / 60 s state-tick checks
./.venv/bin/python -m pytest -m visual    # opt-in screenshot baselines
```

| File | What it covers |
|---|---|
| `tests/test_units.py` | pure helpers (formatting, semver, SQL splitting, time math) |
| `tests/test_db.py` | `hammertime/db.py`: draw ordering, overlap rules, week view, config, users |
| `tests/test_timer_state.py` | the five timer statuses and their window boundaries |
| `tests/test_api.py` | routes, status codes, headers, cookies, auth, the admin CRUD flow |
| `tests/test_sse.py` | `/events`: `hello` snapshot, broadcasts, heartbeat/state tick (`slow`) |
| `tests/test_migrations.py` | schema shape, seed data, idempotency, semver gate, rollback |
| `tests/visual/` | the kiosk/admin/settings pages in Chromium (Playwright) |

`tests/support.py` builds the sandbox: a database migrated in a temp directory and seeded
with a canonical week (`WEEKLY_DRAWS` / `OVERRIDES`), plus frozen instants
(`WAITING`, `RUNNING`, …). `tests/conftest.py` turns that into fixtures
(`server`, `client`, `auth_client`, `db`). Tests never touch `data/schedule.db`, and the
whole suite runs in a pinned timezone (`America/Toronto`) with `HAMMERTIME_FAKE_NOW` set
per test, so "now" is always a known Wednesday.

**Visual tests.** `tests/visual/test_visual.py` drives a real browser against a real
server; the browser clock is frozen with Playwright's clock API at the same instant as
the server's, so countdowns render exact digits. The DOM/colour/interaction assertions run
with the normal suite; the screenshot baselines are marked `visual` and therefore opt-in
(they depend on the machine's fonts and Chromium build). Regenerate them with:

```bash
./.venv/bin/python -m pytest -m visual --update-baselines
```

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
tests/               # unit, data-layer, API, SSE, migration and browser tests
```
