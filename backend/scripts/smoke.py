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


def scenario_extract(client: TestClient) -> None:
    """Black-box /extract + /extract/batch: whole pipeline in one call, isolated failures."""
    section("7. Black-box extraction endpoint (/extract + /extract/batch)")

    with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
        resp = client.post(
            "/extract",
            files={"file": ("invoice-clean.pdf", fh, "application/pdf")},
            data={
                "doc_type": "invoice",
                "ocr_engine": "mock",
                "structuring_provider": "mock",
                "decision_provider": "mock",
            },
        )
    if check("POST /extract (invoice, mock) -> 200", resp.status_code == 200, resp.text[:200]):
        body = resp.json()
        check(
            "extract response has document_id + doc_type==invoice",
            bool(body.get("document_id")) and body.get("doc_type") == "invoice",
            f"document_id={body.get('document_id')} doc_type={body.get('doc_type')}",
        )
        structured = body.get("structured") or {}
        fields = structured.get("fields")
        check(
            "extract structured.fields is a non-empty dict",
            isinstance(fields, dict) and len(fields) > 0,
            f"{len(fields) if isinstance(fields, dict) else 'n/a'} fields",
        )
        decision = (body.get("decision") or {}).get("decision")
        check(
            "extract decision is valid",
            decision in {"approve", "flag", "needs_review"},
            f"decision={decision}",
        )

    # Batch: a single empty/bad file must fail in isolation, still HTTP 200.
    batch = client.post(
        "/extract/batch",
        files=[("files", ("empty.pdf", b"", "application/pdf"))],
        data={
            "doc_type": "invoice",
            "ocr_engine": "mock",
            "structuring_provider": "mock",
            "decision_provider": "mock",
        },
    )
    if check("POST /extract/batch (bad file) -> 200", batch.status_code == 200, batch.text[:200]):
        bbody = batch.json()
        check(
            "batch reports >=1 failure",
            bbody.get("failed", 0) >= 1,
            f"succeeded={bbody.get('succeeded')} failed={bbody.get('failed')}",
        )
        items = bbody.get("items") or []
        bad = items[0] if items else {}
        check(
            "batch bad item has error + error_status populated",
            bool(bad.get("error")) and bad.get("error_status") is not None,
            f"error={bad.get('error')!r} error_status={bad.get('error_status')}",
        )


def scenario_review_queue(client: TestClient) -> None:
    """Per-field review queue: at-risk fields, worst-first, PATCH round-trip, edited-excluded."""
    section("8. Review queue (per-field risk) + PATCH round-trip")

    doc = _upload(client, "invoice-clean.pdf")
    doc_id = doc["id"]
    client.post(f"/documents/{doc_id}/prescan")
    client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
    structure = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": "invoice", "provider": "mock", "ocr_engine": "mock"},
    )
    if not check(
        "review-queue setup: structure(mock) -> 200",
        structure.status_code == 200,
        structure.text[:200],
    ):
        return

    rq = client.get("/review-queue")
    if not check("GET /review-queue -> 200", rq.status_code == 200, rq.text[:200]):
        return
    entry = next(
        (d for d in rq.json().get("documents", []) if d["document_id"] == doc_id), None
    )
    if not check("review-queue has an entry for the doc", entry is not None, f"doc_id={doc_id}"):
        return

    fields = entry.get("fields") or []
    confidences = [f["confidence"] for f in fields]
    check(
        "entry has >=1 at-risk field, sorted by confidence ascending",
        len(fields) >= 1 and confidences == sorted(confidences),
        f"confidences={confidences}",
    )

    # Every returned field path must be a valid PATCH target.
    all_patched = True
    for f in fields:
        patch = client.patch(
            f"/documents/{doc_id}/structure/field",
            json={"path": f["path"], "value": f.get("value")},
        )
        if patch.status_code != 200:
            all_patched = False
            check(f"PATCH field '{f['path']}' -> 200", False, patch.text[:200])
    check(
        "all review-queue field paths are valid PATCH targets",
        all_patched,
        f"{len(fields)} fields",
    )

    # The corrected field must drop out of the queue (edited excluded).
    corrected_path = fields[0]["path"] if fields else None
    rq2 = client.get("/review-queue")
    entry2 = next(
        (d for d in rq2.json().get("documents", []) if d["document_id"] == doc_id), None
    )
    still_at_risk = {f["path"] for f in (entry2.get("fields") if entry2 else [])}
    check(
        "corrected field no longer at-risk (edited excluded)",
        corrected_path is not None and corrected_path not in still_at_risk,
        f"corrected={corrected_path} still_at_risk={sorted(still_at_risk)}",
    )


