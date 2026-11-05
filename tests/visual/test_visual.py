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


def _font_size(page, selector: str) -> float:
    return page.evaluate(
        "sel => parseFloat(getComputedStyle(document.querySelector(sel)).fontSize)", selector
    )


def _no_transitions(page) -> None:
    """Freeze animations before measuring.

    CSS transitions run on the compositor clock, not the faked JS clock the browser is
    pinned to, so a size read straight after load could catch the badge mid-animation.
    """
    page.add_style_tag(content="*{transition:none !important}")


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
# End counter
# ---------------------------------------------------------------------------

def test_end_number_replaces_the_status_label(kiosk):
    page = kiosk(support.END_MID, configure=support.enable_end_counter)

    assert _text(page, "#label") == "END 4"
    assert page.locator("#label .end-badge").count() == 1
    # The countdown underneath is untouched.
    assert _text(page, "#timer") == "45:00"


def test_end_number_appears_when_end_two_starts(kiosk):
    # One second before END 2 there is nothing to show; the kiosk's own tick() flips it,
    # so the change does not wait for a server push.
    page = kiosk("2026-10-21T18:43:59", configure=support.enable_end_counter)
    assert _text(page, "#label") == "Time remaining:"

    page.clock.fast_forward(1000)
    assert _text(page, "#label") == "END 2"


def test_end_number_is_hidden_at_the_warning_threshold(kiosk):
    page = kiosk(support.WARNING, configure=support.enable_end_counter)

    # END 6 by the schedule, but only 10:00 remain (< the 900 s warning threshold).
    assert _text(page, "#label") == "Time remaining:"
    assert page.locator("#label .end-badge").count() == 0
    assert "end-highlight" not in _classes(page)


def test_end_number_is_not_shown_when_the_feature_is_off(kiosk):
    page = kiosk(support.END_MID)

    assert _text(page, "#label") == "Time remaining:"
    assert page.locator("#label .end-badge").count() == 0
    assert "end-highlight" not in _classes(page)


def test_end_number_is_enlarged_at_the_start_of_an_end(kiosk):
    # 19:15 is three minutes into END 4 (19:12–19:26), so still the first half.
    page = kiosk(support.END_MID, configure=support.enable_end_counter)
    _no_transitions(page)

    assert "end-highlight" in _classes(page)
    # Enlarged by 1.5× the 8vw status size; the countdown shrinks to 75% of its 32vw.
    assert _font_size(page, "#label") == pytest.approx(1280 * 0.08 * 1.5, rel=0.01)
    assert _font_size(page, "#timer") == pytest.approx(1280 * 0.32 * 0.75, rel=0.01)


def test_end_number_returns_to_normal_halfway_through_the_end(kiosk):
    # END 4's halfway point is 19:19; the kiosk's own tick() shrinks the badge.
    page = kiosk(support.END_HALF_BEFORE, configure=support.enable_end_counter)
    _no_transitions(page)
    assert "end-highlight" in _classes(page)

    page.clock.fast_forward(1000)

    assert "end-highlight" not in _classes(page)
    assert _text(page, "#label") == "END 4"
    # Back to the plain status size and the configured countdown size.
    assert _font_size(page, "#label") == pytest.approx(1280 * 0.08, rel=0.01)
    assert _font_size(page, "#timer") == pytest.approx(1280 * 0.32, rel=0.01)


def test_enlarged_end_number_does_not_press_against_the_edges(kiosk):
    # The kiosk is 1280x800 in the tests but a real display is 1080p, where the layout is
    # much tighter: the enlarged badge must still fit above the countdown.
    page = kiosk(support.END_MID, configure=support.enable_end_counter)
    _no_transitions(page)

    for width, height in [(1280, 800), (1920, 1080)]:
        page.set_viewport_size({"width": width, "height": height})
        top = page.evaluate(
            "document.querySelector('#label .end-badge').getBoundingClientRect().top"
        )
        bottom = page.evaluate("document.querySelector('#message').getBoundingClientRect().bottom")
        assert top >= 0, f"badge clipped at the top at {width}x{height}"
        assert bottom <= height, f"message pushed off the bottom at {width}x{height}"


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


