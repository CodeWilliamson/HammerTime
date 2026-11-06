"""Tests for the timer display state machine (``hammertime/timer_state.py``).

The kiosk depends on the exact payload shape per status, so both the status and the
key set are asserted. Times are frozen with ``HAMMERTIME_FAKE_NOW``.
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from hammertime import timer_state
from tests import support

pytestmark = pytest.mark.usefixtures("db")

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _local(iso_utc: str) -> datetime:
    """Parse a ``toISOString()``-style value back to local wall-clock time."""
    assert ISO.match(iso_utc), iso_utc
    return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


@pytest.mark.parametrize(
    ("instant", "status"),
    [
        (support.WAITING, "waiting"),
        (support.PRE_DRAW, "pre_draw"),
        (support.PRE_DRAW_BOUNDARY, "pre_draw"),
        (support.RUNNING, "running"),
        (support.WARNING, "running"),
        (support.COMPLETE, "complete"),
        (support.COMPLETE_BOUNDARY, "complete"),
        (support.LATE_RUNNING, "running"),
        (support.IDLE, "idle"),
    ],
)
def test_status_for_each_instant(freeze, instant, status):
    freeze(instant)
    assert timer_state.get_timer_state()["status"] == status


@pytest.mark.parametrize(
    "instant",
    ["2026-10-21T18:19:59", "2026-10-21T20:10:01", support.WAITING],
)
def test_status_outside_the_windows_is_waiting(freeze, instant):
    freeze(instant)
    assert timer_state.get_timer_state()["status"] == "waiting"


def test_pre_draw_starts_exactly_ten_minutes_before_the_draw(freeze):
    freeze("2026-10-21T18:19:59")
    assert timer_state.get_timer_state()["status"] == "waiting"

    freeze(support.PRE_DRAW_BOUNDARY)
    state = timer_state.get_timer_state()
    assert state["status"] == "pre_draw"
    assert _local(state["targetTime"]) == datetime(2026, 10, 21, 18, 30)


def test_complete_lasts_exactly_ten_minutes_after_the_draw(freeze):
    freeze(support.COMPLETE_BOUNDARY)
    assert timer_state.get_timer_state()["status"] == "complete"

    freeze("2026-10-21T20:10:01")
    assert timer_state.get_timer_state()["status"] == "waiting"


def test_running_payload(freeze):
    freeze(support.RUNNING)
    state = timer_state.get_timer_state()

    assert set(state) == {"status", "drawLabel", "drawMessage", "targetTime", "adminUrl"}
    assert state["status"] == "running"
    assert state["drawLabel"] == "Bonspiel Draw 1"
    assert state["drawMessage"] == "Sheet 1-4"
    # `running` counts down to the end of the draw and deliberately has no endTime.
    assert _local(state["targetTime"]) == datetime(2026, 10, 21, 20, 0)
    assert state["adminUrl"] is None or state["adminUrl"].endswith("/admin")


def test_pre_draw_payload(freeze):
    freeze(support.PRE_DRAW)
    state = timer_state.get_timer_state()

    assert set(state) == {
        "status",
        "drawLabel",
        "drawMessage",
        "targetTime",
        "endTime",
        "adminUrl",
    }
    assert state["drawLabel"] == "Bonspiel Draw 1"
    # `pre_draw` counts down to the start but also carries the end, so the client can
    # switch to the running countdown without waiting for the next server push.
    assert _local(state["targetTime"]) == datetime(2026, 10, 21, 18, 30)
    assert _local(state["endTime"]) == datetime(2026, 10, 21, 20, 0)


def test_waiting_payload(freeze):
    freeze(support.WAITING)
    state = timer_state.get_timer_state()

    assert set(state) == {
        "status",
        "nextDrawStart",
        "targetTime",
        "nextDrawTitle",
        "nextDrawMessage",
        "adminUrl",
    }
    assert state["nextDrawTitle"] == "Bonspiel Draw 1"
    assert state["nextDrawMessage"] == "Sheet 1-4"
    assert _local(state["nextDrawStart"]) == datetime(2026, 10, 21, 18, 30)
    assert state["nextDrawStart"] == state["targetTime"]


def test_complete_payload(freeze):
    freeze(support.COMPLETE)
    state = timer_state.get_timer_state()

    assert set(state) == {"status", "drawLabel", "drawMessage", "targetTime", "adminUrl"}
    assert state["drawLabel"] == "Bonspiel Draw 1"
    assert state["drawMessage"] == "Sheet 1-4"
    assert _local(state["targetTime"]) == datetime(2026, 10, 21, 20, 0)


def test_idle_payload(freeze):
    freeze(support.IDLE)
    state = timer_state.get_timer_state()

    assert set(state) == {"status", "drawLabel", "drawMessage", "targetTime", "adminUrl"}
    assert state["drawLabel"] == "No draw scheduled"
    assert state["drawMessage"] is None
    assert state["targetTime"] is None


def test_js_isoformat_matches_javascript():
    # Naive datetimes are local time; the output is UTC with millisecond precision.
    moment = datetime(2026, 10, 21, 20, 0, 5, 12000)
    text = timer_state.js_isoformat(moment)

    assert text.endswith(".012Z")
    assert _local(text) == moment


# ---------------------------------------------------------------------------
# End counter ("END n" replaces the status label while a draw is running)
# ---------------------------------------------------------------------------

def test_end_counter_payload_starts_at_end_two(end_counter, freeze):
    freeze(support.END_TWO)
    state = timer_state.get_timer_state()

    assert state["status"] == "running"
    assert state["endNumber"] == 2
    assert state["endMinutes"] == 14
    assert _local(state["drawStart"]) == datetime(2026, 10, 21, 18, 30)
    # The end fields are additive: the running key set is otherwise unchanged.
    assert set(state) == {
        "status",
        "drawLabel",
        "drawMessage",
        "targetTime",
        "drawStart",
        "endMinutes",
        "endNumber",
        "adminUrl",
    }


def test_end_number_is_absent_one_second_before_end_two(end_counter, freeze):
    # END 1 is never shown, so there is no number yet — but the primitives are already
    # there, which is what lets the kiosk flip the badge itself on the next second.
    freeze("2026-10-21T18:43:59")
    state = timer_state.get_timer_state()

    assert "endNumber" not in state
    assert "drawStart" in state
    assert state["endMinutes"] == 14


def test_end_number_advances_with_the_draw(end_counter, freeze):
    freeze(support.END_MID)
    assert timer_state.get_timer_state()["endNumber"] == 4


def test_end_number_stops_at_the_last_end(end_counter, freeze):
    # 4-minute ends: END 10 starts 36 minutes in, END 11 would start at 40. The 18:30
    # draw on this date is the override ("Bonspiel Draw 1"); the weekly draw is excluded.
    end_counter._conn.execute(
        "UPDATE draw_overrides SET end_minutes = 4 WHERE title = 'Bonspiel Draw 1'"
    )

    freeze("2026-10-21T19:06:00")
    assert timer_state.get_timer_state()["endNumber"] == 10

    freeze("2026-10-21T19:10:00")
    assert "endNumber" not in timer_state.get_timer_state()


def test_end_number_is_absent_when_the_draw_has_no_time_per_end(db, end_counter, freeze):
    db._conn.execute(
        "UPDATE draw_overrides SET end_minutes = NULL WHERE title = 'Bonspiel Draw 1'"
    )
    freeze(support.END_MID)
    state = timer_state.get_timer_state()

    assert state["status"] == "running"
    assert "endNumber" not in state
    assert "drawStart" not in state


def test_end_number_is_absent_when_the_feature_is_disabled(db, end_counter, freeze):
    db._conn.execute("UPDATE timer_config SET show_end_number = 0")
    freeze(support.END_MID)
    state = timer_state.get_timer_state()

    assert state["status"] == "running"
    # Disabled means the payload is exactly what it was before the feature existed.
    assert set(state) == {"status", "drawLabel", "drawMessage", "targetTime", "adminUrl"}


def test_end_number_is_not_sent_before_the_draw_starts(end_counter, freeze):
    freeze(support.PRE_DRAW)
    state = timer_state.get_timer_state()

    assert state["status"] == "pre_draw"
    assert "endNumber" not in state
    assert "drawStart" not in state


# ---------------------------------------------------------------------------
# System-wide time per end (one value for every draw)
# ---------------------------------------------------------------------------

def test_system_end_minutes_override_every_draw_value(end_counter, freeze):
    # The draw still stores 14 minutes; the system value must win at read time.
    end_counter._conn.execute(
        "UPDATE timer_config SET use_system_end_minutes = 1, system_end_minutes = 9"
    )
    freeze(support.END_MID)
    state = timer_state.get_timer_state()

    assert state["status"] == "running"
    assert state["endMinutes"] == 9
    # 45 minutes in with 9-minute ends is END 6 (14-minute ends would be END 4).
    assert state["endNumber"] == 6


def test_system_end_minutes_applies_to_draws_with_no_stored_value(system_end_counter, freeze):
    freeze(support.END_TWO)
    state = timer_state.get_timer_state()

    assert state["endMinutes"] == 9
    assert state["endNumber"] == 2
    assert _local(state["drawStart"]) == datetime(2026, 10, 21, 18, 30)


def test_system_end_minutes_falls_back_to_the_draw_value_when_disabled(end_counter, freeze):
    end_counter._conn.execute(
        "UPDATE timer_config SET use_system_end_minutes = 0, system_end_minutes = 9"
    )
    freeze(support.END_MID)
    state = timer_state.get_timer_state()

    # Switching the override off restores the per-draw value that was never touched.
    assert state["endMinutes"] == 14
    assert state["endNumber"] == 4


def test_system_end_minutes_falls_back_when_the_shared_value_is_missing(end_counter, freeze):
    end_counter._conn.execute(
        "UPDATE timer_config SET use_system_end_minutes = 1, system_end_minutes = NULL"
    )
    freeze(support.END_MID)
    state = timer_state.get_timer_state()

    assert state["endMinutes"] == 14
    assert state["endNumber"] == 4


def test_system_end_minutes_is_ignored_when_the_counter_is_off(system_end_counter, freeze):
    system_end_counter._conn.execute("UPDATE timer_config SET show_end_number = 0")
    freeze(support.END_MID)
    state = timer_state.get_timer_state()

    assert state["status"] == "running"
    assert set(state) == {"status", "drawLabel", "drawMessage", "targetTime", "adminUrl"}
