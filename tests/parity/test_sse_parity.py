"""SSE parity: identical framing, identical snapshot payloads, identical timers."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from tests.parity import harness

pytestmark = pytest.mark.skipif(
    not harness.node_available(), reason="original Node server is not available"
)


def _login_and_update_config(server: harness.Server, colour: str) -> None:
    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        response = client.post(
            "/auth/login", json={"username": "timer", "password": "timer"}
        )
        assert response.status_code == 200, response.text
        response = client.put("/api/timer/config", json={"background_color": colour})
        assert response.status_code == 204, response.text


def _handshake(server: harness.Server):
    """Collect hello, then the config + timer_state frames caused by a config save."""
    with httpx.stream(
        "GET", f"{server.base_url}/events", timeout=httpx.Timeout(30, read=20)
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"

        lines = response.iter_lines()
        hello = harness.read_frame(lines)
        _login_and_update_config(server, "#abcdef")
        config = harness.read_frame(lines)
        state = harness.read_frame(lines)
        return [hello, config, state]


def test_sse_parity(servers):
    node, python = servers("2026-10-21T10:00:00")

    node_frames = _handshake(node)
    python_frames = _handshake(python)

    assert [frame["event"] for frame in node_frames] == ["hello", "config", "timer_state"]
    assert [frame["event"] for frame in python_frames] == ["hello", "config", "timer_state"]

    for expected, actual in zip(node_frames, python_frames):
        assert json.loads(expected["data"]) == json.loads(actual["data"]), (
            f"{expected['event']} payload differs\n"
            f"node:   {expected['data']}\n"
            f"python: {actual['data']}"
        )

    # Framing must match byte for byte (key order included).
    for expected, actual in zip(node_frames, python_frames):
        assert expected["data"] == actual["data"], (
            f"{expected['event']} serialisation differs\n"
            f"node:   {expected['data']}\n"
            f"python: {actual['data']}"
        )


@pytest.mark.slow
def test_sse_background_timers(servers):
    """The 20 s heartbeat and 60 s state tick must both fire without any writes."""
    node, python = servers("2026-10-21T10:00:00")

    def collect(server: harness.Server, seconds: float):
        comments = 0
        events = []
        deadline = time.time() + seconds
        with httpx.stream(
            "GET", f"{server.base_url}/events", timeout=httpx.Timeout(90, read=40)
        ) as response:
            for line in response.iter_lines():
                if time.time() > deadline:
                    break
                line = line.rstrip("\n")
                if line.startswith(":") and "keep-alive" in line:
                    comments += 1
                elif line.startswith("event:"):
                    events.append(line[len("event:"):].strip())
        return comments, events

    node_comments, node_events = collect(node, 62)
    python_comments, python_events = collect(python, 62)

    assert python_comments >= 2, "expected keep-alive comments every 20s"
    assert "timer_state" in python_events, "expected the 60s state re-broadcast"
    assert python_comments == node_comments
    assert python_events == node_events