def test_admin_time_per_end_field_follows_the_setting(open_page):
    # Hidden while the end counter is off, shown once it is enabled.
    page, server, context = open_page(support.DEFAULT_INSTANT, "/login.html")
    _log_in(context, server)
    page.goto(server.base_url + "/admin.html")
    page.wait_for_selector(".draw-card-abs")
    page.click(".add-btn")
    assert not page.is_visible("#endMinutesContainer")

    page, server, context = open_page(
        support.DEFAULT_INSTANT, "/login.html", support.enable_end_counter
    )
    _log_in(context, server)
    page.goto(server.base_url + "/admin.html")
    page.wait_for_selector(".draw-card-abs")
    page.click(".add-btn")
    assert page.is_visible("#endMinutesContainer")


def test_admin_saves_a_time_per_end(open_page):
    page, server, context = open_page(
        support.DEFAULT_INSTANT, "/login.html", support.enable_end_counter
    )
    _log_in(context, server)
    page.goto(server.base_url + "/admin.html")
    page.wait_for_selector(".draw-card-abs")

    page.click(".add-btn")
    page.fill("input[name=title]", "End Counter Draw")
    page.select_option("select[name=day_of_week]", "Saturday")
    page.fill("input[name=start_time]", "08:00")
    page.fill("input[name=duration_minutes]", "90")
    page.fill("input[name=end_minutes]", "12")
    page.click("#drawForm button[type=submit]")
    page.wait_for_selector("text=End Counter Draw")

    draws = context.request.get(f"{server.base_url}/api/draws").json()["drawsForWeek"]
    saved = next(draw for draw in draws if draw["title"] == "End Counter Draw")
    assert saved["end_minutes"] == 12


def test_end_tuning_fields_follow_the_end_counter_setting(open_page):
    page, server, context = open_page(support.DEFAULT_INSTANT, "/login.html")
    _log_in(context, server)
    page.goto(server.base_url + "/settings.html")
    page.wait_for_selector("#configForm")

    # Nothing to tune while the end counter is off.
    assert page.is_disabled("#end_highlight_percent")
    assert page.is_disabled("#end_highlight_scale")
    assert page.is_disabled("#end_highlight_timer_percent")

    page.check("#show_end_number")
    assert page.is_enabled("#end_highlight_percent")
    assert page.is_enabled("#end_highlight_scale")
    assert page.is_enabled("#end_highlight_timer_percent")

    # Their values are still saved while disabled, so switching it off keeps the tuning.
    page.uncheck("#show_end_number")
    assert page.input_value("#end_highlight_percent") == "50"
    assert page.is_disabled("#end_highlight_percent")


def test_settings_page_loads_the_current_config(open_page):
    page, server, context = open_page(support.DEFAULT_INSTANT, "/login.html")
    _log_in(context, server)
    page.goto(server.base_url + "/settings.html")

    page.wait_for_selector("#configForm")
    assert page.input_value("#running_warning_threshold") == "900"
    assert page.input_value("#pre_draw_warning_threshold") == "300"
    assert page.is_checked("#show_admin_url")
    assert page.is_checked("#dynamic_timer_format")
    # The end counter ships off, with the enlarged-end defaults behind it.
    assert not page.is_checked("#show_end_number")
    assert page.input_value("#end_highlight_percent") == "50"
    assert page.input_value("#end_highlight_scale") == "1.5"
    assert page.input_value("#end_highlight_timer_percent") == "75"
    assert page.is_disabled("#end_highlight_percent")
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
def test_kiosk_end_number_screenshot(kiosk, screenshot):
    page = kiosk(support.END_MID, configure=support.enable_end_counter)
    screenshot(page, "kiosk-end-number")


@pytest.mark.visual
def test_kiosk_end_number_second_half_screenshot(kiosk, screenshot):
    page = kiosk(support.END_SECOND_HALF, configure=support.enable_end_counter)
    screenshot(page, "kiosk-end-second-half")


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


@pytest.mark.visual
def test_settings_end_counter_screenshot(open_page, screenshot):
    # The end-counter card sits below the fold, so scroll it into view and baseline that.
    page, server, context = open_page(
        support.DEFAULT_INSTANT, "/login.html", support.enable_end_counter
    )
    _log_in(context, server)
    page.goto(server.base_url + "/settings.html")
    page.wait_for_selector("#configForm")
    page.locator("#end_highlight_timer_percent").scroll_into_view_if_needed()

    screenshot(page, "settings-end-counter")
