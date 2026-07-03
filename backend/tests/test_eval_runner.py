"""Runner + persistence tests for the evaluation harness (offline: mock engine/provider).

Mirrors tests/test_structuring.py's fixture use: a real Document is taken through the
pipeline via the mock engine + mock provider (no network), then scored. The
``mock-baseline`` golden pins exactly the mock's fixed output, so it scores 1.0
deterministically across repeated runs.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine as db_engine, init_db
from app.evaluation.golden import get_golden
from app.evaluation.runner import run_and_score, score_existing
from app.main import app
from app.models import Document, EvalRunRow, PipelineRun

from .conftest import SAMPLES

# Ensure tables (including the new EvalRunRow) exist for the direct-Session tests that
# don't go through the app lifespan.
init_db()


def test_run_and_score_mock_baseline_is_deterministic_and_persists():
    golden = get_golden("mock-baseline")
    with Session(db_engine) as session:
        # Count preexisting rows: other test modules share this temp DB and may have
        # already scored mock-baseline, so assert on the delta, not an absolute count.
        before = len(
            session.exec(
                select(EvalRunRow).where(EvalRunRow.golden_id == "mock-baseline")
            ).all()
        )
        first = run_and_score(session, golden, engine="mock", provider="mock")
        second = run_and_score(session, golden, engine="mock", provider="mock")

        # The mock output equals the golden exactly -> perfect, and stable across runs.
        assert first.overall_score == 1.0
        assert first.field_accuracy_exact == 1.0
        assert first.overall_score == second.overall_score
        assert first.collection_scores["line_items"].line_item_score == 1.0

        # A Document was created (and reused, not duplicated) plus a PipelineRun.
        docs = session.exec(
            select(Document).where(Document.filename == "[eval] mock-baseline invoice-clean.pdf")
        ).all()
        assert len(docs) == 1
        doc_id = docs[0].id
        runs = session.exec(select(PipelineRun).where(PipelineRun.document_id == doc_id)).all()
        assert len(runs) >= 1
        assert "structure" in runs[0].stage_results

        # Two EvalRunRows persisted (one per call), on top of any preexisting ones.
        rows = session.exec(
            select(EvalRunRow).where(EvalRunRow.golden_id == "mock-baseline")
        ).all()
        assert len(rows) == before + 2
        assert any(r.document_id == doc_id for r in rows)


def _pipeline_document(client: TestClient, sample: str, doc_type: str) -> str:
    with (SAMPLES / sample).open("rb") as fh:
        doc_id = client.post("/documents", files={"file": (sample, fh)}).json()["id"]
    client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
    client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": doc_type, "provider": "mock", "ocr_engine": "mock"},
    )
    return doc_id


def test_score_existing_reads_persisted_structure():
    golden = get_golden("mock-baseline")
    with TestClient(app) as client:
        doc_id = _pipeline_document(client, "invoice-clean.pdf", "invoice")

    with Session(db_engine) as session:
        result = score_existing(session, golden, doc_id)
        # The persisted structure is the mock output -> matches mock-baseline perfectly.
        assert result.overall_score == 1.0
        assert result.document_id == doc_id
        # engine/provider are taken from the persisted structuring result.
        assert result.provider == "mock"
        assert result.engine == "mock"

        rows = session.exec(
            select(EvalRunRow).where(EvalRunRow.document_id == doc_id)
        ).all()
        assert len(rows) == 1


def test_score_existing_without_structure_raises():
    golden = get_golden("mock-baseline")
    with Session(db_engine) as session:
        try:
            score_existing(session, golden, "no-such-document")
        except LookupError:
            pass
        else:
            raise AssertionError("expected LookupError for a missing document")
