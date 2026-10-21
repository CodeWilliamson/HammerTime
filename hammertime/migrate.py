"""Database migration runner — direct port of ``db_migrate.js``.

Applies every ``db_migrations/*.sql`` file whose semver is newer than the recorded
``schema_version`` and not newer than the application version. Each file runs inside a
single transaction; on failure the transaction is rolled back and no further migrations
are applied. Re-running is safe.

Usage:
    python -m hammertime.migrate
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator, Tuple

from hammertime import __version__

MIGRATIONS_DIR = Path("db_migrations")
DATA_DIR = Path("data")
DB_FILE = DATA_DIR / "schedule.db"


def parse_semver(version: str) -> Tuple[int, int, int, Tuple[Tuple[int, str], ...]]:
    """Parse ``major.minor.patch[-prerelease]``; missing parts count as 0."""
    core, _, prerelease = version.partition("-")
    numbers = []
    for part in core.split("."):
        digits = "".join(char for char in part if char.isdigit())
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    pre = tuple(
        (0, int(ident)) if ident.isdigit() else (1, ident)
        for ident in prerelease.split(".")
        if ident
    )
    return numbers[0], numbers[1], numbers[2], pre


def compare_semver(left: str, right: str) -> int:
    """Return -1/0/1 for left<right, equal, left>right (semver precedence)."""
    l_major, l_minor, l_patch, l_pre = parse_semver(left)
    r_major, r_minor, r_patch, r_pre = parse_semver(right)

    core = (l_major, l_minor, l_patch)
    other = (r_major, r_minor, r_patch)
    if core != other:
        return -1 if core < other else 1

    # A version with a prerelease has lower precedence than one without.
    if not l_pre and not r_pre:
        return 0
    if not l_pre:
        return 1
    if not r_pre:
        return -1
    if l_pre == r_pre:
        return 0
    return -1 if l_pre < r_pre else 1


def split_statements(sql: str) -> Iterator[str]:
    """Split a SQL script into complete statements (comments and multi-line safe)."""
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement:
                yield statement
    if buffer.strip():
        yield buffer.strip()


def main() -> None:
    # Ensure the data directory exists before opening the database.
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(DB_FILE), isolation_level=None)
    try:
        app_schema_version = __version__
        print(f"App version: {app_schema_version}")

        # 1. Ensure schema_version table exists.
        # The exact text is kept so a fresh database stores the same schema SQL as the
        # Node migrator (which used the same multi-line literal).
        connection.execute(
            """
  CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT NOT NULL
  );
"""
        )

        # 2. Get current schema version (default 0.0.0 if not set).
        row = connection.execute("SELECT version FROM schema_version").fetchone()
        current_version = row[0] if row else "0.0.0"
        print(f"Current DB schema version: {current_version}")
        print(f"Target schema version: {app_schema_version}")

        # 3. Collect and sort all migration files using semver.
        migration_files = sorted(
            (name for name in MIGRATIONS_DIR.iterdir() if name.suffix == ".sql"),
            key=lambda path: _semver_key(path.stem),
        ) if MIGRATIONS_DIR.exists() else []

        # 4. Run migrations newer than current version and <= target.
        for path in migration_files:
            file_version = path.stem
            if not (
                compare_semver(file_version, current_version) > 0
                and compare_semver(file_version, app_schema_version) <= 0
            ):
                continue

            print(f"➡️ Running migration {file_version}...")
            sql = path.read_text(encoding="utf-8")

            # Run inside a transaction for safety.
            try:
                connection.execute("BEGIN")
                for statement in split_statements(sql):
                    connection.execute(statement)
                connection.execute("COMMIT")
            except sqlite3.Error as error:
                connection.execute("ROLLBACK")
                print(f"❌ Migration {file_version} failed:", error)
                print("Rolling back...")
                break  # stop further migrations

            print(f"✅ Migration {file_version} applied successfully.")
            connection.execute("DELETE FROM schema_version")
            connection.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (file_version,)
            )
            current_version = file_version

        print(f"📦 Database schema is now at version {current_version}")
    finally:
        connection.close()


def _semver_key(version: str):
    """Sort key matching ``files.sort((a, b) => semver.compare(a, b))``."""
    major, minor, patch, pre = parse_semver(version)
    # Prerelease versions sort before the release itself.
    return (major, minor, patch, 1 if not pre else 0, pre)


if __name__ == "__main__":
    main()
