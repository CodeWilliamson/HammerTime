"""Unit tests for the ported pure logic.

The HTTP-level behaviour is covered by the parity/golden suites; these tests pin the
small helpers those depend on (formatting, semver gating, SQL splitting, time math).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from hammertime import clock
from hammertime.db import format_date, parse_time_to_minutes, time_ranges_overlap
from hammertime.migrate import compare_semver, split_statements
from hammertime.timer_state import js_isoformat
from hammertime.web import js_date_to_epoch


def test_js_isoformat_matches_to_iso_string():
    # A naive local datetime is what `new Date()` + `setHours()` produces in Node.
    moment = datetime(2026, 10, 21, 18, 30, 0, 123000)
    formatted = js_isoformat(moment)

    assert len(formatted) == len("2026-10-21T18:30:00.000Z")
    assert formatted.endswith("Z")
    assert datetime.fromisoformat(formatted.replace("Z", "+00:00")) == moment.astimezone(
        timezone.utc
    )


def test_js_isoformat_zero_pads_milliseconds():
    moment = datetime(2026, 10, 21, 9, 5, 1, 4000)
    assert js_isoformat(moment).endswith(":01.004Z")


def test_weekday_name_matches_javascript_get_day_order():
    # 2026-10-21 is a Wednesday.
    assert clock.weekday_name(datetime(2026, 10, 21)) == "Wednesday"
    assert clock.weekday_name(datetime(2026, 10, 18)) == "Sunday"
    assert clock.weekday_name(datetime(2026, 10, 24)) == "Saturday"


def test_format_date_zero_pads():
    assert format_date(datetime(2026, 1, 2)) == "2026-01-02"


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("0.0.0", "1.0.0", -1),
        ("1.5.0", "1.5.0", 0),
        ("1.10.0", "1.9.0", 1),
        ("1.0.1", "1.1.0", -1),
        ("2.0.0", "1.99.99", 1),
        ("1.0.0", "0.9.9", 1),
        ("1.0.0-beta", "1.0.0", -1),
        ("1.0.0", "1.0.0-beta", 1),
    ],
)
def test_compare_semver(left, right, expected):
    assert compare_semver(left, right) == expected


def test_split_statements_keeps_comments_and_multi_line_statements():
    sql = """-- a comment
CREATE TABLE a (
    id INTEGER -- trailing comment
);
ALTER TABLE a ADD COLUMN b TEXT;

INSERT INTO a (id, b) VALUES (1, 'x');
"""
    statements = list(split_statements(sql))
    assert len(statements) == 3
    assert statements[0].startswith("-- a comment")
    assert statements[1].startswith("ALTER TABLE")
    assert statements[2].startswith("INSERT INTO")

    # And they are valid SQL.
    connection = sqlite3.connect(":memory:")
    try:
        for statement in statements:
            connection.execute(statement)
        assert connection.execute("SELECT b FROM a").fetchone() == ("x",)
    finally:
        connection.close()


def test_split_statements_without_trailing_semicolon():
    assert list(split_statements("SELECT 1")) == ["SELECT 1"]


def test_js_date_to_epoch_handles_both_client_formats():
    naive = js_date_to_epoch("2026-10-19 01:19:13")
    iso = js_date_to_epoch("2026-10-19T01:19:13.000Z")

    # A naive string is interpreted as local time (like V8), while the ISO form with a
    # trailing Z is UTC. Both end up as the same *instant* only when local time is UTC.
    assert naive == datetime(2026, 10, 19, 1, 19, 13).timestamp()
    assert iso == datetime(2026, 10, 19, 1, 19, 13, tzinfo=timezone.utc).timestamp()
    assert naive - iso == datetime(2026, 10, 19, 1, 19, 13).astimezone().utcoffset().total_seconds() * -1


def test_js_date_to_epoch_returns_nan_for_invalid_input():
    value = js_date_to_epoch("not-a-date")
    assert value != value  # NaN


def test_js_date_to_epoch_treats_numbers_as_milliseconds():
    assert js_date_to_epoch(0) == 0.0
    assert js_date_to_epoch(1500) == 1.5


def test_parse_time_to_minutes():
    assert parse_time_to_minutes("19:00") == 1140
    assert parse_time_to_minutes("00:00") == 0
    assert parse_time_to_minutes("23:59") == 1439


@pytest.mark.parametrize(
    "start_a,dur_a,start_b,dur_b,expected",
    [
        ("18:30", 110, "19:00", 60, True),
        ("18:30", 110, "21:00", 60, False),  # touching edges do not overlap
        ("09:00", 60, "09:30", 10, True),
        ("09:00", 60, "10:00", 10, False),
        ("09:00", 120, "09:30", 10, True),  # containment
    ],
)
def test_time_ranges_overlap(start_a, dur_a, start_b, dur_b, expected):
    assert time_ranges_overlap(start_a, dur_a, start_b, dur_b) is expected
