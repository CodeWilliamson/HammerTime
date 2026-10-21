"""HTTP helpers shared by the route modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request


async def read_json(request: Request) -> Any:
    """Parse the request body the way ``express.json()`` + ``req.body`` is used.

    The original handlers destructure ``req.body`` directly and never validate it, so
    this returns whatever the JSON document contains (normally a dict).
    """
    try:
        return await request.json()
    except Exception:
        # express.json() rejects malformed JSON before the route runs (400).
        raise HTTPException(status_code=400, detail="Invalid JSON body")


def js_date_to_epoch(value: Any) -> float:
    """``new Date(value).getTime() / 1000`` — NaN when JS would produce an Invalid Date."""
    if isinstance(value, bool):
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value) / 1000.0
    try:
        text = str(value).strip()
        if text[-1:] in ("Z", "z"):
            text = text[:-1] + "+00:00"
        # Naive strings (SQLite's "YYYY-MM-DD HH:MM:SS") are local time, like V8.
        return datetime.fromisoformat(text).timestamp()
    except (ValueError, IndexError):
        return float("nan")