def scenario_corrections_export(client: TestClient) -> None:
    """JSONL label export of the correction log, in raw + grouped (examples) shapes."""
    import json as _json

    section("9. Corrections export (JSONL label export)")

    # Self-contained: guarantee at least one logged correction.
    doc = _upload(client, "invoice-clean.pdf")
    doc_id = doc["id"]
    client.post(f"/documents/{doc_id}/prescan")
    client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
    client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": "invoice", "provider": "mock", "ocr_engine": "mock"},
    )
    made = client.patch(
        f"/documents/{doc_id}/structure/field", json={"path": "total", "value": 4321.0}
    )
    check("seed a correction: PATCH total -> 200", made.status_code == 200, made.text[:200])

    raw = client.get("/corrections/export", params={"shape": "raw"})
    if check(
        "GET /corrections/export?shape=raw -> 200", raw.status_code == 200, raw.text[:200]
    ):
        check(
            "raw export content-type is ndjson",
            "ndjson" in raw.headers.get("content-type", ""),
            raw.headers.get("content-type", ""),
        )
        lines = [ln for ln in raw.text.splitlines() if ln.strip()]
        if check("raw export has >=1 line", len(lines) >= 1, f"{len(lines)} lines"):
            check(
                "every raw line is JSON with a field_path key",
                all("field_path" in _json.loads(ln) for ln in lines),
                f"{len(lines)} lines",
            )

    ex = client.get("/corrections/export", params={"shape": "examples"})
    if check(
        "GET /corrections/export?shape=examples -> 200", ex.status_code == 200, ex.text[:200]
    ):
        lines = [ln for ln in ex.text.splitlines() if ln.strip()]
        if check("examples export has >=1 line", len(lines) >= 1, f"{len(lines)} lines"):
            check(
                "every examples line is JSON with a fields object",
                all(isinstance(_json.loads(ln).get("fields"), dict) for ln in lines),
                f"{len(lines)} lines",
            )


def scenario_routing(client: TestClient) -> None:
    """Engine routing (built-in patchable) + external adapter degrading cleanly."""
    section("10. Engine routing + external adapter (Phase 5 + Phase 7)")

    try:
        patch = client.patch(
            "/doc-types/invoice/routing",
            json={"preferred_ocr_engine": "mock", "ocr_fallback_engines": []},
        )
        if check(
            "PATCH /doc-types/invoice/routing (builtin) -> 200",
            patch.status_code == 200,
            patch.text[:200],
        ):
            check(
                "routing patch echoes preferred_ocr_engine==mock",
                patch.json().get("preferred_ocr_engine") == "mock",
                f"preferred={patch.json().get('preferred_ocr_engine')}",
            )

        # No explicit ocr_engine -> routing resolves the doc type's preferred (mock).
        with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
            routed = client.post(
                "/extract",
                files={"file": ("invoice-clean.pdf", fh, "application/pdf")},
                data={
                    "doc_type": "invoice",
                    "structuring_provider": "mock",
                    "decision_provider": "mock",
                },
            )
        if check(
            "POST /extract (no ocr_engine, routed) -> 200",
            routed.status_code == 200,
            routed.text[:200],
        ):
            engine = (routed.json().get("structured") or {}).get("ocr_engine")
            check(
                "routing engaged: structured.ocr_engine==mock",
                engine == "mock",
                f"ocr_engine={engine}",
            )

        # Unconfigured external adapter degrades cleanly to a 400 (no crash).
        with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
            bad = client.post(
                "/extract",
                files={"file": ("invoice-clean.pdf", fh, "application/pdf")},
                data={
                    "doc_type": "invoice",
                    "ocr_engine": "digibot",
                    "structuring_provider": "mock",
                    "decision_provider": "mock",
                },
            )
        if check(
            "POST /extract (ocr_engine=digibot, unconfigured) -> 400",
            bad.status_code == 400,
            bad.text[:200],
        ):
            check(
                "digibot 400 detail mentions 'not configured'",
                "not configured" in bad.text,
                bad.text[:200],
            )
    finally:
        # Restore invoice routing so later scenarios / repeat runs are unaffected.
        client.patch(
            "/doc-types/invoice/routing",
            json={"preferred_ocr_engine": None, "ocr_fallback_engines": []},
        )


