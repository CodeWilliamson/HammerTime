"""SQLite data access — direct port of ``db.js``.

Behaviour notes that are deliberately preserved from the Node version:

* The connection runs in autocommit mode (``isolation_level=None``) because
  better-sqlite3 commits every statement immediately.
* ``PRAGMA foreign_keys = ON`` because better-sqlite3 enables it by default.
* Date strings are built from *local* wall-clock time.
* ``get_current_draw`` orders override rows by rowid (no ORDER BY) and puts them
  before the weekly draws; that ordering decides which draw counts as "next".
* ``get_all_draws`` suppresses a weekly draw when an override on that date has the
  *same start_time* — a different rule from the overlap filter used above. Both are
  original behaviour and are covered by the parity suite.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

import bcrypt

from hammertime import clock
from hammertime.config import DB_PATH


class DrawOverlapError(Exception):
    """Raised when a weekly draw overlaps another one on the same weekday."""


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(str(DB_PATH), isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Opened at import time, exactly like `new Database("./data/schedule.db")`, so a missing
# database fails fast at startup instead of on the first request.
_conn = _connect()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    return [dict(row) for row in _conn.execute(sql, tuple(params))]


def _row(sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
    row = _conn.execute(sql, tuple(params)).fetchone()
    return dict(row) if row is not None else None


def format_date(moment: datetime) -> str:
    """``YYYY-MM-DD`` in local time (JS ``getFullYear``/``getMonth``/``getDate``)."""
    return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"


def parse_time_to_minutes(time_str: Any) -> int:
    """``HH:MM`` -> minutes since midnight (JS ``split(":").map(Number)``)."""
    parts = str(time_str).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def time_ranges_overlap(start_a: Any, duration_a: Any, start_b: Any, duration_b: Any) -> bool:
    """True when two HH:MM + duration ranges overlap. Touching edges do not overlap."""
    a_start = parse_time_to_minutes(start_a)
    a_end = a_start + float(duration_a)
    b_start = parse_time_to_minutes(start_b)
    b_end = b_start + float(duration_b)
    return a_start < b_end and a_end > b_start


def js_number_to_int(value: Any) -> Optional[int]:
    """Best-effort ``Number(value)`` for id comparisons; ``None`` behaves like NaN."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Current draw
# ---------------------------------------------------------------------------

def get_current_draw() -> Dict[str, Any]:
    """The most recently ended and the next/current draw for *today* (local time)."""
    now = clock.now()
    iso_date = format_date(now)

    overrides = _rows("SELECT * FROM draw_overrides WHERE date = ?", (iso_date,))
    day = clock.weekday_name(now)
    weekly_draws = _rows(
        "SELECT * FROM draws WHERE day_of_week = ? ORDER BY start_time ASC", (day,)
    )

    if overrides:
        # Exclude weekly draws that overlap with any override.
        non_overlapping = [
            weekly
            for weekly in weekly_draws
            if not any(
                time_ranges_overlap(
                    weekly["start_time"], weekly["duration_minutes"],
                    override["start_time"], override["duration_minutes"],
                )
                for override in overrides
            )
        ]
        draws = [*overrides, *non_overlapping]
    else:
        draws = weekly_draws

    last_ended_draw = None
    next_draw = None

    for draw in draws:
        hour, minute = (int(part) for part in str(draw["start_time"]).split(":")[:2])
        draw_start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        draw_end = draw_start + timedelta(minutes=float(draw["duration_minutes"]))

        if now >= draw_end:
            # Save the most recently completed draw.
            if last_ended_draw is None or draw_end > last_ended_draw["drawEnd"]:
                last_ended_draw = {**draw, "drawStart": draw_start, "drawEnd": draw_end}
        else:
            # First upcoming or currently running draw.
            next_draw = {**draw, "drawStart": draw_start, "drawEnd": draw_end}
            break

    return {"lastEndedDraw": last_ended_draw, "nextDraw": next_draw}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_weekly_draw(draw: Dict[str, Any], exclude_id: Any = None) -> None:
    """Reject overlap with another weekly draw on the same day.

    Overrides are intentionally not checked here — they may overlap weekly draws
    because they take precedence on their date.
    """
    others = _rows(
        "SELECT * FROM draws WHERE day_of_week = ? ORDER BY start_time ASC",
        (draw["day_of_week"],),
    )
    excluded = js_number_to_int(exclude_id) if exclude_id is not None else None

    for other in others:
        if exclude_id is not None and other["id"] == excluded:
            continue
        if time_ranges_overlap(
            draw["start_time"], draw["duration_minutes"],
            other["start_time"], other["duration_minutes"],
        ):
            raise DrawOverlapError(
                f'This draw overlaps with "{other["title"]}" on {draw["day_of_week"]} '
                f'at {other["start_time"]} ({other["duration_minutes"]} min). '
                f"Choose a different time or day."
            )


# ---------------------------------------------------------------------------
# Timer config
# ---------------------------------------------------------------------------

CONFIG_FIELDS = (
    "background_color", "background_color_running", "background_color_warning",
    "background_color_critical",
    "timer_color", "timer_color_running", "timer_color_warning", "timer_color_critical",
    "status_color", "status_color_running", "status_color_warning", "status_color_critical",
    "message_color_running", "message_color_warning", "message_color_critical",
    "timer_font_size", "label_font_size", "message_font_size",
    "pre_draw_warning_threshold", "running_warning_threshold",
    "show_admin_url", "dynamic_timer_format",
)


def get_full_config() -> Optional[Dict[str, Any]]:
    return _row("SELECT * FROM timer_config ORDER BY updated_at DESC LIMIT 1")


# getConfig() in db.js is byte-identical to getFullConfig().
get_config = get_full_config


