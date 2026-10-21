"""Unit tests for the data layer (``hammertime/db.py``).

Each test runs against a copy of the canonical sandbox database (see ``tests/support.py``)
with the clock pinned, so "today" is always Wednesday 2026-10-21.
"""

from __future__ import annotations

import bcrypt
import pytest

from tests import support

pytestmark = pytest.mark.usefixtures("db")


def _draw(**overrides):
    draw = {
        "day_of_week": "Saturday",
        "title": "Extra Draw",
        "message": None,
        "start_time": "08:00",
        "duration_minutes": 60,
    }
    draw.update(overrides)
    return draw


# ---------------------------------------------------------------------------
# get_current_draw
# ---------------------------------------------------------------------------

def test_current_draw_prefers_override_rows_in_rowid_order(db):
    # 10:00 on the bonspiel day. Overrides are not sorted by time, so the 18:30
    # override is "next" even though the 12:00 override comes first chronologically.
    current = db.get_current_draw()

    assert current["lastEndedDraw"] is None
    assert current["nextDraw"]["title"] == "Bonspiel Draw 1"
    assert current["nextDraw"]["start_time"] == "18:30"
    assert current["nextDraw"]["drawStart"] == db.clock.now().replace(
        hour=18, minute=30, second=0, microsecond=0
    )


def test_current_draw_excludes_weekly_draw_that_overlaps_an_override(db, freeze):
    # 19:30: the 18:30 override (90 min) is running, so the weekly Valley League
    # draw (18:30, 110 min) is excluded for the date and cannot be "next".
    freeze(support.RUNNING)
    current = db.get_current_draw()

    assert current["nextDraw"]["title"] == "Bonspiel Draw 1"
    assert current["nextDraw"]["duration_minutes"] == 90


def test_current_draw_keeps_non_overlapping_weekly_draws(db, freeze):
    # At 21:30 the only remaining draw is the weekly Late League (the overrides ended).
    freeze(support.LATE_RUNNING)
    current = db.get_current_draw()

    assert current["nextDraw"]["title"] == "Late League"
    assert current["lastEndedDraw"]["title"] == "Bonspiel Draw 1"


def test_current_draw_tracks_the_most_recently_ended_draw(db, freeze):
    # 20:05: the 18:30 override ended at 20:00; the 12:00 override ended earlier but is
    # evaluated after it in rowid order, so it must not win.
    freeze(support.COMPLETE)
    current = db.get_current_draw()

    assert current["lastEndedDraw"]["title"] == "Bonspiel Draw 1"
    assert current["nextDraw"]["title"] == "Late League"


def test_current_draw_on_a_day_without_a_schedule(db, freeze):
    freeze(support.IDLE)
    assert db.get_current_draw() == {"lastEndedDraw": None, "nextDraw": None}


# ---------------------------------------------------------------------------
# Weekly draw validation
# ---------------------------------------------------------------------------

def test_validate_weekly_draw_rejects_overlap(db):
    with pytest.raises(db.DrawOverlapError) as error:
        db.validate_weekly_draw(_draw(day_of_week="Wednesday", start_time="19:00"))

    message = str(error.value)
    assert "Valley League" in message
    assert "overlaps" in message


def test_validate_weekly_draw_allows_touching_edges(db):
    # Valley League runs 18:30-20:20, so a draw starting at 20:20 does not overlap it.
    db.validate_weekly_draw(
        _draw(day_of_week="Wednesday", start_time="20:20", duration_minutes=30)
    )


def test_validate_weekly_draw_ignores_the_draw_being_updated(db):
    valley = db._rows("SELECT * FROM draws WHERE title = 'Valley League'")[0]
    assert valley["start_time"] == "18:30"

    # Updating a draw does not collide with itself.
    db.validate_weekly_draw(_draw(day_of_week="Wednesday", start_time="18:30"), valley["id"])


def test_validate_weekly_draw_does_not_check_overrides(db):
    # Overrides may overlap weekly draws; they take precedence on their date.
    db.add_draw(_draw(day_of_week="Wednesday", start_time="18:00", duration_minutes=30))


# ---------------------------------------------------------------------------
# Draw + override CRUD
# ---------------------------------------------------------------------------

def test_weekly_draw_crud(db):
    created = db.add_draw(_draw())
    draw_id = created["id"]

    assert created == {"id": draw_id, "override": False}
    assert db.get_draw_by_id(draw_id)["title"] == "Extra Draw"
    assert db.get_draw_by_id(draw_id)["duration_minutes"] == 60

    assert db.update_draw(draw_id, _draw(title="Renamed", start_time="09:00")) is True
    assert db.get_draw_by_id(draw_id)["title"] == "Renamed"
    assert db.get_draw_by_id(draw_id)["start_time"] == "09:00"

    assert db.delete_draw(draw_id) is True
    assert db.get_draw_by_id(draw_id) is None
    assert db.delete_draw(draw_id) is False


def test_add_draw_rejects_an_overlapping_weekly_draw(db):
    with pytest.raises(db.DrawOverlapError):
        db.add_draw(_draw(day_of_week="Wednesday", start_time="19:00"))


def test_update_draw_rejects_an_overlap_with_another_draw(db):
    target = next(
        draw for draw in db.get_all_draws()["drawsForWeek"] if draw["title"] == "Late League"
    )
    with pytest.raises(db.DrawOverlapError):
        db.update_draw(target["id"], _draw(day_of_week="Wednesday", start_time="19:00"))