def scenario_kpi(client: TestClient) -> None:
    """KPI dashboard rollups on /overview: accuracy, 30-day series, per-doc-type slices."""
    section("11. KPI dashboard (/overview)")

    ov = client.get("/overview")
    if not check("GET /overview -> 200", ov.status_code == 200, ov.text[:200]):
        return
    body = ov.json()

    check(
        "overview has KPI fields",
        all(
            k in body
            for k in ("accuracy", "throughput", "maintenance", "by_doc_type", "doc_types_used")
        ),
        f"keys={sorted(body)}",
    )

    tp = body.get("throughput") or {}
    check(
        "throughput is a zero-filled 30-day series",
        tp.get("window_days") == 30 and len(tp.get("buckets") or []) == 30,
        f"window_days={tp.get('window_days')} buckets={len(tp.get('buckets') or [])}",
    )
    mt = body.get("maintenance") or {}
    check(
        "maintenance is a zero-filled 30-day series",
        mt.get("window_days") == 30 and len(mt.get("buckets") or []) == 30,
        f"window_days={mt.get('window_days')} buckets={len(mt.get('buckets') or [])}",
    )

    by_doc_type = body.get("by_doc_type")
    invoice_kpi = (
        next((k for k in by_doc_type if k.get("doc_type") == "invoice"), None)
        if isinstance(by_doc_type, list)
        else None
    )
    check(
        "by_doc_type is a list with an invoice entry (documents>=1)",
        invoice_kpi is not None and invoice_kpi.get("documents", 0) >= 1,
        f"invoice_documents={invoice_kpi.get('documents') if invoice_kpi else 'n/a'}",
    )

    accuracy = body.get("accuracy") or {}
    check(
        "overview accuracy has eval_runs_total",
        "eval_runs_total" in accuracy,
        f"accuracy keys={sorted(accuracy)}",
    )
    if accuracy.get("eval_runs_total", 0) > 0:
        check(
            "accuracy populated: latest_overall_score is not None",
            accuracy.get("latest_overall_score") is not None,
            f"eval_runs_total={accuracy.get('eval_runs_total')} "
            f"latest_overall_score={accuracy.get('latest_overall_score')}",
        )


