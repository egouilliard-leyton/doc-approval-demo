"""Golden fixtures for the accuracy-evaluation harness.

A golden case pins the *expected* extraction for one sample file: the scalar/composite
fields (``expected_fields``) plus the collection fields (``expected_collections``,
e.g. an invoice's ``line_items`` or a contract's ``parties``). The scorer compares a
real structuring result against these, so a golden is intentionally provider-agnostic
plain data. Fixtures live as JSON under ``backend/golden/`` (a sibling of ``samples/``);
the ``mock-baseline`` golden pins the deterministic offline mock output so the harness
scores meaningfully with no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.config import BACKEND_ROOT

GOLDEN_DIR = BACKEND_ROOT / "golden"


@dataclass
class GoldenCase:
    """One expected-extraction fixture, loaded from a ``golden/<id>.json`` file."""

    id: str
    sample_file: str
    doc_type: str
    expected_fields: dict
    expected_collections: dict


def _load_case(path) -> GoldenCase:
    data = json.loads(path.read_text(encoding="utf-8"))
    return GoldenCase(
        id=data["id"],
        sample_file=data["sample_file"],
        doc_type=data["doc_type"],
        expected_fields=data.get("expected_fields") or {},
        expected_collections=data.get("expected_collections") or {},
    )


def load_goldens() -> list[GoldenCase]:
    """Every golden fixture under ``backend/golden/``, sorted by id."""
    if not GOLDEN_DIR.is_dir():
        return []
    cases = [_load_case(p) for p in GOLDEN_DIR.glob("*.json")]
    return sorted(cases, key=lambda c: c.id)


def get_golden(golden_id: str) -> GoldenCase:
    """Return the golden with ``golden_id``; raise ``KeyError`` if there is none."""
    for case in load_goldens():
        if case.id == golden_id:
            return case
    raise KeyError(golden_id)