def test_override_crud(db):
    created = db.add_draw_override(
        _draw(override_date="2026-10-24", title="Saturday Bonspiel", start_time="10:00")
    )
    override_id = created["id"]

    assert created["override"] is True
    rows = db._rows("SELECT * FROM draw_overrides WHERE id = ?", (override_id,))
    assert rows[0]["title"] == "Saturday Bonspiel"
    assert rows[0]["date"] == "2026-10-24"

    # Both field names are accepted, like the original.
    assert db.update_draw_override(
        override_id,
        {
            "date": "2026-10-25",
            "title": "Moved",
            "message": None,
            "start_time": "10:00",
            "duration_minutes": 60,
        },
    ) is True
    assert db._rows("SELECT * FROM draw_overrides WHERE id = ?", (override_id,))[0]["date"] == (
        "2026-10-25"
    )

    assert db.delete_draw_override(override_id) is True
    assert db.delete_draw_override(override_id) is False


def test_delete_draw_can_target_overrides(db):
    created = db.add_draw_override(_draw(override_date="2026-10-24"))
    assert db.delete_draw(created["id"], is_override=True) is True
    assert db.delete_draw(created["id"], is_override=True) is False


# ---------------------------------------------------------------------------
# Week view (admin calendar)
# ---------------------------------------------------------------------------

def test_week_view_covers_the_sunday_started_week(db):
    week = db.get_all_draws()

    dates = {draw["date"] for draw in week["drawsForWeek"]}
    assert dates == {"2026-10-18", "2026-10-21", "2026-10-22"}
    assert "2026-10-14" not in dates  # past override
    assert "2026-11-07" not in dates  # future override


def test_week_view_suppresses_weekly_draw_with_the_same_start_time(db):
    # The 18:30 override and the 18:30 weekly draw would both land on 2026-10-21.
    wednesday = [draw for draw in db.get_all_draws()["drawsForWeek"] if draw["date"] == "2026-10-21"]
    titles = [draw["title"] for draw in wednesday]

    assert titles == ["Bonspiel Lunch", "Bonspiel Draw 1", "Late League"]
    assert wednesday[0]["is_override"] is True
    assert wednesday[1]["is_override"] is True
    assert "is_override" not in wednesday[2]


def test_week_view_shows_only_the_override_when_it_shares_a_start_time(db):
    thursday = [draw for draw in db.get_all_draws()["drawsForWeek"] if draw["date"] == "2026-10-22"]

    # The override overlaps the weekly draw and shares its start_time, so only the
    # override is shown.
    assert [draw["title"] for draw in thursday] == ["Bonspiel Final"]
    assert thursday[0]["is_override"] is True


def test_week_view_lists_future_overrides_separately(db):
    future = db.get_all_draws()["futureOverrides"]

    assert [override["title"] for override in future] == ["Future Bonspiel"]
    assert future[0]["date"] == "2026-11-07"
    assert future[0]["is_override"] is True


# ---------------------------------------------------------------------------
# Timer config
# ---------------------------------------------------------------------------

def test_update_config_writes_only_known_fields(db):
    assert db.update_config({"background_color": "#123456", "unknown": "ignored"}) is True

    config = db.get_full_config()
    assert config["background_color"] == "#123456"
    assert "unknown" not in config
    assert config["updated_at"] != support.PINNED_UPDATED_AT


def test_update_config_reports_when_nothing_was_updated(db):
    assert db.update_config({"unknown": "ignored"}) is False
    assert db.update_config({}) is False
    assert db.get_full_config()["updated_at"] == support.PINNED_UPDATED_AT


def test_config_is_returned_newest_first(db):
    db._conn.execute(
        "INSERT INTO timer_config (background_color, updated_at) "
        "VALUES ('#abcdef', '2099-01-01 00:00:00')"
    )
    assert db.get_full_config()["background_color"] == "#abcdef"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def test_get_user_by_username_is_case_insensitive(db):
    user = db.get_user_by_username("TIMER")

    assert user["username"] == "timer"
    assert bcrypt.checkpw(b"timer", user["password_hash"].encode("ascii"))


def test_get_user_by_username_returns_none_when_missing(db):
    assert db.get_user_by_username("nobody") is None


def test_update_password_rehashes_and_reports_missing_users(db):
    assert db.update_password("timer", "new-secret") is True

    stored = db.get_user_by_username("timer")["password_hash"]
    assert stored != "new-secret"
    assert bcrypt.checkpw(b"new-secret", stored.encode("ascii"))

    assert db.update_password("nobody", "new-secret") is False


# ---------------------------------------------------------------------------
# Pure helpers (kept next to their callers)
# ---------------------------------------------------------------------------

def test_date_and_time_helpers(db):
    import datetime as dt

    assert db.format_date(dt.datetime(2026, 1, 9, 23, 59)) == "2026-01-09"
    assert db.parse_time_to_minutes("19:05") == 1145
    assert db.js_number_to_int("12") == 12
    assert db.js_number_to_int("abc") is None

    assert db.time_ranges_overlap("18:30", 90, "19:00", 60) is True
    assert db.time_ranges_overlap("18:30", 30, "19:00", 60) is False
