"""Date-specific draw override routes — direct port of ``routes/drawOverrides.js``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from hammertime.auth import require_auth
from hammertime.broadcast import broadcast_timer_state
from hammertime.db import add_draw_override, delete_draw_override, update_draw_override
from hammertime.responses import JSONResponse
from hammertime.web import read_json

router = APIRouter()


@router.post("/api/draw-overrides")
async def create_override(request: Request, _: None = Depends(require_auth)):
    """Create a new draw override for a specific date."""
    body = await read_json(request)
    try:
        result = add_draw_override(body)
    except Exception as error:  # noqa: BLE001 - original turns any failure into a 400
        return JSONResponse({"error": str(error)}, status_code=400)

    broadcast_timer_state()
    # Quirk preserved: the handler wraps addDrawOverride()'s {id, override} payload.
    return JSONResponse({"id": result}, status_code=201)


@router.put("/api/draw-overrides/{override_id}")
async def replace_override(
    override_id: str, request: Request, _: None = Depends(require_auth)
):
    """Update an existing draw override."""
    body = await read_json(request)
    try:
        updated = update_draw_override(override_id, body)
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)

    if not updated:
        return JSONResponse({"error": "Override draw not found"}, status_code=404)

    broadcast_timer_state()
    return Response(status_code=204)


@router.delete("/api/draw-overrides/{override_id}")
async def remove_override(override_id: str, _: None = Depends(require_auth)):
    """Delete a draw override."""
    try:
        deleted = delete_draw_override(override_id)
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)

    if not deleted:
        return JSONResponse({"error": "Draw not found"}, status_code=404)

    broadcast_timer_state()
    return Response(status_code=204)
