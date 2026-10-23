"""Sandbox helpers shared by the test suite.

Tests never touch the club's real ``data/schedule.db``. Each one works against a
throw-away copy of a database built from ``db_migrations/`` (by running
``python -m hammertime.migrate``) and seeded with the canonical schedule below. Tests
either exercise the data layer in-process or start the real server against that copy on
a free port.

The server's clock is pinned with ``HAMMERTIME_FAKE_NOW`` (see ``hammertime/clock.py``)
so timer states are deterministic. The visual tests pin the browser to the same instant.
"""

from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Timezone pinned for the whole suite, so frozen instants mean the same thing to the
#: in-process tests, the sandbox servers and the browser (see ``tests/conftest.py``).
TEST_TIMEZONE = "America/Toronto"

#: Secret handed to the sandbox server so tests can sign/inspect tokens (>=32 bytes).
JWT_SECRET = "test-secret-do-not-use-0123456789abcdef"

#: Pinned so payloads containing it are reproducible across runs and machines.
PINNED_UPDATED_AT = "2026-10-20 00:00:00"

#: Canonical schedule, anchored to the week of 2026-10-18 (Sunday).
WEEKLY_DRAWS = [
    ("Sunday", "Sunday Morning", "", "09:00", 90),
    ("Sunday", "Sunday Evening", "Open league", "19:00", 120),
    ("Wednesday", "Valley League", "", "18:30", 110),
    ("Wednesday", "Late League", None, "21:00", 60),
    ("Thursday", "Thursday Club", "Club night", "19:00", 120),
]

OVERRIDES = [
    # Same start_time as the Wednesday weekly draw (the week view dedupes by start_time)
    # and overlaps it (get_current_draw excludes it for that date).
    ("2026-10-21", "Bonspiel Draw 1", "Sheet 1-4", "18:30", 90),
    # Non-overlapping override: the 21:00 weekly draw still runs.
    ("2026-10-21", "Bonspiel Lunch", None, "12:00", 60),
    # Overlaps the Thursday weekly draw (the override wins, the weekly draw is excluded).
    ("2026-10-22", "Bonspiel Final", "Championship", "19:00", 90),
    # Future bonspiel (after the current week).
    ("2026-11-07", "Future Bonspiel", None, "10:00", 120),
    # Past override: must not appear in the week view or in futureOverrides.
    ("2026-10-14", "Past Event", None, "19:00", 60),
]

# ---------------------------------------------------------------------------
# Frozen instants (local wall-clock time)
#
# On Wednesday 2026-10-21 the effective schedule is: "Bonspiel Lunch" 12:00-13:00,
# "Bonspiel Draw 1" 18:30-20:00, "Late League" 21:00-22:00 (the weekly 18:30 draw is
# excluded because it overlaps the 18:30 override).
# ---------------------------------------------------------------------------

#: Next draw is the 18:30 bonspiel draw (overrides keep rowid order, not time order).
WAITING = "2026-10-21T10:00:00"
#: 5 minutes before the 18:30 draw.
PRE_DRAW = "2026-10-21T18:25:00"
#: Exactly 600 s before the 18:30 draw — the first second of ``pre_draw``.
PRE_DRAW_BOUNDARY = "2026-10-21T18:20:00"
#: 19:30-20:00 of the 18:30 draw.
RUNNING = "2026-10-21T19:30:00"
#: 10 minutes left: below the default ``running_warning_threshold`` of 900 s.
WARNING = "2026-10-21T19:50:00"
#: 5 minutes after the 18:30 draw ended.
COMPLETE = "2026-10-21T20:05:00"
#: Exactly 600 s after the draw ended — the last second of ``complete``.
COMPLETE_BOUNDARY = "2026-10-21T20:10:00"
#: The 21:00 weekly draw is running.
LATE_RUNNING = "2026-10-21T21:30:00"
#: Friday: nothing scheduled that day.
IDLE = "2026-10-23T12:00:00"

#: Instant used when a test does not care about the time of day.
DEFAULT_INSTANT = WAITING


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def seed_database(db_file: Path) -> None:
    """Insert the canonical schedule into a freshly migrated database."""
    connection = sqlite3.connect(db_file, isolation_level=None)
    try:
        connection.execute("UPDATE timer_config SET updated_at = ?", (PINNED_UPDATED_AT,))
        connection.executemany(
            """
            INSERT INTO draws (day_of_week, title, message, start_time, duration_minutes)
            VALUES (?, ?, ?, ?, ?)
            """,
            WEEKLY_DRAWS,
        )
        connection.executemany(
            """
            INSERT INTO draw_overrides (date, title, message, start_time, duration_minutes)
            VALUES (?, ?, ?, ?, ?)
            """,
            OVERRIDES,
        )
    finally:
        connection.close()


