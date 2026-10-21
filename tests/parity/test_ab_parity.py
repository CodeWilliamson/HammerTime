"""A/B parity: identical requests must produce identical responses from both servers.

These tests need the original Node server to be runnable (`node_modules` installed).
They are the reference used to generate `golden/`, which then keeps guarding the port
after the JavaScript implementation is removed.
"""

from __future__ import annotations

import pytest

from tests.parity import harness, scenario
from tests.parity.harness import INSTANTS

pytestmark = pytest.mark.skipif(
    not harness.node_available(), reason="original Node server is not available"
)


def _assert_parity(node, python, expected, actual) -> None:
    diff = scenario.compare_results(expected, actual)
    assert diff is None, (
        f"{diff}\n--- node log ---\n{node.log()}\n--- python log ---\n{python.log()}"
    )


def test_read_only_parity(servers, frozen_now):
    node, python = servers(frozen_now)
    expected = scenario.run_read_script(node.base_url)
    actual = scenario.run_read_script(python.base_url)
    _assert_parity(node, python, expected, actual)


def test_mutation_parity(servers):
    node, python = servers(harness.MUTATION_INSTANT)
    expected = scenario.run_mutation_script(node.base_url)
    actual = scenario.run_mutation_script(python.base_url)
    _assert_parity(node, python, expected, actual)
