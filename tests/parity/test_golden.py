"""Golden-response tests.

The fixtures in ``golden/`` were captured from the original Node server (see
``capture_golden.py``). They keep guarding the Python port after the JavaScript
implementation is deleted, without requiring Node to be installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.parity import harness, scenario
from tests.parity.harness import INSTANTS

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def _load_golden(name: str):
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        pytest.skip(f"golden fixture {path.name} not captured yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _label_for(frozen_now: str) -> str:
    for label, value in INSTANTS:
        if value == frozen_now:
            return label
    raise AssertionError(f"unknown instant {frozen_now}")


def test_mutation_golden(start_python):
    golden = _load_golden("mutation")
    python = start_python(golden["frozen_now"])
    actual = scenario.run_mutation_script(python.base_url)
    diff = scenario.compare_results(golden["results"], actual)
    assert diff is None, f"{diff}\n--- python log ---\n{python.log()}"


def test_read_golden(start_python, frozen_now):
    golden = _load_golden(f"read-{_label_for(frozen_now)}")
    python = start_python(golden["frozen_now"])
    actual = scenario.run_read_script(python.base_url)
    diff = scenario.compare_results(golden["results"], actual)
    assert diff is None, f"{diff}\n--- python log ---\n{python.log()}"
