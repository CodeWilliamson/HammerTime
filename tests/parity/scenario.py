"""The request scripts replayed against both servers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from tests.parity.harness import normalise_response

Capture = Callable[..., None]


def _capture_into(results: List[Dict[str, Any]]) -> Capture:
    def capture(label: str, response: httpx.Response, compare: str = "full") -> None:
        results.append(
            {"label": label, "compare": compare, **normalise_response(response)}
        )

    return capture


def _iso_utc_from_local(value: str) -> str:
    """Turn SQLite's local "YYYY-MM-DD HH:MM:SS" into the ISO string the kiosk sends."""
    return (
        datetime.fromisoformat(value)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")
    )


def run_read_script(base_url: str) -> List[Dict[str, Any]]:
    """Read-only scenario: timer state + week view at a frozen instant."""
    results: List[Dict[str, Any]] = []
    capture = _capture_into(results)

    with httpx.Client(base_url=base_url, timeout=10) as client:
        capture("version", client.get("/api/version"))

        # Public timer endpoints (no auth).
        capture("state/no-param", client.get("/api/timer/state"))
        capture("state/epoch", client.get("/api/timer/state?lastConfigSeenAt=1970-01-01T00:00:00.000Z"))
        capture(
            "state/future",
            client.get("/api/timer/state?lastConfigSeenAt=2030-01-01T00:00:00.000Z"),
        )
        capture("state/garbage", client.get("/api/timer/state?lastConfigSeenAt=not-a-date"))
        capture("closest-draw-duration", client.get("/api/timer/closest-draw-duration"))

        # Unauthenticated admin endpoints answer 403 with a specific body.
        capture("draws/unauth", client.get("/api/draws"))
        capture("config/unauth", client.get("/api/timer/config"))

        capture(
            "login",
            client.post(
                "/auth/login", json={"username": "timer", "password": "timer"}
            ),
        )

        capture("config", client.get("/api/timer/config"))

        # Read the raw timestamp separately (captured bodies mask updated_at so that
        # runs on different machines stay comparable).
        config = client.get("/api/timer/config").json()
        if isinstance(config, dict) and config.get("updated_at"):
            capture(
                "state/same-local",
                client.get(
                    "/api/timer/state",
                    params={"lastConfigSeenAt": config["updated_at"]},
                ),
            )
            capture(
                "state/same-iso",
                client.get(
                    "/api/timer/state",
                    params={"lastConfigSeenAt": _iso_utc_from_local(config["updated_at"])},
                ),
            )

        capture("draws", client.get("/api/draws"))

    return results


