"""Timer routes — direct port of ``routes/timer.js``."""

from __future__ import annotations

import logging
logger = logging.getLogger("hammertime.timer")
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
    if debug_enabled():
        logger.info("Received updates: %s", updates)

    ok = update_config(updates if isinstance(updates, dict) else {})
    if not ok:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    # Push the new config + timer state to every client so all displays update live.
    broadcast_config()
    broadcast_timer_state()
    return Response(status_code=204)
