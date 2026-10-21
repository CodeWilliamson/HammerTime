"""Regression test for the admin create/edit/delete flow.

`public/admin.js` builds the endpoint as ``/api/draws/${form.id.value}`` — i.e. it POSTs
to ``/api/draws/`` (with a trailing slash) when creating a new draw, and to
``/api/draw-overrides/`` when creating a new override. Express matches both forms; without
``hammertime/middleware.py`` the catch-all static mount answered those POSTs with
405 Method Not Allowed.

This test needs no Node server, so it keeps guarding the flow after the cutover.
"""

from __future__ import annotations

import httpx

from tests.parity import harness


def _login(client: httpx.Client) -> None:
    response = client.post("/auth/login", json={"username": "timer", "password": "timer"})
    assert response.status_code == 200, response.text


def test_admin_create_update_delete_draw_uses_trailing_slash(start_python):
    server = start_python(harness.MUTATION_INSTANT)

    with httpx.Client(base_url=server.base_url, timeout=10) as client:
        _login(client)

        # Create: admin.js POSTs to `/api/draws/` for a new draw.
        created = client.post(
            "/api/draws/",
            json={
                "day_of_week": "Saturday",
                "title": "Admin Flow Draw",
                "message": "",
                "start_time": "08:00",
                "duration_minutes": 45,
            },
        )
        assert created.status_code == 201, created.text
        draw_id = created.json()["id"]["id"]

        listing = client.get("/api/draws/")
        assert listing.status_code == 200, listing.text
        assert "Admin Flow Draw" in [draw["title"] for draw in listing.json()["drawsForWeek"]]

        # Update: admin.js uses the un-slashed form with an id.
        updated = client.put(
            f"/api/draws/{draw_id}",
            json={
                "day_of_week": "Saturday",
                "title": "Admin Flow Draw Updated",
                "message": None,
                "start_time": "08:30",
                "duration_minutes": 45,
            },
        )
        assert updated.status_code == 204, updated.text
        assert client.get(f"/api/draws/{draw_id}").json()["title"] == "Admin Flow Draw Updated"

        # Delete, both plain and with a trailing slash.
        assert client.delete(f"/api/draws/{draw_id}").status_code == 204
        assert client.delete(f"/api/draws/{draw_id}").status_code == 404

        # Same story for overrides: `/api/draw-overrides/` on create.
        override = client.post(
            "/api/draw-overrides/",
            json={
                "override_date": "2026-10-24",
                "title": "Admin Flow Override",
                "message": "",
                "start_time": "09:00",
                "duration_minutes": 60,
            },
        )
        assert override.status_code == 201, override.text
        override_id = override.json()["id"]["id"]
        assert client.delete(f"/api/draw-overrides/{override_id}/").status_code == 204

        # Config saves (settings page) and the /admin redirect also accept a slash.
        assert client.get("/api/timer/config/").status_code == 200
        assert client.put("/api/timer/config/", json={"background_color": "#101010"}).status_code == 204
        assert client.get("/admin/").status_code == 302

        # Static assets must not be rewritten: a trailing slash on a file stays a miss.
        assert client.get("/does-not-exist/").status_code == 404
