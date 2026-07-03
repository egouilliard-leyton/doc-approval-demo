"""Admin overview aggregate endpoint (offline: mock engines/providers)."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine as db_engine
from app.main import app
from app.models import (
    Document,
    DocumentStatus,
    EvalRunRow,
    FieldCorrectionRow,
    PipelineRun,
)

from .conftest import SAMPLES


def _dt_row(stats: dict, doc_type: str) -> dict | None:
    for row in stats["by_doc_type"]:
        if row["doc_type"] == doc_type:
            return row
    return None


def _bucket_count(series: dict, date_str: str) -> int | None:
    for b in series["buckets"]:
        if b["date"] == date_str:
            return b["count"]
    return None


def test_overview_aggregates():
    with TestClient(app) as client:
        # Baseline (seeded engines/doc-types exist from lifespan). The shared file DB may
        # already carry rows from earlier test modules, so assert RELATIVE to this baseline.
        base = client.get("/overview").json()
        assert base["engines_enabled"] >= 1
        assert base["doc_types"] >= 1

        # New KPI-extension keys are present and well-shaped on the baseline payload.
        assert set(base["throughput"]) == {"window_days", "buckets"}
        assert base["throughput"]["window_days"] == 30
        assert len(base["throughput"]["buckets"]) == 30
        assert base["maintenance"]["window_days"] == 30
        assert len(base["maintenance"]["buckets"]) == 30
        assert set(base["accuracy"]) == {
            "latest_overall_score",
            "latest_line_item_score",
            "eval_runs_total",
            "doc_types_evaluated",
        }
        assert isinstance(base["doc_types_used"], int)
        assert isinstance(base["by_doc_type"], list)

        base_invoice = _dt_row(base, "invoice")
        base_invoice_docs = base_invoice["documents"] if base_invoice else 0
        base_eval_runs = base["accuracy"]["eval_runs_total"]

        # Ingest + structure one invoice, then correct a field.
        with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
            doc_id = client.post(
                "/documents", files={"file": ("invoice-clean.pdf", fh)}
            ).json()["id"]
        client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
        client.post(
            f"/documents/{doc_id}/structure",
            params={"doc_type": "invoice", "provider": "mock", "ocr_engine": "mock"},
        )
        client.patch(
            f"/documents/{doc_id}/structure/field",
            json={"path": "invoice_no", "value": "INV-1"},
        )

        stats = client.get("/overview").json()
        assert stats["documents_total"] == base["documents_total"] + 1
        assert sum(stats["documents_by_status"].values()) == stats["documents_total"]
        assert stats["corrections_total"] >= 1
        assert stats["corrected_documents"] >= 1
        assert stats["avg_extraction_confidence"] is not None

        # --- KPI extension: internal consistency for the single-invoice flow ---
        # Throughput/maintenance buckets never over-count the totals.
        assert sum(b["count"] for b in stats["throughput"]["buckets"]) <= stats["documents_total"]
        assert (
            sum(b["count"] for b in stats["maintenance"]["buckets"])
            <= stats["corrections_total"]
        )
        # The new invoice document shows up in its doc-type slice (one more than baseline).
        invoice = _dt_row(stats, "invoice")
        assert invoice is not None
        assert invoice["documents"] == base_invoice_docs + 1
        assert 0.0 <= invoice["pct_of_total"] <= 1.0
        assert invoice["avg_extraction_confidence"] is not None
        assert invoice["corrections_total"] >= 1
        assert invoice["corrected_documents"] >= 1
        # doc_types_used counts the invoice (unclassified is never counted).
        assert stats["doc_types_used"] >= 1
        # This flow scores no evaluation run -> the accuracy rollup is unchanged.
        assert stats["accuracy"]["eval_runs_total"] == base_eval_runs


def test_overview_time_series_and_accuracy_with_seeded_history():
    """Seed dated Documents/corrections + one EvalRunRow directly, then assert the
    30-day windowing, per-doc-type grouping (incl. an unclassified doc), and the
    accuracy rollup. Mirrors test_ocr.py's direct-Session seeding + finally-cleanup."""
    now = datetime.now(timezone.utc)
    today = now.date()
    d_today = now
    d_5 = now - timedelta(days=5)
    d_40 = now - timedelta(days=40)
    today_5_str = (today - timedelta(days=5)).isoformat()
    today_40_str = (today - timedelta(days=40)).isoformat()

    dt = "kpi_alpha"  # unique label -> isolated from any accumulated invoice/contract docs
    doc_ids: list[str] = []
    run_ids: list[str] = []
    corr_ids: list[str] = []
    eval_row_id = ""

    def _make_doc(created_at: datetime, doc_type: str | None) -> Document:
        return Document(
            filename="seed.pdf",
            mime="application/pdf",
            doc_type=doc_type,
            status=DocumentStatus.structured,
            created_at=created_at,
        )

    def _make_run(doc_id: str, conf: float, decision: str | None) -> PipelineRun:
        stage: dict = {"structure": {"doc_type": dt, "extraction_confidence": conf}}
        if decision is not None:
            stage["decide"] = {"decision": decision}
        return PipelineRun(document_id=doc_id, status="done", stage_results=stage)

    try:
        with Session(db_engine) as session:
            # Three kpi_alpha docs: today / today-5 / today-40 (last is out of window).
            doc1 = _make_doc(d_today, dt)
            doc2 = _make_doc(d_5, dt)
            doc3 = _make_doc(d_40, dt)
            # One unclassified doc: doc_type=None AND no structure run.
            doc4 = _make_doc(d_today, None)
            docs = [doc1, doc2, doc3, doc4]
            for d in docs:
                session.add(d)
            session.commit()
            for d in docs:
                session.refresh(d)
            doc_ids = [d.id for d in docs]

            runs = [
                _make_run(doc1.id, 0.8, "approve"),
                _make_run(doc2.id, 0.6, "flag"),
                _make_run(doc3.id, 0.7, None),
            ]
            for r in runs:
                session.add(r)

            corrections = [
                FieldCorrectionRow(
                    document_id=doc2.id, doc_type=dt, field_path="total",
                    original_value="1", new_value="2", created_at=d_5,
                ),
                FieldCorrectionRow(
                    document_id=doc3.id, doc_type=dt, field_path="total",
                    original_value="3", new_value="4", created_at=d_40,
                ),
            ]
            for c in corrections:
                session.add(c)

            # Latest eval row globally (runs last in wall-clock -> newest created_at).
            eval_row = EvalRunRow(
                golden_id="kpi-golden",
                doc_type=dt,
                engine="mock",
                overall_score=0.85,
                collection_scores={
                    "line_items": {"line_item_score": 0.4},
                    "taxes": {"line_item_score": 0.9},
                },
                created_at=now,
            )
            session.add(eval_row)
            session.commit()
            run_ids = [r.id for r in runs]
            corr_ids = [c.id for c in corrections]
            eval_row_id = eval_row.id

        with TestClient(app) as client:
            stats = client.get("/overview").json()

        # --- Time-series windowing ---
        # today-5: exactly one seeded document / one seeded correction fall on that day.
        assert _bucket_count(stats["throughput"], today_5_str) == 1
        assert _bucket_count(stats["maintenance"], today_5_str) == 1
        # today-40 is outside the 30-day window: the day is absent entirely.
        assert _bucket_count(stats["throughput"], today_40_str) is None
        assert _bucket_count(stats["maintenance"], today_40_str) is None

        # --- Accuracy rollup (seeded row is the global latest) ---
        acc = stats["accuracy"]
        assert acc["latest_overall_score"] == 0.85
        assert acc["latest_line_item_score"] == 0.9  # max line_item across collections
        assert acc["eval_runs_total"] >= 1
        assert dt in {r["doc_type"] for r in stats["by_doc_type"] if r["eval_runs"] > 0}

        # --- Per-doc-type grouping ---
        alpha = _dt_row(stats, dt)
        assert alpha is not None
        assert alpha["documents"] == 3  # doc1/doc2/doc3 (out-of-window doc still counts)
        assert alpha["decisions"] == {"approve": 1, "flag": 1}
        assert alpha["avg_extraction_confidence"] == 0.7  # mean of 0.8/0.6/0.7
        assert alpha["corrections_total"] == 2
        assert alpha["corrected_documents"] == 2
        assert alpha["latest_accuracy"] == 0.85
        assert alpha["latest_accuracy_engine"] == "mock"
        assert alpha["latest_line_item_score"] == 0.9
        assert alpha["eval_runs"] == 1

        # The doc_type=None / no-structure doc lands in the unclassified group only.
        unclassified = _dt_row(stats, "unclassified")
        assert unclassified is not None
        assert unclassified["documents"] >= 1
    finally:
        # Remove everything this test seeded so later tests see a clean shared DB.
        with Session(db_engine) as session:
            for model, ids in (
                (EvalRunRow, [eval_row_id] if eval_row_id else []),
                (FieldCorrectionRow, corr_ids),
                (PipelineRun, run_ids),
                (Document, doc_ids),
            ):
                for row_id in ids:
                    row = session.get(model, row_id)
                    if row is not None:
                        session.delete(row)
            session.commit()
