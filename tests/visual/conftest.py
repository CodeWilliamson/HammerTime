"""Fixtures for the browser tests.

The kiosk is the product, so it is tested in a real browser (Chromium via Playwright).
Time is pinned in both places at once:

* the server runs with ``HAMMERTIME_FAKE_NOW`` set to the scenario instant;
* the browser gets Playwright's fake clock (``page.clock``) at the same instant.

Without the second half the kiosk's own ``tick()`` would compute the countdown from the
real clock and render nonsense next to the server's frozen state.

Screenshot baselines are opt-in::

    pytest -m visual                     # compare against tests/visual/baselines/
    pytest -m visual --update-baselines  # rewrite the baselines (review the diff!)

Baselines are tied to the machine that produced them (fonts, DPR, Chromium version),
so they are not part of the default run.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed")

from PIL import Image, ImageChops  # noqa: E402  (after importorskip)
from playwright.sync_api import sync_playwright  # noqa: E402

from tests import support  # noqa: E402

BASELINES = Path(__file__).resolve().parent / "baselines"

VIEWPORT = {"width": 1280, "height": 800}

#: Per-channel difference below this is treated as identical (font antialiasing).
PIXEL_TOLERANCE = 12
#: Number of differing pixels tolerated before a screenshot fails (~0.1% of the viewport).
MAX_DIFF_PIXELS = 1000


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        try:
            yield chromium
        finally:
            chromium.close()


@pytest.fixture
def open_page(browser, server_factory):
    """Factory: start a server frozen at ``instant`` and open ``path`` in a new page."""
    contexts = []

    def _open(instant: str = support.DEFAULT_INSTANT, path: str = "/"):
        server = server_factory(instant)
        context = browser.new_context(
            viewport=VIEWPORT,
            locale="en-US",
            timezone_id=support.TEST_TIMEZONE,
        )
        page = context.new_page()
        # Both calls must happen before the page's own scripts run. `install` fakes the
        # timer functions; `pause_at` freezes the clock exactly at the instant (install
        # alone would let it drift, and the countdown would land a second out).
        page.clock.install(time=instant)
        page.clock.pause_at(instant)
        page.goto(server.base_url + path)
        contexts.append(context)
        return page, server, context

    try:
        yield _open
    finally:
        for context in reversed(contexts):
            context.close()


@pytest.fixture
def kiosk(open_page):
    """Open the display page and wait until the first timer snapshot is rendered."""

    def _kiosk(instant: str = support.DEFAULT_INSTANT):
        page, server, _context = open_page(instant, "/")
        page.wait_for_function(
            "document.getElementById('label').textContent !== 'Loading...'"
        )
        return page

    return _kiosk


@pytest.fixture
def screenshot(request, tmp_path):
    """Compare (or, with ``--update-baselines``, write) a page screenshot."""

    def _check(page, name: str) -> None:
        path = BASELINES / f"{name}.png"
        # The kiosk footer shows the host's LAN IP; mask it so baselines are portable.
        mask = [page.locator("#ip-display")] if page.locator("#ip-display").count() else []
        actual = page.screenshot(animations="disabled", mask=mask, mask_color="#808080")

        if request.config.getoption("--update-baselines") or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(actual)
            return

        differing = _diff_pixels(path.read_bytes(), actual)
        if differing > MAX_DIFF_PIXELS:
            (tmp_path / f"{name}.actual.png").write_bytes(actual)
            pytest.fail(
                f"{name} differs from its baseline in {differing} pixels "
                f"(allowed: {MAX_DIFF_PIXELS}).\n"
                f"Expected: {path}\nActual:   {tmp_path / f'{name}.actual.png'}\n"
                "If the change is intended, regenerate with --update-baselines."
            )

    return _check


def _diff_pixels(expected_png: bytes, actual_png: bytes) -> int:
    expected = Image.open(io.BytesIO(expected_png)).convert("RGB")
    actual = Image.open(io.BytesIO(actual_png)).convert("RGB")
    if expected.size != actual.size:
        return expected.size[0] * expected.size[1]

    difference = ImageChops.difference(expected, actual).convert("L")
    significant = difference.point(lambda value: 255 if value > PIXEL_TOLERANCE else 0)
    # `histogram()[255]` is the number of pixels above the tolerance (C-level counting).
    return significant.histogram()[255]