def scenario_signing(client: TestClient) -> None:
    """Digital signing, both paths, all offline via the mock provider.

    Inbound: run a doc to APPROVE, sign its original PDF, validate, then re-decide
    and confirm the seal is invalidated (GET /sign -> 404).
    Outbound: generate a template PDF and seal it, confirming the signed variant is
    fetchable through /files.
    """
    from uuid import uuid4

    from sqlmodel import Session, select

    from app import storage
    from app.db import engine as _engine
    from app.models import PipelineRun, _new_id

    section("12. Digital signing (inbound seal + outbound generated-output)")

    # --- Inbound: sign an approved document's original PDF --------------------
    doc = _upload(client, "invoice-clean.pdf")
    doc_id = doc["id"]
    client.post(f"/documents/{doc_id}/prescan")
    client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
    structure = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": "invoice", "provider": "mock", "ocr_engine": "mock"},
    )
    if not check(
        "signing setup: structure(mock) -> 200",
        structure.status_code == 200,
        structure.text[:200],
    ):
        return

    # The mock structurer emits a constant invoice_no; make it unique so the doc
    # approves (a duplicate would flag) — mirrors test_signing._uniquify_invoice_no.
    with Session(_engine) as session:
        run = session.exec(
            select(PipelineRun)
            .where(PipelineRun.document_id == doc_id)
            .order_by(PipelineRun.created_at.desc())
        ).first()
        structure_res = dict(run.stage_results["structure"])
        fields = dict(structure_res["fields"])
        node = dict(fields["invoice_no"])
        node["value"] = f"INV-{uuid4()}"
        fields["invoice_no"] = node
        structure_res["fields"] = fields
        run.stage_results = {**run.stage_results, "structure": structure_res}
        session.add(run)
        session.commit()

    decide = client.post(f"/documents/{doc_id}/decide", params={"provider": "mock"})
    check(
        "inbound decide(mock) -> approve",
        decide.status_code == 200 and decide.json().get("decision") == "approve",
        f"status={decide.status_code} decision={decide.json().get('decision') if decide.status_code == 200 else 'n/a'}",
    )

    sign = client.post(f"/documents/{doc_id}/sign", params={"provider": "mock"})
    if check("POST /documents/{id}/sign(mock) -> 200", sign.status_code == 200, sign.text[:200]):
        sbody = sign.json()
        check(
            "inbound sign: status signed + validation.valid",
            sbody.get("status") == "signed" and sbody.get("validation", {}).get("valid") is True,
            f"status={sbody.get('status')} valid={sbody.get('validation', {}).get('valid')}",
        )

    validate = client.post(
        f"/documents/{doc_id}/validate-signature", params={"provider": "mock"}
    )
    check(
        "POST /documents/{id}/validate-signature(mock) -> valid",
        validate.status_code == 200 and validate.json().get("valid") is True,
        f"status={validate.status_code} valid={validate.json().get('valid') if validate.status_code == 200 else 'n/a'}",
    )

    # Re-deciding a signed doc must invalidate the seal (GET /sign -> 404).
    client.post(f"/documents/{doc_id}/decide", params={"provider": "mock"})
    gone = client.get(f"/documents/{doc_id}/sign")
    check(
        "re-decide invalidates seal: GET /sign -> 404",
        gone.status_code == 404,
        f"status={gone.status_code}",
    )

    # --- Outbound: sign a generated template output PDF ----------------------
    tid = client.post(
        "/templates", json={"name": "Smoke Signable", "doc_type": "invoice"}
    ).json()["id"]
    html = '<p>Invoice for <span data-field="vendor" data-field-kind="text">Vendor</span></p>'
    client.put(f"/templates/{tid}", json={"html_body": html, "output_formats": ["pdf"]})

    stash_id = _new_id()
    with Session(_engine) as session:
        session.add(
            PipelineRun(
                document_id=stash_id,
                status="structured",
                stage_results={
                    "structure": {
                        "fields": {
                            "vendor": {"value": "MOCK INVOICE", "confidence": 0.9, "grounding": None}
                        }
                    }
                },
            )
        )
        session.commit()

    gen = client.post(f"/templates/{tid}/generate", params={"document_id": stash_id})
    if not check(
        "outbound generate PDF -> 201", gen.status_code == 201, gen.text[:200]
    ):
        return
    oid = gen.json()["output_id"]

    osign = client.post(
        f"/templates/{tid}/outputs/{oid}/sign", params={"provider": "mock"}
    )
    if check(
        "POST /templates/{tid}/outputs/{oid}/sign(mock) -> 201",
        osign.status_code == 201,
        osign.text[:200],
    ):
        check(
            "outbound sign: validation.valid",
            osign.json().get("validation", {}).get("valid") is True,
            f"valid={osign.json().get('validation', {}).get('valid')}",
        )

    fetched = client.get(f"/files/templates/{tid}/outputs/{oid}-signed.pdf")
    check(
        "signed output fetchable via /files -> 200 (%PDF)",
        fetched.status_code == 200 and fetched.content[:4] == b"%PDF",
        f"status={fetched.status_code}",
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
        scenario_extract(client)
        scenario_review_queue(client)
        scenario_corrections_export(client)
        scenario_routing(client)
        scenario_kpi(client)
        scenario_signing(client)

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
