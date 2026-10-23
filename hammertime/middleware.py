"""ASGI middleware that restores Express's non-strict route matching.

Express matches ``/api/draws`` and ``/api/draws/`` identically (``strict routing`` is
off by default). Starlette does not: the catch-all static mount at ``/`` matches every
path, so ``/api/draws/`` is answered by ``StaticFiles`` instead of being routed — a
``POST`` gets **405 Method Not Allowed** and a ``GET`` gets 404.

The admin UI relies on this: it builds the endpoint as ``/api/draws/${form.id.value}``,
which is ``/api/draws/`` (trailing slash) when creating a new draw.

Rewriting the path before routing makes both forms hit the same handler, with no
redirect, which is exactly what Express does.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def _is_route_path(stripped_path: str) -> bool:
    """True for paths served by a route (not by the static file mount).

    Static assets are excluded so ``/app.js/`` stays a 404, matching serve-static.
    """
    return (
        stripped_path.startswith("/api/")
        or stripped_path.startswith("/auth/")
        or stripped_path in ("/events", "/admin")
    )


class StripTrailingSlashMiddleware:
    """Route ``/api/draws/`` to the ``/api/draws`` handler."""

    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            path = scope.get("path") or "/"
            if path != "/" and path.endswith("/"):
                stripped = path[:-1]
                if _is_route_path(stripped):
                    scope = dict(scope)
                    scope["path"] = stripped
                    raw_path = scope.get("raw_path")
                    if raw_path and raw_path.endswith(b"/"):
                        scope["raw_path"] = raw_path[:-1]
        await self.app(scope, receive, send)
