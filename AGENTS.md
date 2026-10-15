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
- Migrations: `db_migrations/*.sql`, named by semver (e.g. `1.0.0.sql`, `1.3.0.sql`). `npm run migrate` applies only migrations newer than the tracked `schema_version` and `<= ` the version in `package.json`; re-running is safe.
- `data/.gitkeep` is tracked; `data/schedule.db` is local/untracked — **do not commit it**.
- Schema: `draws` (recurring weekly draws), `draw_overrides` (date-specific, e.g. bonspiels), `timer_config`, `users`.

## Auth

- JWT in an httpOnly cookie (`/auth/login`), `requireAuth` middleware guards admin APIs.
- Default admin credentials: `timer` / `timer` (change after first login). Seeded by the `1.0.0` migration.

## Frontend

- `public/` is served statically by Express. Entry pages: `index.html` (timer display, public), `login.html`, `admin.html`, `settings.html`.
- No build step — edit HTML/CSS/JS in `public/` directly.

## What does NOT exist

- No test suite, no linter, no formatter, no typecheck (plain JS). `npm test`, `npm run lint`, etc. are not defined — don't run them.
- No CI beyond deployment: `.github/workflows/main.yml` runs on push to `main` on a self-hosted Raspberry Pi (`git pull`, `npm install`, `npm run migrate`, `sudo systemctl restart curling-timer.service`).

## Gotchas

- `getCurrentDraw()` in `db.js` uses the **local timezone** for the current date — behavior depends on the host's TZ.
- Weekly draws overlapping a same-day override are excluded for that date; non-overlapping weekly draws still run.
- Frontend polls `/api/timer/state` every few seconds; config changes push via `updated_at` comparison against `lastConfigSeenAt`.