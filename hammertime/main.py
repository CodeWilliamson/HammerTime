"""ASGI application wiring — direct port of ``index.js``."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import Response

from hammertime import __version__, config
from hammertime.auth import AuthError
from hammertime.auth import router as auth_router
from hammertime.broadcast import handle_events
from hammertime.middleware import StripTrailingSlashMiddleware
from hammertime.responses import JSONResponse, StaticFiles
from hammertime.routes import draw_overrides as draw_override_routes
from hammertime.routes import draws as draw_routes
from hammertime.routes import timer as timer_routes


def create_app() -> FastAPI:
    # docs/openapi are disabled: the Node server exposes no such endpoints.
    app = FastAPI(
        title="HammerTime",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        # Express sends `application/json; charset=utf-8` for every res.json().
        default_response_class=JSONResponse,
    )

    @app.exception_handler(AuthError)
    async def _auth_error(_: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse({"error": exc.message}, status_code=403)

    # Express treats `/api/draws/` and `/api/draws` as the same route; the static mount
    # would otherwise answer the trailing-slash form with 404/405. Must be added before
    # the first request, and it is a pure-ASGI middleware so SSE streaming is untouched.
    app.add_middleware(StripTrailingSlashMiddleware)

    # Mount REST route modules (paths include their own prefixes, like app.use()).
    for router in (
        auth_router,
        timer_routes.router,
        draw_routes.router,
        draw_override_routes.router,
    ):
        app.include_router(router)

    # Redirect /admin to the admin HTML page (Express redirects with 302 and a
    # text/plain body: `res.type('txt').send('Found. Redirecting to ...')`).
    @app.get("/admin")
    async def admin_redirect() -> Response:
        return Response(
            content="Found. Redirecting to /admin.html",
            status_code=302,
            headers={"Location": "/admin.html"},
            media_type="text/plain; charset=utf-8",
        )

    # API version metadata.
    @app.get("/api/version")
    async def version() -> dict:
        return {"version": __version__}

    # Server-Sent Events stream: live timer state + config for all display pages.
    @app.get("/events")
    async def events(request: Request):
        return await handle_events(request)

    # Static frontend last, so API routes always win (express.static is mounted first
    # in Node, but no frontend file shadows an API path).
    app.mount("/", StaticFiles(directory=str(config.PUBLIC_DIR), html=True), name="public")

    return app


app = create_app()
