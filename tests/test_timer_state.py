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
