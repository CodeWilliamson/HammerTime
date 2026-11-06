"""Timer routes — direct port of ``routes/timer.js``."""

from __future__ import annotations

import logging
logger = logging.getLogger("hammertime.timer")
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from hammertime.auth import require_auth
from hammertime.broadcast import broadcast_config, broadcast_timer_state
from hammertime.config import debug_enabled
from hammertime.db import get_current_draw, get_full_config, update_config
from hammertime.responses import JSONResponse
from hammertime.timer_state import get_timer_state
from hammertime.web import js_date_to_epoch, read_json

router = APIRouter()

#: Same range the admin draw form accepts for a per-draw "time per end".
MIN_END_MINUTES = 1
MAX_END_MINUTES = 120


def _flag_enabled(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false")
    return bool(value)


def _normalise_system_end_minutes(value: Any) -> Optional[int]:
    """Whole minutes in the supported range, ``None`` for blank, ``ValueError`` otherwise."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        raise ValueError("system_end_minutes must be a whole number between 1 and 120")
    if not minutes.is_integer() or not MIN_END_MINUTES <= minutes <= MAX_END_MINUTES:
        raise ValueError("system_end_minutes must be a whole number between 1 and 120")
    return int(minutes)



@router.get("/api/timer/state")
async def timer_state(request: Request):
    """Current timer display state (REST fallback / initial fetch)."""
    seen = request.query_params.get("lastConfigSeenAt") or 0
    client_timestamp = js_date_to_epoch(seen)
    config = get_full_config()
    config_changed = js_date_to_epoch(config["updated_at"]) > client_timestamp

    state = get_timer_state()
    # Append config only if changed since the client last saw it.
    if config_changed:
        state["config"] = {**config, "updated_at": config["updated_at"]}
    return JSONResponse(state)


@router.get("/api/timer/closest-draw-duration")
async def closest_draw_duration():
    """Duration (minutes) of the closest upcoming or most recent draw."""
    current = get_current_draw()
    draw = current["nextDraw"] or current["lastEndedDraw"]
    return {"durationMinutes": draw["duration_minutes"] if draw else None}


@router.get("/api/timer/config")
async def read_config(_: None = Depends(require_auth)):
    """Timer display config (for dynamic CSS)."""
    return get_full_config()


@router.put("/api/timer/config")
async def write_config(request: Request, _: None = Depends(require_auth)):
    """Update timer config fields and push changes live to all clients."""
    updates = await read_json(request)
    if not isinstance(updates, dict):
        updates = {}

    # The system-wide time per end is required whenever its override is enabled. Validate
    # here as well as in the settings page so a hand-crafted request cannot store a value
    # the kiosk would have to ignore.
    current = get_full_config() or {}
    if "system_end_minutes" in updates or "use_system_end_minutes" in updates:
        override_on = _flag_enabled(
            updates.get("use_system_end_minutes", current.get("use_system_end_minutes"))
        )
        try:
            minutes = _normalise_system_end_minutes(
                updates.get("system_end_minutes", current.get("system_end_minutes"))
            )
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        if override_on and minutes is None:
            return JSONResponse(
                {"error": "system_end_minutes is required when use_system_end_minutes is enabled"},
                status_code=400,
            )
        if "system_end_minutes" in updates:
            updates["system_end_minutes"] = minutes

    if debug_enabled():
        logger.info("Received updates: %s", updates)

    ok = update_config(updates if isinstance(updates, dict) else {})
    if not ok:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    # Push the new config + timer state to every client so all displays update live.
    broadcast_config()
    broadcast_timer_state()
    return Response(status_code=204)
