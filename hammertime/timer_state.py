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


#: Curling plays a fixed number of ends, so the counter stops there even on a draw long
#: enough to imply more. Keep in sync with ``MAX_ENDS`` in ``public/app.js``.
MAX_ENDS = 10


def end_number_at(now: datetime, draw_start: datetime, end_minutes: Any) -> Optional[int]:
    """Which end is being played at ``now`` (1-based), or ``None`` when unavailable.

    ``None`` means "nothing to display": the first end is never shown (END 2 is the
    first useful number), and the counter stops at :data:`MAX_ENDS`.
    """
    end_seconds = _end_seconds(end_minutes)
    if end_seconds is None:
        return None

    number = int((now - draw_start).total_seconds() // end_seconds) + 1
    if number < 2 or number > MAX_ENDS:
        return None
    return number


def _end_seconds(end_minutes: Any) -> Optional[float]:
    if not end_minutes:
        return None
    try:
        seconds = float(end_minutes) * 60
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def effective_end_minutes(config: Optional[Dict[str, Any]], draw: Dict[str, Any]) -> Any:
    """The end length to display for ``draw``.

    A system-wide override (Display Settings → End counter) replaces every draw's stored
    ``end_minutes`` at read time; the per-draw values stay in the database and come back
    when the override is switched off. A missing/invalid override value falls back to the
    draw's own value rather than disabling the badge unexpectedly.
    """
    if config and config.get("use_system_end_minutes"):
        system_minutes = config.get("system_end_minutes")
        if _end_seconds(system_minutes) is not None:
            return system_minutes
    return draw.get("end_minutes")


def _end_counter_fields(
    config: Optional[Dict[str, Any]],
    draw: Dict[str, Any],
    now: datetime,
    draw_start: datetime,
) -> Dict[str, Any]:
    """END n payload fields for a running draw, or ``{}`` when the counter is off.

    Only the schedule primitives are sent (:class:`MAX_ENDS`, the warning threshold and
    the once-a-second refresh are the client's job), so the kiosk's ``tick()`` can hide
    the badge at the warning threshold without waiting for the next server push.
    """
    if not config or not config.get("show_end_number"):
        return {}

    end_minutes = effective_end_minutes(config, draw)
    if _end_seconds(end_minutes) is None:
        return {}

    # The primitives are sent for the whole running phase — even before END 2 — so the
    # kiosk can flip the badge on the exact second instead of waiting for a push.
    fields: Dict[str, Any] = {
        "drawStart": js_isoformat(draw_start),
        "endMinutes": int(end_minutes),
    }

    number = end_number_at(now, draw_start, end_minutes)
    if number is not None:
        fields["endNumber"] = number
    return fields


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
            payload = {
                "status": "running",
                "drawLabel": next_draw["title"],
                "drawMessage": _message(next_draw),
                "targetTime": js_isoformat(draw_end),
                **state,
            }
            payload.update(_end_counter_fields(config, next_draw, now, draw_start))
            return payload

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
