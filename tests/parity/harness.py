"""Sandbox helpers for the parity suite.

Every test runs both servers against throw-away copies of a database built from
``db_migrations/`` and seeded with a canonical schedule. The club's real
``data/schedule.db`` is never touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY_DIR = Path(__file__).resolve().parent

#: Secret used by both servers so JWTs are byte-comparable (>=32 bytes for HS256).
JWT_SECRET = "parity-secret-do-not-use-0123456789abcdef"

#: Canonical schedule. Dates are relative to a fixed week so the tests are stable.
WEEKLY_DRAWS = [
    ("Sunday", "Sunday Morning", "", "09:00", 90),
    ("Sunday", "Sunday Evening", "Open league", "19:00", 120),
    ("Wednesday", "Valley League", "", "18:30", 110),
    ("Wednesday", "Late League", None, "21:00", 60),
    ("Thursday", "Thursday Club", "Club night", "19:00", 120),
]

OVERRIDES = [
    # Same start_time as the Wednesday weekly draw (week view dedupes by start_time).
    ("2026-10-21", "Bonspiel Draw 1", "Sheet 1-4", "18:30", 90),
    # Non-overlapping override: the 21:00 weekly draw still runs.
    ("2026-10-21", "Bonspiel Lunch", None, "12:00", 60),
    # Overlaps the Thursday weekly draw (override wins, weekly draw is excluded).
    ("2026-10-22", "Bonspiel Final", "Championship", "19:00", 90),
    # Future bonspiel (after the current week).
    ("2026-11-07", "Future Bonspiel", None, "10:00", 120),
    # Past override: must not appear in the week view or future overrides.
    ("2026-10-14", "Past Event", None, "19:00", 60),
]


#: Moments that exercise every timer status and the week-view boundaries.
INSTANTS = [
    ("tuesday-idle", "2026-10-20T12:00:00"),
    ("wednesday-waiting", "2026-10-21T10:00:00"),
    ("wednesday-pre-draw", "2026-10-21T18:25:00"),
    ("wednesday-running", "2026-10-21T19:30:00"),
    ("wednesday-complete", "2026-10-21T20:25:00"),
    ("wednesday-late-running", "2026-10-21T21:30:00"),
    ("thursday-override-running", "2026-10-22T19:30:00"),
    ("friday-idle", "2026-10-23T12:00:00"),
    ("sunday-week-start", "2026-10-25T09:30:00"),
    ("saturday-future-override", "2026-11-07T09:30:00"),
]

#: Instant used for the full read/write scenario.
MUTATION_INSTANT = "2026-10-21T10:00:00"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


#: Pinned so payloads containing it are reproducible across runs and machines.
PINNED_UPDATED_AT = "2026-10-20 00:00:00"


def seed_database(db_file: Path) -> None:
    """Insert the canonical schedule into a freshly migrated database."""
    connection = sqlite3.connect(db_file, isolation_level=None)
    try:
        connection.execute(
            "UPDATE timer_config SET updated_at = ?", (PINNED_UPDATED_AT,)
        )
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
    """Run the Python migration runner in ``workdir`` and return the resulting DB."""
    workdir.mkdir(parents=True, exist_ok=True)
    _link_shared_files(workdir)
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "hammertime.migrate"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"migration failed:\n{result.stdout}\n{result.stderr}")

    db_file = workdir / "data" / "schedule.db"
    seed_database(db_file)
    return db_file


def _link_shared_files(root: Path) -> None:
    """Expose the repo's public/ and db_migrations/ inside a sandbox (cwd-relative)."""
    for name in ("public", "db_migrations"):
        link = root / name
        if link.is_symlink():
            link.unlink()
        if not link.exists():
            link.symlink_to(REPO_ROOT / name, target_is_directory=True)


@dataclass
class Server:
    name: str
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


