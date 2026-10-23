"""Browser tests for the kiosk, admin and settings pages.

Two layers:

* behaviour/style assertions — always run (fast, deterministic, no pixels);
* screenshot baselines — marked ``visual``, opt-in (see ``conftest.py``).

The kiosk is CSS-class + CSS-variable driven, so both layers verify the same thing from
different angles: the right classes and config colours actually reach the screen.
"""

from __future__ import annotations

import httpx
import pytest

from tests import support


def _text(page, selector: str) -> str:
    return " ".join(page.locator(selector).inner_text().split())


def _classes(page) -> set:
    return set(page.evaluate("Array.from(document.body.classList)"))


def _background(page) -> str:
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


def _log_in(context, server) -> None:
    response = context.request.post(
        f"{server.base_url}/auth/login",
        data={"username": "timer", "password": "timer"},
    )
    assert response.ok, response.text()


# ---------------------------------------------------------------------------
# Timer states
# ---------------------------------------------------------------------------

def test_waiting_state(kiosk):
    page = kiosk(support.WAITING)

    assert _text(page, "#label") == "Next draw: 6:30 PM"
    assert _text(page, "#timer") == ""
    assert _classes(page) == {"no-timer"}
    assert _background(page) == "rgb(0, 0, 0)"


def test_pre_draw_state(kiosk):
    page = kiosk(support.PRE_DRAW)

    # Exactly five minutes out: the pre-draw warning threshold (300 s) is not reached yet.
    assert _classes(page) == {"pre-draw-neutral"}
    assert _text(page, "#label") == "Draw starts in:"
    assert _text(page, "#timer") == "05:00"
    assert _text(page, "#message") == "Sheet 1-4"


def test_running_state(kiosk):
    page = kiosk(support.RUNNING)

    assert _classes(page) == {"running"}
    assert _text(page, "#label") == "Time remaining:"
    assert _text(page, "#timer") == "30:00"
    # The running colour comes from timer_config.background_color_running.
    assert _background(page) == "rgb(26, 219, 0)"


def test_warning_state(kiosk):
    page = kiosk(support.WARNING)

    assert _classes(page) == {"running", "warning"}
    assert _text(page, "#timer") == "10:00"
    assert _background(page) == "rgb(255, 174, 0)"


def test_complete_state(kiosk):
    page = kiosk(support.COMPLETE)

    assert _classes(page) == {"running", "critical"}
    assert _text(page, "#label") == "Time's Up!"
    assert _text(page, "#timer") == "0:00:00"
    assert _background(page) == "rgb(255, 0, 0)"


def test_idle_state(kiosk):
    page = kiosk(support.IDLE)

    assert _text(page, "#label") == "No more draws today"
    assert _text(page, "#timer") == ""
    assert _classes(page) == {"no-timer"}


def test_countdown_advances_with_the_clock(kiosk):
    page = kiosk(support.RUNNING)
    assert _text(page, "#timer") == "30:00"

    page.clock.fast_forward(1000)
    assert _text(page, "#timer") == "29:59"

    page.clock.fast_forward(60_000)
    assert _text(page, "#timer") == "28:59"


# ---------------------------------------------------------------------------
# Live updates and interaction
# ---------------------------------------------------------------------------

def test_config_change_repaints_the_display_without_a_reload(open_page):
    page, server, _context = open_page(support.RUNNING, "/")
    page.wait_for_function("document.getElementById('label').textContent !== 'Loading...'")
    assert _background(page) == "rgb(26, 219, 0)"

    with httpx.Client(base_url=server.base_url, timeout=15) as http_client:
        http_client.post("/auth/login", json={"username": "timer", "password": "timer"})
        response = http_client.put(
            "/api/timer/config", json={"background_color_running": "#0044ff"}
        )
        assert response.status_code == 204

    # The kiosk repaints from the SSE `config` event — no reload, no polling.
    page.wait_for_function(
        "getComputedStyle(document.body).backgroundColor === 'rgb(0, 68, 255)'"
    )


