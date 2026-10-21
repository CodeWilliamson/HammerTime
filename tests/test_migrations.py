"""Migration runner tests (``python -m hammertime.migrate``).

These assert the shape of the schema, the seed data and the runner's rules (semver gate,
idempotency, rollback on failure) directly — no captured reference dump needed.
"""

from __future__ import annotations

import bcrypt
import shutil
import sqlite3

import pytest

from hammertime import __version__
from hammertime.migrate import compare_semver, parse_semver
from tests import support

MIGRATION_FILES = sorted(
    (path.stem for path in (support.REPO_ROOT / "db_migrations").glob("*.sql")),
    key=lambda version: parse_semver(version),
)
#: Highest migration this application version is allowed to run.
TARGET_VERSION = max(
    (version for version in MIGRATION_FILES if compare_semver(version, __version__) <= 0),
    default="0.0.0",
)

TIMER_CONFIG_COLUMNS = [
    "id",
    "background_color",
    "background_color_running",
    "background_color_warning",
    "background_color_critical",
    "timer_color_running",
    "timer_color_warning",
    "timer_color_critical",
    "status_color",
    "status_color_running",
    "status_color_warning",
    "status_color_critical",
    "message_color_running",
    "message_color_warning",
    "message_color_critical",
    "timer_font_size",
    "label_font_size",
    "message_font_size",
    "updated_at",
    "pre_draw_warning_threshold",
    "running_warning_threshold",
    "timer_color",
    "show_admin_url",
    "dynamic_timer_format",
]


def _use_repo_migrations(workdir) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "db_migrations").symlink_to(
        support.REPO_ROOT / "db_migrations", target_is_directory=True
    )


def _query(db_file, sql):
    connection = sqlite3.connect(db_file)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _schema_version(db_file) -> str:
    rows = _query(db_file, "SELECT version FROM schema_version")
    return rows[0][0] if rows else "0.0.0"


# ---------------------------------------------------------------------------
# Fresh migration
# ---------------------------------------------------------------------------

def test_fresh_migration_creates_the_expected_schema(tmp_path):
    workdir = tmp_path / "fresh"
    _use_repo_migrations(workdir)

    result = support.run_migrate(workdir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Database schema is now at version {TARGET_VERSION}" in result.stdout

    db_file = workdir / "data" / "schedule.db"
    schema = support.dump_schema(db_file)

    assert schema["schema_version"] == [TARGET_VERSION]
    assert schema["timer_config_columns"] == TIMER_CONFIG_COLUMNS
    assert schema["timer_config_rows"] == 1
    assert {row[0] for row in _query(
        db_file, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )} == {
        "draws",
        "draw_overrides",
        "schema_version",
        "timer_config",
        "users",
    }
    assert [row[1] for row in _query(db_file, "PRAGMA table_info(draws)")] == [
        "id",
        "day_of_week",
        "title",
        "message",
        "start_time",
        "duration_minutes",
    ]
    assert [row[1] for row in _query(db_file, "PRAGMA table_info(draw_overrides)")] == [
        "id",
        "date",
        "title",
        "message",
        "start_time",
        "duration_minutes",
    ]


def test_fresh_migration_seeds_the_default_admin(tmp_path):
    workdir = tmp_path / "seed"
    _use_repo_migrations(workdir)
    assert support.run_migrate(workdir).returncode == 0

    users = support.dump_schema(workdir / "data" / "schedule.db")["users"]
    assert [user["username"] for user in users] == ["timer"]
    assert bcrypt.checkpw(b"timer", users[0]["password_hash"].encode("ascii"))


def test_default_config_is_the_documented_starting_point(tmp_path):
    workdir = tmp_path / "config"
    _use_repo_migrations(workdir)
    assert support.run_migrate(workdir).returncode == 0

    row = _query(
        workdir / "data" / "schedule.db",
        "SELECT background_color_warning, background_color_critical, "
        "pre_draw_warning_threshold, running_warning_threshold, "
        "show_admin_url, dynamic_timer_format FROM timer_config",
    )[0]

    assert row == ("#ffae00", "#ff0000", 300, 900, 1, 1)


# ---------------------------------------------------------------------------
# Re-running
# ---------------------------------------------------------------------------

def test_migration_is_idempotent(tmp_path):
    workdir = tmp_path / "twice"
    _use_repo_migrations(workdir)

    first = support.run_migrate(workdir)
    assert first.returncode == 0, first.stdout + first.stderr
    schema = support.dump_schema(workdir / "data" / "schedule.db")

    second = support.run_migrate(workdir)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "Running migration" not in second.stdout
    assert f"Current DB schema version: {TARGET_VERSION}" in second.stdout
    assert support.dump_schema(workdir / "data" / "schedule.db") == schema


def test_migration_leaves_a_current_live_database_untouched(tmp_path):
    """Guards the club's real database: a copy at the current version is a no-op."""
    live = support.REPO_ROOT / "data" / "schedule.db"
    if not live.exists():
        pytest.skip("no local database to copy")

    workdir = tmp_path / "live-copy"
    (workdir / "data").mkdir(parents=True)
    _use_repo_migrations(workdir)
    copy = workdir / "data" / "schedule.db"
    shutil.copyfile(live, copy)

    before = support.dump_schema(copy)
    result = support.run_migrate(workdir)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Running migration" not in result.stdout
    assert support.dump_schema(copy) == before


# ---------------------------------------------------------------------------
# Version gate
# ---------------------------------------------------------------------------

def test_migrations_newer_than_the_app_version_are_skipped(tmp_path):
    workdir = tmp_path / "gated"
    migrations = workdir / "db_migrations"
    migrations.mkdir(parents=True)
    (migrations / "1.0.0.sql").write_text("CREATE TABLE applied (id INTEGER);\n", encoding="utf-8")
    (migrations / "99.0.0.sql").write_text("CREATE TABLE too_new (id INTEGER);\n", encoding="utf-8")

    result = support.run_migrate(workdir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Running migration 99.0.0" not in result.stdout

    tables = {row[0] for row in _query(workdir / "data" / "schedule.db", "SELECT name FROM sqlite_master")}
    assert "applied" in tables
    assert "too_new" not in tables
    assert _schema_version(workdir / "data" / "schedule.db") == "1.0.0"


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

def test_migration_rolls_back_and_stops_on_failure(tmp_path):
    workdir = tmp_path / "broken"
    migrations = workdir / "db_migrations"
    migrations.mkdir(parents=True)
    # 1.0.0 succeeds, 1.1.0 creates a table and then fails, 1.2.0 must not run.
    (migrations / "1.0.0.sql").write_text("CREATE TABLE ok (id INTEGER);\n", encoding="utf-8")
    (migrations / "1.1.0.sql").write_text(
        "CREATE TABLE half_done (id INTEGER);\nCREATE TABLE broken (;\n", encoding="utf-8"
    )
    (migrations / "1.2.0.sql").write_text("CREATE TABLE never (id INTEGER);\n", encoding="utf-8")

    result = support.run_migrate(workdir)
    # The runner reports the failure and stops, like the Node version (exit code 0).
    assert result.returncode == 0
    assert "Migration 1.1.0 failed" in result.stdout
    assert "Running migration 1.2.0" not in result.stdout

    db_file = workdir / "data" / "schedule.db"
    assert _schema_version(db_file) == "1.0.0"
    tables = {row[0] for row in _query(db_file, "SELECT name FROM sqlite_master")}
    assert "ok" in tables
    # The statements that ran before the failure were rolled back with the file.
    assert "half_done" not in tables
    assert "never" not in tables