def run_mutation_script(base_url: str) -> List[Dict[str, Any]]:
    """Full CRUD scenario: every documented status code and payload shape."""
    results: List[Dict[str, Any]] = []
    capture = _capture_into(results)

    with httpx.Client(base_url=base_url, timeout=10) as client:
        capture("version", client.get("/api/version"))
        capture("root", client.get("/"))
        capture("admin-redirect", client.get("/admin"))

        # --- static frontend ------------------------------------------------
        for page in ("index.html", "admin.html", "settings.html", "login.html"):
            capture(f"static/{page}", client.get(f"/{page}"))
        for asset in ("main.css", "admin.css", "app.js", "settings.js", "admin.js",
                      "manifest.json", "favicon.ico", "firstcall.mp3"):
            capture(f"static/{asset}", client.get(f"/{asset}"))
        capture("static/missing", client.get("/does-not-exist.html"), compare="status")

        # --- auth edge cases -------------------------------------------------
        capture(
            "login/wrong-password",
            client.post("/auth/login", json={"username": "timer", "password": "nope"}),
        )
        capture(
            "login/unknown-user",
            client.post("/auth/login", json={"username": "ghost", "password": "timer"}),
        )
        capture(
            "login/uppercase",
            client.post("/auth/login", json={"username": "TIMER", "password": "timer"}),
        )
        capture(
            "login",
            client.post("/auth/login", json={"username": "timer", "password": "timer"}),
        )

        # --- reads -----------------------------------------------------------
        capture("config", client.get("/api/timer/config"))
        capture("draws", client.get("/api/draws"))
        capture("draw/1", client.get("/api/draws/1"))
        capture("draw/9999", client.get("/api/draws/9999"))
        capture("draw/not-a-number", client.get("/api/draws/not-a-number"))
        capture("draw/12abc", client.get("/api/draws/12abc"))

        # --- weekly draw CRUD ------------------------------------------------
        capture(
            "draw/create",
            client.post(
                "/api/draws",
                json={
                    "day_of_week": "Friday",
                    "title": "Parity Draw",
                    "message": "created by the suite",
                    "start_time": "10:00",
                    "duration_minutes": 60,
                },
            ),
        )
        created = results[-1]["body"]
        new_id = created["id"]["id"] if isinstance(created, dict) else 0

        capture(
            "draw/create-overlap",
            client.post(
                "/api/draws",
                json={
                    "day_of_week": "Wednesday",
                    "title": "Overlapping",
                    "message": "",
                    "start_time": "19:00",
                    "duration_minutes": 60,
                },
            ),
        )
        capture(
            "draw/create-missing-title",
            client.post(
                "/api/draws",
                json={
                    "day_of_week": "Friday",
                    "message": "",
                    "start_time": "11:00",
                    "duration_minutes": 60,
                },
            ),
            compare="status",
        )
        capture(
            "draw/update",
            client.put(
                f"/api/draws/{new_id}",
                json={
                    "day_of_week": "Friday",
                    "title": "Parity Draw Updated",
                    "message": None,
                    "start_time": "10:30",
                    "duration_minutes": 75,
                },
            ),
        )
        capture("draw/after-update", client.get(f"/api/draws/{new_id}"))
        capture(
            "draw/update-overlap",
            client.put(
                f"/api/draws/{new_id}",
                json={
                    "day_of_week": "Wednesday",
                    "title": "Clash",
                    "message": "",
                    "start_time": "18:30",
                    "duration_minutes": 60,
                },
            ),
        )
        capture("draw/delete", client.delete(f"/api/draws/{new_id}"))
        capture("draw/delete-again", client.delete(f"/api/draws/{new_id}"))
        capture("draw/delete-missing", client.delete("/api/draws/9999"))

        # --- override CRUD ---------------------------------------------------
        capture(
            "override/create",
            client.post(
                "/api/draw-overrides",
                json={
                    "override_date": "2026-10-24",
                    "title": "Parity Bonspiel",
                    "message": "",
                    "start_time": "09:00",
                    "duration_minutes": 120,
                },
            ),
        )
        override = results[-1]["body"]
        override_id = override["id"]["id"] if isinstance(override, dict) else 0

        capture(
            "override/update",
            client.put(
                f"/api/draw-overrides/{override_id}",
                json={
                    "override_date": "2026-10-24",
                    "title": "Parity Bonspiel Updated",
                    "message": "final",
                    "start_time": "10:00",
                    "duration_minutes": 90,
                },
            ),
        )
        capture(
            "override/update-missing",
            client.put(
                "/api/draw-overrides/9999",
                json={
                    "override_date": "2026-10-24",
                    "title": "ghost",
                    "message": "",
                    "start_time": "10:00",
                    "duration_minutes": 90,
                },
            ),
        )
        capture("override/delete", client.delete(f"/api/draw-overrides/{override_id}"))
        capture("override/delete-again", client.delete(f"/api/draw-overrides/{override_id}"))

        # --- config ----------------------------------------------------------
        capture(
            "config/update",
            client.put("/api/timer/config", json={"background_color": "#123456"}),
        )
        capture("config/after-update", client.get("/api/timer/config"))
        capture("config/no-fields", client.put("/api/timer/config", json={"nope": 1}))
        capture(
            "config/mixed-fields",
            client.put(
                "/api/timer/config",
                json={"nope": 1, "show_admin_url": 0, "timer_font_size": "30vw"},
            ),
        )
        capture("config/after-mixed", client.get("/api/timer/config"))

        # Timer state now reports the changed config.
        capture("state/after-config", client.get("/api/timer/state"))
        capture("draws/after-mutations", client.get("/api/draws"))

        # --- password change -------------------------------------------------
        capture(
            "password/wrong-old",
            client.post(
                "/auth/change-password",
                json={
                    "username": "timer",
                    "oldPassword": "wrong",
                    "newPassword": "newpass",
                },
            ),
        )
        capture(
            "password/change",
            client.post(
                "/auth/change-password",
                json={
                    "username": "timer",
                    "oldPassword": "timer",
                    "newPassword": "newpass",
                },
            ),
        )
        # The cookie was cleared; the old password no longer works.
        capture("config/after-password-change", client.get("/api/timer/config"))
        capture(
            "login/old-password",
            client.post("/auth/login", json={"username": "timer", "password": "timer"}),
        )
        capture(
            "login/new-password",
            client.post("/auth/login", json={"username": "timer", "password": "newpass"}),
        )

        # --- trailing slashes -------------------------------------------------
        # Express matches routes with or without a trailing slash (strict routing is
        # off), and the admin UI POSTs to `/api/draws/` when creating a new draw.
        capture("slash/draws-get", client.get("/api/draws/"))
        capture("slash/version", client.get("/api/version/"))
        capture("slash/state", client.get("/api/timer/state/"))
        capture("slash/closest-duration", client.get("/api/timer/closest-draw-duration/"))
        capture("slash/config-get", client.get("/api/timer/config/"))
        capture("slash/admin", client.get("/admin/"))
        capture(
            "slash/draws-create",
            client.post(
                "/api/draws/",
                json={
                    "day_of_week": "Saturday",
                    "title": "Trailing Slash Draw",
                    "message": "",
                    "start_time": "06:00",
                    "duration_minutes": 30,
                },
            ),
        )
        created = results[-1]["body"]
        slash_id = created["id"]["id"] if isinstance(created, dict) else 0
        capture(
            "slash/draws-update",
            client.put(
                f"/api/draws/{slash_id}/",
                json={
                    "day_of_week": "Saturday",
                    "title": "Trailing Slash Draw Updated",
                    "message": None,
                    "start_time": "06:30",
                    "duration_minutes": 30,
                },
            ),
        )
        capture("slash/draws-delete", client.delete(f"/api/draws/{slash_id}/"))
        capture(
            "slash/override-create",
            client.post(
                "/api/draw-overrides/",
                json={
                    "override_date": "2026-10-25",
                    "title": "Trailing Slash Override",
                    "message": "",
                    "start_time": "07:00",
                    "duration_minutes": 30,
                },
            ),
        )
        override = results[-1]["body"]
        slash_override_id = override["id"]["id"] if isinstance(override, dict) else 0
        capture(
            "slash/override-delete", client.delete(f"/api/draw-overrides/{slash_override_id}/")
        )
        capture(
            "slash/config-put",
            client.put("/api/timer/config/", json={"background_color": "#123456"}),
        )
        capture(
            "slash/login",
            client.post("/auth/login/", json={"username": "timer", "password": "newpass"}),
        )
        capture("slash/draws-final", client.get("/api/draws/"))

    return results


def compare_results(
    left: List[Dict[str, Any]], right: List[Dict[str, Any]]
) -> Optional[str]:
    """Return a readable diff string, or None when the two runs agree."""
    if len(left) != len(right):
        return f"step count differs: {len(left)} != {len(right)}"

    for expected, actual in zip(left, right):
        if expected["label"] != actual["label"]:
            return f"label mismatch: {expected['label']} != {actual['label']}"

        compare = expected["compare"]
        if compare == "status":
            # Steps whose framework-level output is intentionally different
            # (e.g. Express's HTML 404 page vs Starlette's JSON 404) compare only
            # the status code.
            if expected["status"] != actual["status"]:
                return (
                    f"[{expected['label']}] status differs: "
                    f"{expected['status']} != {actual['status']}"
                )
            continue

        for field in ("status", "content_type", "cookie"):
            if expected[field] != actual[field]:
                return (
                    f"[{expected['label']}] {field} differs:\n"
                    f"  node:   {expected[field]!r}\n"
                    f"  python: {actual[field]!r}"
                )
        if expected["body"] != actual["body"]:
            return (
                f"[{expected['label']}] body differs:\n"
                f"  node:   {expected['body']!r}\n"
                f"  python: {actual['body']!r}"
            )

    return None