def test_tapping_the_screen_starts_a_local_timer(kiosk):
    page = kiosk(support.WAITING)

    page.mouse.click(640, 400)
    page.wait_for_selector("#local-dialog[open]")

    # Prefilled with the closest draw's duration (the 18:30 draw runs 90 minutes).
    page.wait_for_function("document.getElementById('local-duration').value !== ''")
    page.click("#local-dialog button[value=start]")

    page.wait_for_selector("#local-badge:not([hidden])")
    assert _text(page, "#local-badge") == "LOCAL TIMER"
    assert _text(page, "#timer") == "1:30:00"

    stored = page.evaluate("JSON.parse(localStorage.getItem('localTimer'))")
    assert stored["targetTime"] > 0


def test_admin_can_log_in_and_create_a_draw(open_page):
    page, _server, _context = open_page(support.DEFAULT_INSTANT, "/login.html")

    page.fill("#username", "timer")
    page.fill("#password", "timer")
    page.click("#loginForm button[type=submit]")
    page.wait_for_url("**/admin.html")
    page.wait_for_selector(".draw-card-abs")

    assert page.locator(".day-wrapper").count() == 7
    assert "Bonspiel Draw 1" in _text(page, ".calendar-grid")

    # The create form posts to `/api/draws/` (trailing slash) — the endpoint the
    # trailing-slash middleware exists for.
    page.click(".add-btn")
    page.fill("input[name=title]", "UI Draw")
    page.select_option("select[name=day_of_week]", "Saturday")
    page.fill("input[name=start_time]", "08:00")
    page.fill("input[name=duration_minutes]", "45")
    page.click("#drawForm button[type=submit]")

    page.wait_for_selector("text=UI Draw")


def test_settings_page_loads_the_current_config(open_page):
    page, server, context = open_page(support.DEFAULT_INSTANT, "/login.html")
    _log_in(context, server)
    page.goto(server.base_url + "/settings.html")

    page.wait_for_selector("#configForm")
    assert page.input_value("#running_warning_threshold") == "900"
    assert page.input_value("#pre_draw_warning_threshold") == "300"
    assert page.is_checked("#show_admin_url")
    assert page.is_checked("#dynamic_timer_format")
    # The idle message colour is the base column; its input name must match it exactly.
    assert page.input_value('input[name="message_color"]') == "#eeeeee"

    # Save is disabled until something actually changes, then reports success.
    assert page.is_disabled("#saveBtn")
    page.fill("#running_warning_threshold", "600")
    assert page.is_enabled("#saveBtn")
    page.click("#saveBtn")
    page.wait_for_selector("#configStatus:has-text('Saved')")


# ---------------------------------------------------------------------------
# Screenshot baselines (opt-in: pytest -m visual)
# ---------------------------------------------------------------------------

@pytest.mark.visual
@pytest.mark.parametrize(
    ("instant", "name"),
    [
        (support.WAITING, "waiting"),
        (support.PRE_DRAW, "pre-draw"),
        (support.RUNNING, "running"),
        (support.WARNING, "warning"),
        (support.COMPLETE, "complete"),
        (support.IDLE, "idle"),
    ],
)
def test_kiosk_state_screenshot(kiosk, screenshot, instant, name):
    screenshot(kiosk(instant), f"kiosk-{name}")


@pytest.mark.visual
def test_admin_page_screenshot(open_page, screenshot):
    page, server, context = open_page(support.DEFAULT_INSTANT, "/login.html")
    _log_in(context, server)
    page.goto(server.base_url + "/admin.html")
    page.wait_for_selector(".draw-card-abs")

    screenshot(page, "admin-calendar")


@pytest.mark.visual
def test_settings_page_screenshot(open_page, screenshot):
    page, server, context = open_page(support.DEFAULT_INSTANT, "/login.html")
    _log_in(context, server)
    page.goto(server.base_url + "/settings.html")
    page.wait_for_selector("#configForm")

    screenshot(page, "settings")
