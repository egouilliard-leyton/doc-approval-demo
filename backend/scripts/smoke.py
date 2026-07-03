#!/usr/bin/env python
"""End-to-end offline smoke test for the doc-approval backend.

Exercises the FULL system through the FastAPI ``TestClient`` with NO network: the
mock OCR engine + mock structuring/decision providers, and no API key. Prints a
per-step PASS/FAIL report and exits non-zero on the first failure category.

Run from ``backend/``:

    uv run --no-sync python scripts/smoke.py

Isolation: a throwaway ``DATA_DIR`` is set BEFORE any ``app.*`` import (mirroring
tests/conftest.py) so this never touches the real ``backend/data/``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Must run before importing app.* so app.config.settings picks up the temp dir.
_TMP_DATA = tempfile.mkdtemp(prefix="doc-approval-smoke-")
os.environ["DATA_DIR"] = _TMP_DATA

BACKEND_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = BACKEND_ROOT / "samples"

# Make ``app`` importable when run as a standalone script (cwd-independent).
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# --- tiny reporting harness ---------------------------------------------------

_FAILURES = 0
_PASSES = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global _FAILURES, _PASSES
    mark = "PASS" if ok else "FAIL"
    suffix = f"  -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if ok:
        _PASSES += 1
    else:
        _FAILURES += 1
    return ok


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def _upload(client: TestClient, sample: str, doc_type: str | None = None) -> dict:
    data = {"doc_type": doc_type} if doc_type else None
    with (SAMPLES / sample).open("rb") as fh:
        resp = client.post(
            "/documents", files={"file": (sample, fh)}, data=data
        )
    check(f"upload {sample} -> 201", resp.status_code == 201, resp.text[:200])
    return resp.json()


def run_pipeline(
    client: TestClient, sample: str, doc_type: str
) -> tuple[dict | None, dict | None]:
    """Upload -> prescan -> ocr -> structure -> decide (all mock). Returns
    (structure_json, decide_json) or (None, None) if an early step fails."""
    doc = _upload(client, sample)
    doc_id = doc["id"]

    pre = client.post(f"/documents/{doc_id}/prescan")
    check(f"{doc_type} prescan -> 200", pre.status_code == 200, pre.text[:200])

    ocr = client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
    check(f"{doc_type} ocr(mock) -> 200", ocr.status_code == 200, ocr.text[:200])

    structure = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": doc_type, "provider": "mock", "ocr_engine": "mock"},
    )
    if not check(
        f"{doc_type} structure(mock) -> 200",
        structure.status_code == 200,
        structure.text[:200],
    ):
        return None, None
    sbody = structure.json()

    decide = client.post(f"/documents/{doc_id}/decide", params={"provider": "mock"})
    if not check(
        f"{doc_type} decide(mock) -> 200",
        decide.status_code == 200,
        decide.text[:200],
    ):
        return sbody, None
    return sbody, decide.json()


def assert_valid_decision(prefix: str, decide: dict | None) -> None:
    if decide is None:
        check(f"{prefix} decision present", False, "decide step failed")
        return
    check(
        f"{prefix} decision is valid",
        decide.get("decision") in {"approve", "flag", "needs_review"},
        f"decision={decide.get('decision')}",
    )
    checks = decide.get("checks")
    check(
        f"{prefix} has non-empty checks",
        isinstance(checks, list) and len(checks) > 0,
        f"{len(checks) if isinstance(checks, list) else 'n/a'} checks",
    )
    citations = decide.get("citations")
    check(
        f"{prefix} has non-empty citations",
        isinstance(citations, list) and len(citations) > 0,
        f"{len(citations) if isinstance(citations, list) else 'n/a'} citations",
    )


# --- doc-type bodies ----------------------------------------------------------


def purchase_order_body() -> dict:
    name = "purchase_order"
    return {
        "name": name,
        "label": "Purchase Order",
        "icon": "",
        "extraction_definition": {
            "name": name,
            "fields": [
                {"name": "po_number", "kind": "scalar", "cls": "PoNumber", "coerce": "text"},
                {"name": "total", "kind": "scalar", "cls": "Total", "coerce": "number"},
            ],
            "core_paths": ["total"],
            "prompt": "",
            "examples": [],
        },
        "rule_definition": {
            "name": name,
            "rules": [
                {"kind": "presence", "name": "po_present", "field_path": "po_number", "severity": "review"},
                {
                    "kind": "threshold",
                    "name": "total_cap",
                    "field_path": "total",
                    "op": "lte",
                    "threshold": 10000,
                    "severity": "review",
                },
            ],
            "citation_paths": ["po_number", "total"],
        },
        "citation_paths": ["po_number", "total"],
    }


# --- scenarios ----------------------------------------------------------------


def scenario_invoice(client: TestClient) -> None:
    section("1. Built-in full pipeline (invoice)")
    structure, decide = run_pipeline(client, "invoice-clean.pdf", "invoice")
    if structure is not None:
        fields = structure.get("fields", {})
        total = (fields.get("total") or {}).get("value")
        check("invoice structure total == 1234.56", total == 1234.56, f"total={total}")
        line_items = fields.get("line_items")
        check(
            "invoice structure has non-empty line_items",
            isinstance(line_items, list) and len(line_items) > 0,
            f"{len(line_items) if isinstance(line_items, list) else 'n/a'} items",
        )
    assert_valid_decision("invoice", decide)


def scenario_contract(client: TestClient) -> None:
    section("2. Built-in full pipeline (contract)")
    _, decide = run_pipeline(client, "contract-standard.pdf", "contract")
    assert_valid_decision("contract", decide)


def scenario_custom_crud(client: TestClient) -> None:
    section("3. Custom doc-type CRUD + preview round-trip")

    listing = client.get("/doc-types")
    names = (
        {row["name"] for row in listing.json()} if listing.status_code == 200 else set()
    )
    check(
        "GET /doc-types lists invoice + contract builtins",
        listing.status_code == 200 and {"invoice", "contract"} <= names,
        f"names={sorted(names)}",
    )

    created = client.post("/doc-types", json=purchase_order_body())
    ok_create = check(
        "POST /doc-types purchase_order -> 201",
        created.status_code == 201,
        created.text[:200],
    )
    if ok_create:
        check(
            "created type is custom, version 1",
            created.json().get("builtin") is False and created.json().get("version") == 1,
            f"builtin={created.json().get('builtin')} version={created.json().get('version')}",
        )

    got = client.get("/doc-types/purchase_order")
    check("GET /doc-types/purchase_order -> 200", got.status_code == 200, got.text[:200])

    preview = client.post(
        "/doc-types/purchase_order/preview",
        json={"sample_text": "PO-123\nTotal: $42.00", "provider": "mock"},
    )
    check(
        "POST preview (mock) -> 200",
        preview.status_code == 200,
        preview.text[:200],
    )

    update_body = purchase_order_body()
    del update_body["name"]
    update_body["label"] = "Renamed PO"
    put = client.put("/doc-types/purchase_order", json=update_body)
    check(
        "PUT bumps version to 2",
        put.status_code == 200 and put.json().get("version") == 2,
        f"status={put.status_code} version={put.json().get('version') if put.status_code == 200 else 'n/a'}",
    )

    deleted = client.delete("/doc-types/purchase_order")
    check("DELETE purchase_order -> 204", deleted.status_code == 204, deleted.text[:200])

    gone = client.get("/doc-types/purchase_order")
    check("GET after delete -> 404", gone.status_code == 404, gone.text[:200])


def scenario_guards(client: TestClient) -> None:
    section("4. Guards")

    put_builtin = client.put(
        "/doc-types/invoice",
        json={
            "label": "Invoice",
            "icon": "",
            "extraction_definition": {},
            "rule_definition": {},
            "citation_paths": [],
        },
    )
    check(
        "PUT /doc-types/invoice (builtin) -> 403",
        put_builtin.status_code == 403,
        put_builtin.text[:200],
    )

    bad = purchase_order_body()
    bad["name"] = "purchase_order_bad"
    bad["rule_definition"]["rules"] = [
        {"kind": "presence", "name": "bad_ref", "field_path": "nonexistent", "severity": "review"},
    ]
    bad_resp = client.post("/doc-types", json=bad)
    check(
        "POST rule referencing undeclared field -> 422",
        bad_resp.status_code == 422,
        bad_resp.text[:200],
    )


def scenario_assist_wizard(client: TestClient) -> None:
    """AI doc-type wizard: assist turn, text ingest, annotate start + unknown poll.

    Fully offline: the assistant LLM call is patched to a canned valid envelope and the
    Plannotator subprocess is replaced with a fake Popen, so no network or real process
    is involved.
    """
    import json as _json

    from app import annotate_proc
    from app.config import settings as _settings
    from app.pipeline import doctype_assistant

    section("5. AI doc-type wizard (assist / ingest / annotate)")

    saved_key = _settings.openrouter_api_key
    _settings.openrouter_api_key = "smoke-key"

    canned = _json.dumps(
        {
            "questions": ["What kind of document is this?"],
            "updated_spec_markdown": "# Draft Spec\n",
            "done": False,
            "draft_doctype": None,
        }
    )
    saved_call_llm = doctype_assistant._call_llm
    doctype_assistant._call_llm = lambda messages: canned

    class _FakePopen:
        pid = 9999

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self):
            return (b'{"decision": "approve", "feedback": "ok"}', b"")

        def terminate(self):
            pass

    saved_popen = annotate_proc.subprocess.Popen
    annotate_proc.subprocess.Popen = _FakePopen

    try:
        assist = client.post("/doc-types/assist", json={"messages": []})
        ok_assist = check(
            "POST /doc-types/assist -> 200", assist.status_code == 200, assist.text[:200]
        )
        if ok_assist:
            body = assist.json()
            check(
                "assist response has wizard shape",
                isinstance(body.get("questions"), list)
                and "updated_spec_markdown" in body
                and body.get("done") is False
                and isinstance(body.get("warnings"), list),
                f"keys={sorted(body)}",
            )

        ingest = client.post(
            "/doc-types/assist/ingest",
            files={"file": ("notes.txt", b"hello smoke", "text/plain")},
            data={"kind": "process"},
        )
        ok_ingest = check(
            "POST /doc-types/assist/ingest (.txt) -> 200",
            ingest.status_code == 200,
            ingest.text[:200],
        )
        if ok_ingest:
            check(
                "ingest returns the decoded text",
                ingest.json().get("text") == "hello smoke",
                f"text={ingest.json().get('text')!r}",
            )

        started = client.post(
            "/doc-types/assist/annotate", json={"spec_markdown": "# Spec\n"}
        )
        ok_start = check(
            "POST /doc-types/assist/annotate -> 200",
            started.status_code == 200,
            started.text[:200],
        )
        if ok_start:
            sbody = started.json()
            check(
                "annotate start returns session_id + url",
                bool(sbody.get("session_id")) and str(sbody.get("url")).startswith("http"),
                f"session_id={sbody.get('session_id')} url={sbody.get('url')}",
            )
            client.delete(f"/doc-types/assist/annotate/{sbody.get('session_id')}")

        unknown = client.get("/doc-types/assist/annotate/does-not-exist")
        check(
            "GET annotate/{unknown} -> 404", unknown.status_code == 404, unknown.text[:200]
        )
    finally:
        doctype_assistant._call_llm = saved_call_llm
        annotate_proc.subprocess.Popen = saved_popen
        _settings.openrouter_api_key = saved_key


def scenario_eval(client: TestClient) -> None:
    """Accuracy-evaluation harness: list goldens, run mock/mock, list runs (offline)."""
    section("6. Accuracy-evaluation harness (goldens / run / runs)")

    goldens = client.get("/eval/goldens")
    ok_list = check(
        "GET /eval/goldens -> 200", goldens.status_code == 200, goldens.text[:200]
    )
    if ok_list:
        ids = {g["id"] for g in goldens.json()}
        check(
            "goldens include mock-baseline",
            "mock-baseline" in ids,
            f"ids={sorted(ids)}",
        )

    run = client.post("/eval/run", json={"golden_id": "mock-baseline", "engine": "mock", "provider": "mock"})
    ok_run = check("POST /eval/run (mock/mock) -> 200", run.status_code == 200, run.text[:200])
    if ok_run:
        body = run.json()
        check(
            "mock-baseline scores 1.0",
            body.get("overall_score") == 1.0,
            f"overall_score={body.get('overall_score')}",
        )

    runs = client.get("/eval/runs", params={"golden_id": "mock-baseline"})
    check(
        "GET /eval/runs reflects the run",
        runs.status_code == 200 and len(runs.json()) >= 1,
        f"status={runs.status_code} count={len(runs.json()) if runs.status_code == 200 else 'n/a'}",
    )


def main() -> int:
    print(f"doc-approval smoke test (DATA_DIR={_TMP_DATA})")
    with TestClient(app) as client:
        scenario_invoice(client)
        scenario_contract(client)
        scenario_custom_crud(client)
        scenario_guards(client)
        scenario_assist_wizard(client)
        scenario_eval(client)

    section("Summary")
    total = _PASSES + _FAILURES
    print(f"  {_PASSES}/{total} checks passed, {_FAILURES} failed")
    if _FAILURES:
        print("\nSMOKE TEST FAILED")
        return 1
    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
