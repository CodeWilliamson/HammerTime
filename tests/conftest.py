"""Shared fixtures: sandbox database, real server process, in-process data layer."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Callable, Iterator

import httpx
import pytest

from tests import support

# Pin the timezone before anything imports ``hammertime``: its clock is naive local time,
# so the frozen instants must mean the same thing to the in-process tests, the sandbox
# servers (which inherit TZ) and the browser (which is given TEST_TIMEZONE).
os.environ["TZ"] = support.TEST_TIMEZONE
time.tzset()


def pytest_addoption(parser):
    # Registered here (not in tests/visual/conftest.py) so the option is known during
    # the initial argument parse, before the visual conftest is loaded.
    parser.addoption(
        "--update-baselines",
        action="store_true",
        default=False,
        help="Rewrite the visual screenshot baselines instead of comparing",
    )


@pytest.fixture(scope="session")
def template_db(tmp_path_factory) -> Path:
    """A migrated + seeded database, built once per test session."""
    return support.build_template_database(tmp_path_factory.mktemp("hammertime-template"))


@pytest.fixture
def server_factory(template_db: Path, tmp_path: Path) -> Iterator[Callable[..., support.Server]]:
    """Start servers against sandbox databases; all are stopped at teardown."""
    started: list[support.Server] = []

    def _start(frozen_now: str = support.DEFAULT_INSTANT) -> support.Server:
        root = tmp_path / f"server-{len(started) + 1}"
        server = support.start_server(root, template_db, frozen_now)
        started.append(server)
        return server

    try:
        yield _start
    finally:
        for server in reversed(started):
            server.stop()


@pytest.fixture
def server(server_factory) -> support.Server:
    return server_factory()


@pytest.fixture
def client(server) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=server.base_url, timeout=15) as http_client:
        yield http_client


@pytest.fixture
def auth_client(client) -> httpx.Client:
    """A client holding the session cookie of the seeded ``timer`` user."""
    response = client.post("/auth/login", json={"username": "timer", "password": "timer"})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def freeze(monkeypatch) -> Callable[[str], None]:
    """Pin the clock of the in-process data layer to a frozen instant."""

    def _freeze(instant: str) -> None:
        monkeypatch.setenv("HAMMERTIME_FAKE_NOW", instant)

    return _freeze


@pytest.fixture
def db(template_db: Path, tmp_path: Path, freeze) -> Iterator[object]:
    """The ``hammertime.db`` module, pointed at a sandbox database.

    ``_conn`` is module-level state (the real app opens ``data/schedule.db`` at import),
    so tests swap it out for a connection to their own copy and restore it afterwards.
    """
    from hammertime import db as db_module

    freeze(support.DEFAULT_INSTANT)
    sandbox = tmp_path / "in-process"
    (sandbox / "data").mkdir(parents=True)
    db_file = sandbox / "data" / "schedule.db"
    shutil.copyfile(template_db, db_file)

    connection = support.connect(db_file)
    original = db_module._conn
    db_module._conn = connection
    try:
        yield db_module
    finally:
        db_module._conn = original
        connection.close()