def update_config(updates: Dict[str, Any]) -> bool:
    """Update the known timer_config fields. Returns False when nothing to update."""
    set_clauses: List[str] = []
    values: List[Any] = []
    for key in CONFIG_FIELDS:
        if key in updates:
            set_clauses.append(f"{key} = ?")
            values.append(updates[key])

    if not set_clauses:
        return False

    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    sql = (
        f"UPDATE timer_config SET {', '.join(set_clauses)} "
        "WHERE id = (SELECT id FROM timer_config ORDER BY updated_at DESC LIMIT 1)"
    )
    cursor = _conn.execute(sql, values)
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Draws / overrides
# ---------------------------------------------------------------------------

def add_draw_override(draw: Dict[str, Any]) -> Dict[str, Any]:
    cursor = _conn.execute(
        """
        INSERT INTO draw_overrides (date, title, message, start_time, duration_minutes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            draw.get("override_date"),
            draw.get("title"),
            draw.get("message"),
            draw.get("start_time"),
            draw.get("duration_minutes"),
        ),
    )
    return {"id": cursor.lastrowid, "override": True}


def add_draw(draw: Dict[str, Any]) -> Dict[str, Any]:
    # Prevent weekly draws from overlapping other weekly draws.
    validate_weekly_draw(draw)

    cursor = _conn.execute(
        """
        INSERT INTO draws (day_of_week, title, message, start_time, duration_minutes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            draw.get("day_of_week"),
            draw.get("title"),
            draw.get("message"),
            draw.get("start_time"),
            draw.get("duration_minutes"),
        ),
    )
    return {"id": cursor.lastrowid, "override": False}


def update_draw(draw_id: Any, updates: Dict[str, Any]) -> bool:
    # Prevent weekly draws from overlapping other weekly draws (exclude self).
    validate_weekly_draw(updates, draw_id)

    cursor = _conn.execute(
        """
        UPDATE draws
        SET day_of_week = ?, title = ?, message = ?, start_time = ?, duration_minutes = ?
        WHERE id = ?
        """,
        (
            updates.get("day_of_week"),
            updates.get("title"),
            updates.get("message"),
            updates.get("start_time"),
            updates.get("duration_minutes"),
            draw_id,
        ),
    )
    return cursor.rowcount > 0


def delete_draw(draw_id: Any, is_override: bool = False) -> bool:
    if is_override:
        cursor = _conn.execute("DELETE FROM draw_overrides WHERE id = ?", (draw_id,))
    else:
        cursor = _conn.execute("DELETE FROM draws WHERE id = ?", (draw_id,))
    return cursor.rowcount > 0


def delete_draw_override(draw_id: Any) -> bool:
    cursor = _conn.execute("DELETE FROM draw_overrides WHERE id = ?", (draw_id,))
    return cursor.rowcount > 0


def update_draw_override(draw_id: Any, updates: Dict[str, Any]) -> bool:
    cursor = _conn.execute(
        """
        UPDATE draw_overrides
        SET date = ?, title = ?, message = ?, start_time = ?, duration_minutes = ?
        WHERE id = ?
        """,
        (
            # Allow either field name, like the original.
            updates.get("override_date") or updates.get("date"),
            updates.get("title"),
            updates.get("message"),
            updates.get("start_time"),
            updates.get("duration_minutes"),
            draw_id,
        ),
    )
    return cursor.rowcount > 0


def get_all_draws() -> Dict[str, Any]:
    """Week view (Sunday-based) plus future overrides, grouped for the admin calendar."""
    today = clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = format_date(today)

    all_overrides = _rows(
        "SELECT * FROM draw_overrides WHERE date >= ? ORDER BY date ASC, start_time ASC",
        (today_str,),
    )
    overrides_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for override in all_overrides:
        overrides_by_date.setdefault(override["date"], []).append(
            {**override, "is_override": True}
        )

    all_draws = _rows("SELECT * FROM draws ORDER BY day_of_week ASC, start_time ASC")

    # Week starts on Sunday, like `today.getDate() - today.getDay()`.
    week_start = today - timedelta(days=today.isoweekday() % 7)
    week_end = week_start + timedelta(days=6)

    draws_for_week: List[Dict[str, Any]] = []
    for offset in range(7):
        date = week_start + timedelta(days=offset)
        date_str = format_date(date)
        day_of_week_str = clock.weekday_name(date)

        weekly_draws = [
            {**draw, "day_of_week": day_of_week_str, "date": date_str}
            for draw in all_draws
            if draw["day_of_week"] == day_of_week_str
        ]

        overrides = [
            {**override, "date": override["date"], "is_override": True}
            for override in overrides_by_date.get(date_str, [])
        ]

        override_times = {override["start_time"] for override in overrides}

        # Overrides first — they take precedence.
        draws_for_week.extend(overrides)
        draws_for_week.extend(
            weekly for weekly in weekly_draws if weekly["start_time"] not in override_times
        )

    future_overrides = [
        {**override, "is_override": True}
        for override in all_overrides
        if datetime.fromisoformat(override["date"] + "T00:00:00") > week_end
    ]

    return {"drawsForWeek": draws_for_week, "futureOverrides": future_overrides}


def get_draw_by_id(draw_id: Any) -> Optional[Dict[str, Any]]:
    return _row("SELECT * FROM draws WHERE id = ?", (draw_id,))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user_by_username(username: Any) -> Optional[Dict[str, Any]]:
    return _row("SELECT * FROM users WHERE username = ?", (str(username).lower(),))


def update_password(username: Any, new_password: Any) -> bool:
    hashed = bcrypt.hashpw(
        str(new_password).encode("utf-8"), bcrypt.gensalt(rounds=10)
    ).decode("ascii")
    cursor = _conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (hashed, str(username).lower()),
    )
    return cursor.rowcount > 0
