# HammerTime

**A curling rink draw timer built for Raspberry Pi kiosk displays.**

HammerTime shows players and spectators the time remaining in the current draw, automatically transitioning through draw states — pre-draw countdown, active timer, and completion — based on a weekly schedule. Date-specific overrides let you easily accommodate bonspiels or other special events without changing your regular schedule.

[![Deploy on Raspberry Pi](https://github.com/CodeWilliamson/HammerTime/actions/workflows/main.yml/badge.svg)](https://github.com/CodeWilliamson/HammerTime/actions/workflows/main.yml)

---

## Features

- **Full-screen countdown timer** designed to be displayed on a large screen at the rink
- **Automatic draw state management** — no manual intervention needed during the day
- **Weekly recurring draws** configured once and repeated every week
- **Date-specific overrides** for bonspiels and special events that replace or supplement the regular schedule
- **Configurable display** — fully customizable colors and font sizes per timer state, managed through the admin panel
- **Admin panel** with a visual weekly calendar to manage draws and overrides
- **JWT-authenticated admin routes** to protect schedule and config changes
- **Automatic database migrations** using semver-versioned SQL files
- **Raspberry Pi + GitHub Actions CI/CD** — push to `main` and the rink display updates automatically

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

- **Runtime:** Node.js with ES Modules
- **Server:** Express 5
- **Database:** SQLite via `better-sqlite3`
- **Auth:** JWT (`jsonwebtoken`) + bcrypt (`bcryptjs`) with `httpOnly` cookies
- **Frontend:** Vanilla HTML, CSS, and JavaScript — no framework required
- **Deployment target:** Raspberry Pi running as a `systemd` service

---

## Getting Started

### Prerequisites

- Node.js 18+
- npm

### Installation

```bash
git clone https://github.com/CodeWilliamson/HammerTime.git
cd HammerTime
npm install
```

### Initialize the database

Run migrations to create the database schema and seed the default admin user:

```bash
npm run migrate
```

This creates `data/schedule.db` and applies all pending SQL migrations from the `db_migrations/` directory.

### Start the server

```bash
npm start
```

The app will be available at [http://localhost:3000](http://localhost:3000).

---

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `PORT` | `3000` | Port the server listens on |
| `JWT_SECRET` | `timertimertimer` | Secret key for signing JWT tokens — **change this in production** |

---

## Usage

### Timer display

Open `http://<your-host>:3000` in a browser. The timer display is public — no login required. It polls the server every few seconds and updates automatically.

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

Migration files live in `db_migrations/` and are named using semantic versioning (e.g., `1.0.0.sql`, `1.1.0.sql`). The migration script tracks the current schema version in a `schema_version` table and only applies migrations newer than the current version.

To run migrations manually:

```bash
npm run migrate
```

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/timer/state` | No | Current timer state (used by the display page) |
| `GET` | `/api/timer/config` | Yes | Full timer display config |
| `PUT` | `/api/timer/config` | Yes | Update timer display config |
| `GET` | `/api/draws` | Yes | List all weekly draws |
| `POST` | `/api/draws` | Yes | Create a weekly draw |
| `PUT` | `/api/draws/:id` | Yes | Update a weekly draw |
| `DELETE` | `/api/draws/:id` | Yes | Delete a weekly draw |
| `POST` | `/api/draw-overrides` | Yes | Create a date-specific override |
| `PUT` | `/api/draw-overrides/:id` | Yes | Update an override |
| `DELETE` | `/api/draw-overrides/:id` | Yes | Delete an override |
| `POST` | `/auth/login` | No | Log in and receive a session cookie |
| `POST` | `/auth/change-password` | No | Change admin password |
