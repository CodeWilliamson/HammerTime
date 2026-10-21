"""Migration tests.

The schema produced by ``python -m hammertime.migrate`` must be identical to the schema
the original Node migrator produced (captured in ``parity/golden/schema.json``), and
re-running it must never touch an up-to-date database — including the club's live one.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.parity.capture_schema import dump_schema
from tests.parity.harness import REPO_ROOT

GOLDEN_SCHEMA = Path(__file__).resolve().parent / "parity" / "golden" / "schema.json"


def _run_migrate(workdir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "hammertime.migrate"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
    )


def _prepare(workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "db_migrations").symlink_to(REPO_ROOT / "db_migrations", target_is_directory=True)


def test_fresh_migration_matches_node_schema(tmp_path):
    workdir = tmp_path / "fresh"
    _prepare(workdir)

    result = _run_migrate(workdir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Database schema is now at version 1.5.0" in result.stdout

    expected = json.loads(GOLDEN_SCHEMA.read_text(encoding="utf-8"))
    assert dump_schema(workdir / "data" / "schedule.db") == expected


def test_migration_is_idempotent(tmp_path):
    workdir = tmp_path / "twice"
    _prepare(workdir)

    first = _run_migrate(workdir)
    assert first.returncode == 0, first.stdout + first.stderr
    after_first = dump_schema(workdir / "data" / "schedule.db")

    second = _run_migrate(workdir)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "Running migration" not in second.stdout
    assert "Current DB schema version: 1.5.0" in second.stdout
    assert dump_schema(workdir / "data" / "schedule.db") == after_first


def test_migration_leaves_a_current_live_database_untouched(tmp_path):
    """Guards the club's real database: a copy at the current version is a no-op."""
    live = REPO_ROOT / "data" / "schedule.db"
    if not live.exists():
        pytest.skip("no local database to copy")

    workdir = tmp_path / "live-copy"
    (workdir / "data").mkdir(parents=True)
    _prepare(workdir)
    copy = workdir / "data" / "schedule.db"
    shutil.copyfile(live, copy)

    before = dump_schema(copy)
    result = _run_migrate(workdir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Running migration" not in result.stdout
    assert dump_schema(copy) == before


def test_migration_rolls_back_and_stops_on_failure(tmp_path):
    workdir = tmp_path / "broken"
    workdir.mkdir(parents=True)
    migrations = workdir / "db_migrations"
    migrations.mkdir()
    # 1.0.0 succeeds, 1.1.0 is invalid SQL, 1.2.0 must not run.
    (migrations / "1.0.0.sql").write_text("CREATE TABLE ok (id INTEGER);\n", encoding="utf-8")
    (migrations / "1.1.0.sql").write_text("CREATE TABLE broken (;\n", encoding="utf-8")
    (migrations / "1.2.0.sql").write_text("CREATE TABLE never (id INTEGER);\n", encoding="utf-8")

    result = _run_migrate(workdir)
    assert result.returncode == 0  # the script reports and stops, like the Node version
    assert "Migration 1.1.0 failed" in result.stdout

    connection = sqlite3.connect(workdir / "data" / "schedule.db")
    try:
        version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    finally:
        connection.close()

    assert version == "1.0.0"
    assert "ok" in tables
    assert "broken" not in tables
    assert "never" not in tables
