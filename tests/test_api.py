"""HTTP tests: endpoints, status codes, headers, auth and the admin flow.

Every test talks to a real server process running against a sandbox database, frozen at
Wednesday 2026-10-21 10:00 unless stated otherwise.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import jwt
import pytest

from hammertime import __version__
from tests import support

JSON_TYPE = "application/json; charset=utf-8"


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

def test_version(client):
    response = client.get("/api/version")

    assert response.status_code == 200
    assert response.headers["content-type"] == JSON_TYPE
    assert response.json() == {"version": __version__}


def test_timer_state_is_public(client):
    response = client.get("/api/timer/state")

    assert response.status_code == 200
    assert response.headers["content-type"] == JSON_TYPE
    body = response.json()
    assert body["status"] == "waiting"
    # No lastConfigSeenAt means "I have seen nothing", so the config is included.
    assert body["config"]["updated_at"] == support.PINNED_UPDATED_AT


def test_timer_state_honours_last_config_seen_at(client):
    seen = support.PINNED_UPDATED_AT.replace(" ", "T")
    assert "config" not in client.get(
        "/api/timer/state", params={"lastConfigSeenAt": seen}
    ).json()

    behind = client.get("/api/timer/state", params={"lastConfigSeenAt": "2026-10-01T00:00:00"})
    assert behind.json()["config"]["background_color"]


def test_timer_state_follows_the_server_clock(server_factory):
    server = server_factory(support.RUNNING)
    with httpx.Client(base_url=server.base_url, timeout=15) as http_client:
        assert http_client.get("/api/timer/state").json()["status"] == "running"


def test_closest_draw_duration(client):
    assert client.get("/api/timer/closest-draw-duration").json() == {"durationMinutes": 90}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def test_reads_require_a_token(client):
    for endpoint in ("/api/draws", "/api/timer/config"):
        response = client.get(endpoint)
        assert response.status_code == 403
        assert response.headers["content-type"] == JSON_TYPE
        assert response.json() == {"error": "No token"}


def test_writes_require_a_token(client):
    response = client.post(
        "/api/draws",
        json={
            "day_of_week": "Saturday",
            "title": "Nope",
            "message": "",
            "start_time": "08:00",
            "duration_minutes": 60,
        },
    )
    assert response.status_code == 403
    assert response.json() == {"error": "No token"}


def test_login_sets_a_strict_http_only_cookie(client):
    response = client.post("/auth/login", json={"username": "timer", "password": "timer"})

    assert response.status_code == 200
    assert response.json() == {"success": True}

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("token=")
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=3600" in cookie
    assert "samesite=strict" in cookie.lower()


def test_login_accepts_any_username_case(client):
    response = client.post("/auth/login", json={"username": "TIMER", "password": "timer"})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "timer", "password": "wrong"},
        {"username": "nobody", "password": "timer"},
        {"password": "timer"},
    ],
)
def test_login_rejects_bad_credentials(client, credentials):
    response = client.post("/auth/login", json=credentials)

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid credentials"}
    assert "set-cookie" not in response.headers


def test_malformed_token_is_rejected(client):
    response = client.get("/api/draws", headers={"Cookie": "token=not-a-jwt"})

    assert response.status_code == 403
    assert response.json() == {"error": "Invalid or expired token"}


def test_token_expiry_is_checked_against_the_server_clock(client):
    now = int(datetime.fromisoformat(support.WAITING).timestamp())

    def _token(expires_in: int) -> str:
        return jwt.encode(
            {"user": "timer", "exp": now + expires_in}, support.JWT_SECRET, algorithm="HS256"
        )

    expired = client.get("/api/draws", headers={"Cookie": f"token={_token(-1)}"})
    assert expired.status_code == 403
    assert expired.json() == {"error": "Invalid or expired token"}

    valid = client.get("/api/draws", headers={"Cookie": f"token={_token(60)}"})
    assert valid.status_code == 200


def test_change_password_clears_the_cookie_and_updates_the_hash(auth_client):
    response = auth_client.post(
        "/auth/change-password",
        json={"username": "timer", "oldPassword": "timer", "newPassword": "hammer"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("token=;")
    assert "Expires=Thu, 01 Jan 1970 00:00:00 GMT" in cookie
    assert "HttpOnly" in cookie

    # The caller's session cookie is gone, and the new password works.
    assert auth_client.get("/api/draws").status_code == 403
    assert auth_client.post(
        "/auth/login", json={"username": "timer", "password": "hammer"}
    ).status_code == 200


def test_change_password_rejects_a_wrong_old_password(client):
    response = client.post(
        "/auth/change-password",
        json={"username": "timer", "oldPassword": "wrong", "newPassword": "hammer"},
    )

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid credentials"}


# ---------------------------------------------------------------------------
# Weekly draws
# ---------------------------------------------------------------------------

def _draw(**overrides):
    draw = {
        "day_of_week": "Saturday",
        "title": "Extra Draw",
        "message": None,
        "start_time": "08:00",
        "duration_minutes": 60,
    }
    draw.update(overrides)
    return draw


def test_create_draw_returns_the_nested_id(auth_client):
    response = auth_client.post("/api/draws", json=_draw())

    assert response.status_code == 201
    body = response.json()
    # Quirk kept from the original handler: the data-layer result is wrapped, so the
    # id is nested. The admin UI ignores this payload.
    assert body["id"]["override"] is False
    assert isinstance(body["id"]["id"], int)


def test_draw_crud_round_trip(auth_client):
    created = auth_client.post("/api/draws", json=_draw())
    draw_id = created.json()["id"]["id"]

    single = auth_client.get(f"/api/draws/{draw_id}")
    assert single.status_code == 200
    assert single.json()["title"] == "Extra Draw"

    updated = auth_client.put(f"/api/draws/{draw_id}", json=_draw(title="Renamed", start_time="09:00"))
    assert updated.status_code == 204
    assert updated.content == b""
    assert auth_client.get(f"/api/draws/{draw_id}").json()["title"] == "Renamed"

    deleted = auth_client.delete(f"/api/draws/{draw_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    missing = auth_client.delete(f"/api/draws/{draw_id}")
    assert missing.status_code == 404
    assert missing.json() == {"error": "Draw not found"}


def test_draw_list_is_grouped_for_the_week_view(auth_client):
    body = auth_client.get("/api/draws").json()

    assert set(body) == {"drawsForWeek", "futureOverrides"}
    assert [draw["title"] for draw in body["futureOverrides"]] == ["Future Bonspiel"]


@pytest.mark.parametrize("draw_id", ["999999", "abc", "12abc"])
def test_unknown_draw_ids_are_not_found(auth_client, draw_id):
    response = auth_client.get(f"/api/draws/{draw_id}")

    assert response.status_code == 404
    assert response.json() == {"error": "Draw not found"}


def test_overlapping_draw_is_rejected_with_the_original_message(auth_client):
    response = auth_client.post("/api/draws", json=_draw(day_of_week="Wednesday", start_time="19:00"))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error.startswith('This draw overlaps with "Valley League" on Wednesday at 18:30')
    assert auth_client.get("/api/draws").json()["drawsForWeek"]


def test_draw_without_a_day_is_rejected(auth_client):
    response = auth_client.post("/api/draws", json={"title": "Incomplete"})

    assert response.status_code == 400
    assert "error" in response.json()


def test_updating_a_missing_draw_still_reports_success(auth_client):
    # The original reports 204 even when the UPDATE matched no row.
    response = auth_client.put("/api/draws/999999", json=_draw())

    assert response.status_code == 204
    assert auth_client.get("/api/draws/999999").status_code == 404


# ---------------------------------------------------------------------------
# Draw overrides
# ---------------------------------------------------------------------------

def _override(**overrides):
    draw = _draw(override_date="2026-10-24")
    draw.pop("day_of_week")
    draw.update(overrides)
    return draw


def test_override_crud_round_trip(auth_client):
    created = auth_client.post("/api/draw-overrides", json=_override())
    assert created.status_code == 201
    assert created.json()["id"]["override"] is True
    override_id = created.json()["id"]["id"]

    updated = auth_client.put(
        f"/api/draw-overrides/{override_id}",
        json=_override(title="Moved", override_date="2026-10-25"),
    )
    assert updated.status_code == 204

    listed = auth_client.get("/api/draws").json()["futureOverrides"]
    assert "Moved" in [override["title"] for override in listed]

    assert auth_client.delete(f"/api/draw-overrides/{override_id}").status_code == 204
    missing = auth_client.delete(f"/api/draw-overrides/{override_id}")
    assert missing.status_code == 404
    assert missing.json() == {"error": "Draw not found"}


def test_updating_a_missing_override_is_not_found(auth_client):
    response = auth_client.put("/api/draw-overrides/999999", json=_override())

    assert response.status_code == 404
    assert response.json() == {"error": "Override draw not found"}


# ---------------------------------------------------------------------------
# Timer config
# ---------------------------------------------------------------------------

def test_config_requires_auth_and_round_trips(auth_client):
    config = auth_client.get("/api/timer/config")
    assert config.status_code == 200
    assert config.json()["updated_at"] == support.PINNED_UPDATED_AT

    updated = auth_client.put("/api/timer/config", json={"background_color": "#101010"})
    assert updated.status_code == 204
    assert updated.content == b""

    assert auth_client.get("/api/timer/config").json()["background_color"] == "#101010"
    assert auth_client.get("/api/timer/config").json()["updated_at"] != support.PINNED_UPDATED_AT


def test_config_round_trips_the_idle_message_color(auth_client):
    """The idle message colour is a base column (like status_color), not a suffixed one."""
    assert auth_client.get("/api/timer/config").json()["message_color"] == "#eeeeee"

    updated = auth_client.put("/api/timer/config", json={"message_color": "#123456"})
    assert updated.status_code == 204

    assert auth_client.get("/api/timer/config").json()["message_color"] == "#123456"


@pytest.mark.parametrize("body", [{}, {"unknown": "value"}])
def test_config_rejects_updates_without_known_fields(auth_client, body):
    response = auth_client.put("/api/timer/config", json=body)

    assert response.status_code == 400
    assert response.json() == {"error": "No valid fields to update"}


# ---------------------------------------------------------------------------
# Admin page flow (the browser relies on all of these shapes)
# ---------------------------------------------------------------------------

def test_admin_create_update_delete_flow(auth_client):
    """Mirror of ``public/admin.js``: it posts to the trailing-slash URLs."""
    created = auth_client.post(
        "/api/draws/",
        json=_draw(day_of_week="Saturday", title="Admin Flow Draw", start_time="08:00", duration_minutes=45),
    )
    assert created.status_code == 201, created.text
    draw_id = created.json()["id"]["id"]

    listing = auth_client.get("/api/draws/")
    assert listing.status_code == 200, listing.text
    assert "Admin Flow Draw" in [draw["title"] for draw in listing.json()["drawsForWeek"]]

    updated = auth_client.put(
        f"/api/draws/{draw_id}",
        json=_draw(
            day_of_week="Saturday",
            title="Admin Flow Draw Updated",
            start_time="08:30",
            duration_minutes=45,
        ),
    )
    assert updated.status_code == 204, updated.text
    assert auth_client.get(f"/api/draws/{draw_id}").json()["title"] == "Admin Flow Draw Updated"

    assert auth_client.delete(f"/api/draws/{draw_id}").status_code == 204
    assert auth_client.delete(f"/api/draws/{draw_id}").status_code == 404

    override = auth_client.post("/api/draw-overrides/", json=_override(title="Admin Flow Override"))
    assert override.status_code == 201, override.text
    override_id = override.json()["id"]["id"]
    assert auth_client.delete(f"/api/draw-overrides/{override_id}/").status_code == 204

    # The settings page saves through the same trailing-slash route.
    assert auth_client.get("/api/timer/config/").status_code == 200
    assert auth_client.put("/api/timer/config/", json={"background_color": "#101010"}).status_code == 204
    assert auth_client.get("/admin/").status_code == 302

    # Static assets are not rewritten: a trailing slash on a file stays a miss.
    assert auth_client.get("/does-not-exist/").status_code == 404


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("path", "content_type", "needle"),
    [
        ("/", "text/html; charset=utf-8", 'id="timer"'),
        ("/admin.html", "text/html; charset=utf-8", "admin"),
        ("/settings.html", "text/html; charset=utf-8", "settings"),
        ("/login.html", "text/html; charset=utf-8", "login"),
        ("/app.js", "application/javascript; charset=utf-8", "EventSource"),
        ("/manifest.json", "application/json; charset=utf-8", "name"),
        ("/favicon.ico", "image/vnd.microsoft.icon", None),
    ],
)
def test_static_files_keep_the_original_content_types(client, path, content_type, needle):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    if needle:
        assert needle.lower() in response.text.lower()


def test_admin_redirect(client):
    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/admin.html"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == "Found. Redirecting to /admin.html"


def test_unknown_path_is_not_found(client):
    assert client.get("/no-such-page").status_code == 404


def test_malformed_json_body_is_a_bad_request(auth_client):
    response = auth_client.post(
        "/api/draws",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
