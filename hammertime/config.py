"""Runtime configuration.

Mirrors ``index.js`` + ``dotenv.config()``: all paths are resolved relative to the
process working directory (``./data``, ``./public``, ``./db_migrations``), so the
server must be started from the repository root — same requirement as Node.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Node resolves these against process.cwd() at import/call time.
APP_ROOT = Path.cwd()
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "schedule.db"
PUBLIC_DIR = APP_ROOT / "public"
MIGRATIONS_DIR = APP_ROOT / "db_migrations"


def load_env() -> None:
    """Load ``.env`` like ``dotenv.config()``: real environment variables win."""
    load_dotenv(APP_ROOT / ".env", override=False)


def debug_enabled() -> bool:
    """Mirror ``if (process.env.DEBUG)`` — any non-empty string is truthy, incl. "0"."""
    return bool(os.environ.get("DEBUG"))


# Applied on import so every module that reads os.environ (auth.JWT_SECRET, db paths)
# sees the .env values regardless of import order.
load_env()
