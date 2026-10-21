"""Capture golden response fixtures from the original Node server.

Usage (from the repository root, with node_modules installed):

    python -m tests.parity.capture_golden

Writes ``tests/parity/golden/mutation.json`` and ``golden/read-<instant>.json``.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from tests.parity import harness, scenario
from tests.parity.harness import INSTANTS

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def _write(name: str, frozen_now: str, results) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / f"{name}.json"
    path.write_text(
        json.dumps(
            {"scenario": name, "frozen_now": frozen_now, "results": results},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {path.relative_to(Path.cwd())} ({len(results)} steps)")


def main() -> int:
    if not harness.node_available():
        print("node is required to capture golden fixtures", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="hammertime-golden-") as tmp:
        root = Path(tmp)
        template_db = harness.build_template_database(root / "template")

        node = harness.start_node(root / "mutation", template_db, harness.MUTATION_INSTANT)
        try:
            results = scenario.run_mutation_script(node.base_url)
        finally:
            node.stop()
        _write("mutation", harness.MUTATION_INSTANT, results)

        for label, frozen_now in INSTANTS:
            node = harness.start_node(root / label, template_db, frozen_now)
            try:
                results = scenario.run_read_script(node.base_url)
            finally:
                node.stop()
            _write(f"read-{label}", frozen_now, results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
