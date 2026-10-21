"""Shared fixtures for the parity suite."""

from __future__ import annotations

from typing import Callable, Tuple

import pytest

from tests.parity import harness


@pytest.fixture(scope="session")
def template_db(tmp_path_factory) -> object:
    """A migrated + seeded database, built once per test session."""
    workdir = tmp_path_factory.mktemp("hammertime-template")
    return harness.build_template_database(workdir)


@pytest.fixture
def servers(template_db, tmp_path) -> Callable[[str], Tuple[harness.Server, harness.Server]]:
    """Start a Node + Python pair frozen at the same instant; stop both afterwards."""
    started = []

    def _start(frozen_now: str) -> Tuple[harness.Server, harness.Server]:
        node = harness.start_node(tmp_path / "node", template_db, frozen_now)
        started.append(node)
        python = harness.start_python(tmp_path / "python", template_db, frozen_now)
        started.append(python)
        return node, python

    try:
        yield _start
    finally:
        for server in reversed(started):
            server.stop()


@pytest.fixture
def start_python(template_db, tmp_path) -> Callable[[str], harness.Server]:
    """Start only the Python server (used by the golden tests)."""
    started = []

    def _start(frozen_now: str) -> harness.Server:
        server = harness.start_python(tmp_path / "python", template_db, frozen_now)
        started.append(server)
        return server

    try:
        yield _start
    finally:
        for server in reversed(started):
            server.stop()


def pytest_generate_tests(metafunc):
    """Give parametrised scenarios readable ids without repeating the label list."""
    instants = getattr(metafunc.module, "INSTANTS", None)
    if instants and "frozen_now" in metafunc.fixturenames:
        metafunc.parametrize(
            "frozen_now", [value for _, value in instants], ids=[key for key, _ in instants]
        )
