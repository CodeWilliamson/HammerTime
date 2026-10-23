"""Server-Sent Events tests (``GET /events``).

The kiosk display lives off this stream: a full ``hello`` snapshot on connect, then
snapshot events whenever timer state or config changes.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from tests import support


def test_hello_frame_is_a_full_snapshot(server):
    with httpx.Client(base_url=server.base_url, timeout=15) as http_client:
        with http_client.stream("GET", "/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
            assert response.headers["cache-control"] == "no-cache, no-transform"
            assert response.headers["x-accel-buffering"] == "no"

            frame = support.read_frame(response.iter_lines())

    assert frame["event"] == "hello"
    payload = json.loads(frame["data"])
    assert set(payload) == {"timer_state", "config", "adminUrl"}
    assert payload["timer_state"]["status"] == "waiting"
    assert payload["config"]["updated_at"] == support.PINNED_UPDATED_AT
    assert payload["adminUrl"] == payload["timer_state"]["adminUrl"]


def test_config_update_is_broadcast_then_timer_state(server, auth_client):
    with httpx.Client(base_url=server.base_url, timeout=15) as stream_client:
        with stream_client.stream("GET", "/events") as response:
            lines = response.iter_lines()
            assert support.read_frame(lines)["event"] == "hello"

            updated = auth_client.put("/api/timer/config", json={"background_color": "#123456"})
            assert updated.status_code == 204

            config_frame = support.read_frame(lines)
            assert config_frame["event"] == "config"
            config = json.loads(config_frame["data"])
            assert config["type"] == "config"
            assert config["background_color"] == "#123456"
            # The kiosk turns every *_color key into a CSS variable, idle message included.
            assert config["message_color"] == "#eeeeee"

            state_frame = support.read_frame(lines)
            assert state_frame["event"] == "timer_state"
            assert json.loads(state_frame["data"])["status"] == "waiting"


def test_draw_mutation_pushes_a_new_timer_state(server, auth_client):
    with httpx.Client(base_url=server.base_url, timeout=15) as stream_client:
        with stream_client.stream("GET", "/events") as response:
            lines = response.iter_lines()
            assert support.read_frame(lines)["event"] == "hello"

            created = auth_client.post(
                "/api/draws",
                json={
                    "day_of_week": "Saturday",
                    "title": "Broadcast Draw",
                    "message": None,
                    "start_time": "08:00",
                    "duration_minutes": 60,
                },
            )
            assert created.status_code == 201

            frame = support.read_frame(lines)
            assert frame["event"] == "timer_state"
            assert json.loads(frame["data"])["type"] == "timer_state"


@pytest.mark.slow
def test_heartbeat_and_periodic_state_broadcast(server):
    """The 20 s keep-alive and the 60 s state tick keep kiosks converging."""
    started = time.monotonic()
    comments = 0
    events = []

    with httpx.Client(base_url=server.base_url, timeout=httpx.Timeout(30.0)) as http_client:
        with http_client.stream("GET", "/events") as response:
            lines = response.iter_lines()
            assert support.read_frame(lines)["event"] == "hello"

            while time.monotonic() - started < 62:
                line = next(lines)
                if line.startswith(":"):
                    comments += 1
                elif line.startswith("event:"):
                    events.append(line)

    assert comments >= 2  # one at 20 s, another at 40 s (and one at 60 s)
    assert "event: timer_state" in events
