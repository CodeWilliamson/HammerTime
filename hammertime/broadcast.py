"""Server-Sent Events hub — direct port of ``broadcast.js``.

Each connected client gets an ``asyncio.Queue``; broadcasts are pure fan-out writes of
pre-serialized frames. Frames are snapshots, never diffs, and there is no replay: every
(re)connect receives a full ``hello`` payload.

Timers (60 s state re-broadcast, 20 s keep-alive comment) start lazily when the first
client connects and never stop — same as the Node implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Set

from fastapi import Request
from fastapi.responses import StreamingResponse

from hammertime.config import debug_enabled
from hammertime.db import get_full_config
from hammertime.timer_state import get_timer_state

logger = logging.getLogger("hammertime.broadcast")

HEARTBEAT_FRAME = ": keep-alive\n\n"

#: Connected client queues (one per subscribed page).
_clients: Set[asyncio.Queue] = set()
_timers_started = False


def _serialize(payload: Dict[str, Any]) -> str:
    # ensure_ascii=False + compact separators mirror JSON.stringify byte-for-byte.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _frame(event_type: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {_serialize(payload)}\n\n"


def broadcast(message: Dict[str, Any]) -> None:
    """Send one named event to every connected client."""
    frame = _frame(message["type"], message)
    if debug_enabled():
        logger.info("Broadcasting message to %d clients: %s", len(_clients), message)
    for queue in list(_clients):
        queue.put_nowait(frame)


def broadcast_timer_state() -> None:
    broadcast({"type": "timer_state", **get_timer_state()})


def broadcast_config() -> None:
    broadcast({"type": "config", **get_full_config()})


async def _repeat(interval: float, action) -> None:
    while True:
        await asyncio.sleep(interval)
        action()


def _start_timers() -> None:
    """Start the background timers that keep clients converging (once)."""
    global _timers_started
    if _timers_started:
        return
    _timers_started = True

    loop = asyncio.get_running_loop()
    # Time-driven state transitions are not tied to any REST write, so nothing else
    # would push them. Re-broadcasting periodically lets clients converge.
    loop.create_task(_repeat(60.0, broadcast_timer_state), name="hammertime-state-tick")
    # Comment heartbeat keeps long-lived streams alive through proxies.
    loop.create_task(_repeat(20.0, _heartbeat), name="hammertime-heartbeat")


def _heartbeat() -> None:
    for queue in list(_clients):
        queue.put_nowait(HEARTBEAT_FRAME)


async def _event_frames(queue: asyncio.Queue) -> AsyncIterator[str]:
    try:
        # Full snapshot on every (re)connect.
        state = get_timer_state()
        yield _frame(
            "hello",
            {
                "timer_state": state,
                "config": get_full_config(),
                "adminUrl": state["adminUrl"],
            },
        )
        while True:
            yield await queue.get()
    finally:
        _clients.discard(queue)
        if debug_enabled():
            logger.info("SSE client disconnected (%d total).", len(_clients))


async def handle_events(request: Request) -> StreamingResponse:
    """``GET /events`` — subscribe the response to the SSE stream."""
    queue: asyncio.Queue = asyncio.Queue()
    _clients.add(queue)
    if debug_enabled():
        logger.info("SSE client connected (%d total).", len(_clients))
    _start_timers()

    return StreamingResponse(
        _event_frames(queue),
        status_code=200,
        media_type="text/event-stream",  # Starlette appends "; charset=utf-8"
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Tell any reverse proxy in front of us never to buffer this stream.
            "X-Accel-Buffering": "no",
        },
    )
