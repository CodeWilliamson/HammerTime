"""Timer display state machine — direct port of ``timerState.js``.

The exact key sets per status matter to the kiosk client, so they are reproduced
literally: ``running`` has no ``endTime``, ``pre_draw`` does; ``waiting`` uses
``nextDraw*`` keys; ``adminUrl`` is merged last.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from hammertime import clock
from hammertime.db import get_current_draw, get_full_config
from hammertime.util import get_host_ip


def js_isoformat(moment: datetime) -> str:
    """Format like JS ``Date#toISOString()``: UTC, milliseconds, trailing ``Z``.

    Naive datetimes are interpreted as local time (which is what the Node server
    produces via ``new Date()`` + ``setHours()``).
    """
    utc = moment.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def _message(draw: Optional[Dict[str, Any]]) -> Optional[str]:
    return draw.get("message") if draw else None


def get_timer_state() -> Dict[str, Any]:
    """Compute the current display state (idle/waiting/pre_draw/running/complete)."""
    config = get_full_config()
    state: Dict[str, Any] = {}

    current_ip = get_host_ip()
    state["adminUrl"] = f"http://{current_ip}/admin" if current_ip else None

    now = clock.now()
    current = get_current_draw()
    last_ended_draw = current["lastEndedDraw"]
    next_draw = current["nextDraw"]

    # Case 1: draw is running or starting soon (within 10 minutes).
    if next_draw:
        draw_start = next_draw["drawStart"]
        draw_end = next_draw["drawEnd"]
        seconds_until_start = math.floor((draw_start - now).total_seconds())

        if now >= draw_start and now < draw_end:
            return {
                "status": "running",
                "drawLabel": next_draw["title"],
                "drawMessage": _message(next_draw),
                "targetTime": js_isoformat(draw_end),
                **state,
            }

        if 0 < seconds_until_start <= 600:
            return {
                "status": "pre_draw",
                "drawLabel": next_draw["title"],
                "drawMessage": _message(next_draw),
                "targetTime": js_isoformat(draw_start),
                "endTime": js_isoformat(draw_end),
                **state,
            }

    # Case 2: recently ended draw (< 10 minutes ago).
    if last_ended_draw:
        seconds_since_end = math.floor((now - last_ended_draw["drawEnd"]).total_seconds())
        if seconds_since_end <= 600:
            return {
                "status": "complete",
                "drawLabel": last_ended_draw["title"],
                "drawMessage": _message(last_ended_draw),
                "targetTime": js_isoformat(last_ended_draw["drawEnd"]),
                **state,
            }

    # Case 3: no draw now, show the next one if it exists.
    if next_draw:
        return {
            "status": "waiting",
            "nextDrawStart": js_isoformat(next_draw["drawStart"]),
            "targetTime": js_isoformat(next_draw["drawStart"]),
            "nextDrawTitle": next_draw["title"],
            "nextDrawMessage": _message(next_draw),
            **state,
        }

    # Case 4: no draws today.
    return {
        "status": "idle",
        "drawLabel": "No draw scheduled",
        "drawMessage": None,
        "targetTime": None,
        **state,
    }
