"""Weekly draw routes — direct port of ``routes/draws.js``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from hammertime.auth import require_auth
from hammertime.broadcast import broadcast_timer_state
from hammertime.db import (
    add_draw,
    delete_draw,
    get_all_draws,
    get_draw_by_id,
    update_draw,
)
from hammertime.responses import JSONResponse
from hammertime.web import read_json

router = APIRouter()


def _js_parse_int(value: str):
    """``parseInt(value)`` for route params — ``None`` where JS yields NaN.

    Node passes NaN to SQLite, which turns it into NULL, so no row ever matches.
    """
    text = (value or "").strip()
    digits = ""
    for index, char in enumerate(text):
        if char in "+-" and index == 0:
            digits += char
        elif char.isdigit():
            digits += char
        else:
            break
    try:
        return int(digits)
    except ValueError:
        return None


@router.get("/api/draws")
async def list_draws(_: None = Depends(require_auth)):
    """List all draws (weekly + overrides)."""
    return get_all_draws()


@router.get("/api/draws/{draw_id}")
async def read_draw(draw_id: str, _: None = Depends(require_auth)):
    """Get a single recurring draw by id."""
    draw = get_draw_by_id(_js_parse_int(draw_id))
    if not draw:
        return JSONResponse({"error": "Draw not found"}, status_code=404)
    return draw


@router.post("/api/draws")
async def create_draw(request: Request, _: None = Depends(require_auth)):
    """Create a new recurring draw."""
    body = await read_json(request)
    try:
        result = add_draw(body)
    except Exception as error:  # noqa: BLE001 - original turns any failure into a 400
        return JSONResponse({"error": str(error)}, status_code=400)

    broadcast_timer_state()
    # Quirk preserved: addDraw() already returns {id, override}, so the response is
    # {"id": {"id": N, "override": false}}.
    return JSONResponse({"id": result}, status_code=201)


@router.put("/api/draws/{draw_id}")
async def replace_draw(draw_id: str, request: Request, _: None = Depends(require_auth)):
    """Update an existing recurring draw."""
    body = await read_json(request)
    try:
        # The raw string id is passed through to SQLite (integer affinity matches it).
        update_draw(draw_id, body)
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)

    broadcast_timer_state()
    return Response(status_code=204)


@router.delete("/api/draws/{draw_id}")
async def remove_draw(draw_id: str, _: None = Depends(require_auth)):
    """Delete a recurring draw."""
    try:
        deleted = delete_draw(draw_id)
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)

    if not deleted:
        return JSONResponse({"error": "Draw not found"}, status_code=404)

    broadcast_timer_state()
    return Response(status_code=204)