def build_template_database(workdir: Path) -> Path:
    """Run the migration runner in ``workdir`` and return the resulting database."""
    workdir.mkdir(parents=True, exist_ok=True)
    link_shared_files(workdir)
    result = run_migrate(workdir)
    if result.returncode != 0:
        raise RuntimeError(f"migration failed:\n{result.stdout}\n{result.stderr}")

    db_file = workdir / "data" / "schedule.db"
    seed_database(db_file)
    return db_file


def run_migrate(workdir: Path) -> subprocess.CompletedProcess:
    """Run ``python -m hammertime.migrate`` inside ``workdir``."""
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "hammertime.migrate"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
    )


def link_shared_files(root: Path) -> None:
    """Expose the repo's ``public/`` and ``db_migrations/`` inside a sandbox.

    The application resolves both paths relative to the working directory.
    """
    for name in ("public", "db_migrations"):
        link = root / name
        if link.is_symlink():
            link.unlink()
        if not link.exists():
            link.symlink_to(REPO_ROOT / name, target_is_directory=True)


def make_sandbox(root: Path, template_db: Path) -> Path:
    """Create a working directory containing a copy of the template database."""
    root.mkdir(parents=True, exist_ok=True)
    link_shared_files(root)
    (root / "data").mkdir(exist_ok=True)
    shutil.copyfile(template_db, root / "data" / "schedule.db")
    return root


def connect(db_file: Path) -> sqlite3.Connection:
    """Open a connection with the settings ``hammertime.db`` uses."""
    connection = sqlite3.connect(str(db_file), isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def dump_schema(db_file: Path) -> Dict[str, object]:
    """Everything that describes the schema and seed data, in a stable order."""
    connection = sqlite3.connect(db_file)
    try:
        objects = [
            {"type": row[0], "name": row[1], "tbl_name": row[2], "sql": row[3]}
            for row in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            )
        ]
        version = [row[0] for row in connection.execute("SELECT version FROM schema_version")]
        users = [
            {"username": row[0], "password_hash": row[1]}
            for row in connection.execute("SELECT username, password_hash FROM users ORDER BY id")
        ]
        columns = [row[1] for row in connection.execute("PRAGMA table_info(timer_config)")]
        config_rows = connection.execute("SELECT COUNT(*) FROM timer_config").fetchone()[0]
    finally:
        connection.close()

    return {
        "objects": objects,
        "schema_version": version,
        "users": users,
        "timer_config_rows": config_rows,
        "timer_config_columns": columns,
    }


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

@dataclass
class Server:
    base_url: str
    process: subprocess.Popen
    sandbox: Path
    log_file: Path

    def log(self) -> str:
        return self.log_file.read_text(errors="replace")

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - stubborn process
            self.process.kill()
            self.process.wait(timeout=10)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _server_env(frozen_now: str, port: int) -> Dict[str, str]:
    # Drop inherited values so a developer's shell cannot change the sandbox.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DEBUG", "HAMMERTIME_FAKE_NOW", "PORT", "JWT_SECRET"}
    }
    env.update(
        {
            "PORT": str(port),
            "JWT_SECRET": JWT_SECRET,
            "HAMMERTIME_FAKE_NOW": frozen_now,
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    return env


def _wait_ready(server: Server, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server.process.poll() is not None:
            raise RuntimeError(
                f"server exited early ({server.process.returncode}):\n{server.log()}"
            )
        try:
            if httpx.get(f"{server.base_url}/api/version", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.05)
    raise RuntimeError(f"server did not become ready:\n{server.log()}")


def start_server(root: Path, template_db: Path, frozen_now: str = DEFAULT_INSTANT) -> Server:
    """Start the application against a sandbox copy, frozen at ``frozen_now``."""
    port = _free_port()
    sandbox = make_sandbox(root, template_db)
    log_file = root / "server.log"
    handle = open(log_file, "w")
    process = subprocess.Popen(
        [sys.executable, "-m", "hammertime"],
        cwd=sandbox,
        env=_server_env(frozen_now, port),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    server = Server(f"http://127.0.0.1:{port}", process, sandbox, log_file)
    _wait_ready(server)
    return server


# ---------------------------------------------------------------------------
# Server-Sent Events
# ---------------------------------------------------------------------------

def read_frame(lines: List[str]) -> Dict[str, object]:
    """Read one SSE frame from an iterator of raw lines (comments are skipped)."""
    event = None
    data: List[str] = []
    for line in lines:
        line = line.rstrip("\n")
        if line.startswith(":"):
            continue
        if not line:
            if event is not None or data:
                return {"event": event, "data": "\n".join(data)}
            continue
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:"):].lstrip())
    raise AssertionError("SSE stream ended before a complete frame was read")
