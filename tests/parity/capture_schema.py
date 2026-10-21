"""Capture the reference database schema produced by the original Node migrator.

Usage (from the repository root, with node_modules installed):

    python -m tests.parity.capture_schema

Writes ``tests/parity/golden/schema.json``.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from tests.parity.harness import REPO_ROOT

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def dump_schema(db_file: Path) -> Dict[str, Any]:
    """Everything that describes the schema, in a stable order."""
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


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="hammertime-schema-"))
    try:
        shutil.copyfile(REPO_ROOT / "package.json", workdir / "package.json")
        (workdir / "db_migrations").symlink_to(REPO_ROOT / "db_migrations")
        result = subprocess.run(
            ["node", str(REPO_ROOT / "db_migrate.js")],
            cwd=workdir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(result.stdout, result.stderr, file=sys.stderr)
            return 1

        schema = dump_schema(workdir / "data" / "schedule.db")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / "schema.json"
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(Path.cwd())} ({len(schema['objects'])} objects)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