def _sandbox(root: Path, template_db: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _link_shared_files(root)
    (root / "data").mkdir(exist_ok=True)
    shutil.copyfile(template_db, root / "data" / "schedule.db")
    return root


def _base_env(frozen_now: str, port: int) -> Dict[str, str]:
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


def _wait_ready(base_url: str, process: subprocess.Popen, log_file: Path, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"server exited early ({process.returncode}):\n{log_file.read_text(errors='replace')}"
            )
        try:
            if httpx.get(f"{base_url}/api/version", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.05)
    raise RuntimeError(f"server did not become ready:\n{log_file.read_text(errors='replace')}")


def start_node(root: Path, template_db: Path, frozen_now: str) -> Server:
    port = _free_port()
    sandbox = _sandbox(root, template_db)
    log_file = root / "node.log"
    handle = open(log_file, "w")
    process = subprocess.Popen(
        ["node", "--import", str(PARITY_DIR / "fake_clock.mjs"), str(REPO_ROOT / "index.js")],
        cwd=sandbox,
        env=_base_env(frozen_now, port),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    server = Server("node", f"http://127.0.0.1:{port}", process, sandbox, log_file)
    _wait_ready(server.base_url, process, log_file)
    return server


def start_python(root: Path, template_db: Path, frozen_now: str) -> Server:
    port = _free_port()
    sandbox = _sandbox(root, template_db)
    log_file = root / "python.log"
    handle = open(log_file, "w")
    process = subprocess.Popen(
        [sys.executable, "-m", "hammertime"],
        cwd=sandbox,
        env=_base_env(frozen_now, port),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    server = Server("python", f"http://127.0.0.1:{port}", process, sandbox, log_file)
    _wait_ready(server.base_url, process, log_file)
    return server


def node_available() -> bool:
    return shutil.which("node") is not None and (REPO_ROOT / "index.js").exists()


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------

def normalise_cookie(raw: str) -> Optional[Dict[str, str]]:
    """Reduce a Set-Cookie header to the parts a browser actually depends on."""
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(";") if part.strip()]
    name, _, value = parts[0].partition("=")
    attributes = {name.lower(): value}
    for part in parts[1:]:
        key, _, attr_value = part.partition("=")
        key = key.strip().lower()
        # Expires is derived from Max-Age; its exact rendering differs between stacks.
        if key == "expires":
            continue
        value = attr_value.strip()
        if key == "samesite":
            # Attribute values are case-insensitive ("Strict" vs "strict").
            value = value.lower()
        attributes[key] = value
    return attributes


#: Values that legitimately differ between runs/machines and are therefore masked.
_HOST_URL = re.compile(r"^http://\d{1,3}(?:\.\d{1,3}){3}/admin$")


def _normalise_value(value):
    if isinstance(value, dict):
        return {
            key: (
                "<timestamp>"
                if key == "updated_at"
                # `__version__` is now the single source of truth and is intentionally
                # free to move ahead of the frozen Node reference's package.json.
                else "<version>"
                if key == "version"
                else _normalise_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalise_value(item) for item in value]
    if isinstance(value, str) and _HOST_URL.match(value):
        return "http://<host-ip>/admin"
    return value


def normalise_content_type(value: str) -> str:
    """Case/alias-insensitive content type.

    Express sends ``text/html; charset=UTF-8``, Starlette ``text/html; charset=utf-8``,
    and the two disagree on ``application/javascript`` vs ``text/javascript``. None of
    that is observable to a browser, so it is masked out of the comparison.
    """
    lowered = (value or "").lower()
    return lowered.replace("text/javascript", "application/javascript")


def normalise_response(response: httpx.Response) -> Dict[str, object]:
    content_type = response.headers.get("content-type", "")
    body: object
    if content_type.startswith("application/json") and response.content:
        try:
            body = _normalise_value(response.json())
        except json.JSONDecodeError:  # pragma: no cover - defensive
            body = response.text
    elif not response.content:
        body = None
    else:
        body = "<html>"

    return {
        "status": response.status_code,
        "content_type": normalise_content_type(content_type),
        "cookie": normalise_cookie(response.headers.get("set-cookie", "")),
        "body": body,
    }


def read_frame(lines) -> Dict[str, object]:
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
