"""Runner + persistence for the accuracy-evaluation harness.

Bridges a :class:`~app.evaluation.golden.GoldenCase` to the real pipeline: it uploads
(once) the golden's sample as a persisted eval Document, runs OCR + structuring exactly
as the ``/documents/{id}/ocr`` + ``/structure`` routes do (reusing their persistence
helpers so stage results land identically), scores the structuring output against the
golden with the pure :mod:`~app.evaluation.scorer`, and records an :class:`EvalRunRow`.

Offline by default (engine=mock, provider=mock) so the harness scores with no network;
the frontend passes real engines/providers.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app import storage
from app.config import BACKEND_ROOT
from app.evaluation.golden import GoldenCase
from app.evaluation.scorer import score_extraction
from app.models import Document, DocumentStatus, EvalRunRow
from app.pipeline.ocr import get_engine
from app.pipeline.structuring import run_structuring
from app.routes.pipeline import _latest_run, _save_stage, get_or_create_run
from app.schemas import EvalRunResult

SAMPLES = BACKEND_ROOT / "samples"


def ensure_document(session: Session, golden: GoldenCase) -> Document:
    """Return the persisted eval Document for ``golden``, creating it once if needed.

    Mirrors ``routes.documents.upload_document``'s core (detect_type / save_original /
    normalize_to_pages) but reads the sample bytes from ``backend/samples/``. The filename
    is prefixed with ``"[eval] "`` and keyed by golden id, so a repeated run reuses the
    same Document rather than re-uploading the sample.
    """
    filename = f"[eval] {golden.id} {golden.sample_file}"
    existing = session.exec(
        select(Document).where(Document.filename == filename)
    ).first()
    if existing is not None and existing.page_count > 0:
        return existing

    content = (SAMPLES / golden.sample_file).read_bytes()
    ext, mime = storage.detect_type(golden.sample_file)
    doc = Document(filename=filename, doc_type=golden.doc_type, mime=mime)
    original = storage.save_original(doc.id, ext, content)
    doc.page_count = storage.normalize_to_pages(doc.id, original, mime)

    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def run_and_score(
    session: Session,
    golden: GoldenCase,
    engine: str = "mock",
    provider: str = "mock",
) -> EvalRunResult:
    """Run OCR + structuring over the golden's sample, score it, and persist the run."""
    doc = ensure_document(session, golden)

    ocr_result = get_engine(engine, session).run(doc)
    run = get_or_create_run(session, doc.id)
    existing_ocr = dict(run.stage_results.get("ocr") or {})
    existing_ocr[engine] = ocr_result.model_dump(mode="json")
    _save_stage(session, run, doc, "ocr", existing_ocr, "ocr_done", DocumentStatus.ocr_done)

    structured = run_structuring(doc, ocr_result, golden.doc_type, provider)
    _save_stage(
        session, run, doc, "structure", structured.model_dump(mode="json"),
        "structured", DocumentStatus.structured,
    )

    return _score_and_persist(session, golden, engine, provider, doc.id, structured.fields)


def score_existing(
    session: Session, golden: GoldenCase, document_id: str
) -> EvalRunResult:
    """Score an EXISTING document's persisted structure stage against ``golden``.

    Reads ``stage_results["structure"]`` off the document's latest run (mirroring
    ``routes.pipeline.get_structure``); raises ``LookupError`` when the document or its
    structure stage is absent (the route maps that to 404). The run is tagged with the
    engine/provider recorded on the persisted structuring result.
    """
    doc = session.get(Document, document_id)
    if doc is None:
        raise LookupError(f"Document '{document_id}' not found.")

    run = _latest_run(session, document_id)
    structure = run.stage_results.get("structure") if run else None
    if not structure:
        raise LookupError("No structuring result for this document.")

    fields = structure.get("fields") or {}
    engine = structure.get("ocr_engine") or ""
    provider = structure.get("provider") or ""
    return _score_and_persist(session, golden, engine, provider, document_id, fields)


def _score_and_persist(
    session: Session,
    golden: GoldenCase,
    engine: str,
    provider: str,
    document_id: str,
    fields: dict,
) -> EvalRunResult:
    """Score ``fields`` against ``golden``, persist an EvalRunRow, return the full result."""
    scored = score_extraction(golden, fields)
    row = EvalRunRow(
        golden_id=golden.id,
        doc_type=golden.doc_type,
        engine=engine,
        provider=provider,
        document_id=document_id,
        overall_score=scored["overall_score"],
        field_accuracy_exact=scored["field_accuracy_exact"],
        field_accuracy_normalized=scored["field_accuracy_normalized"],
        field_scores=scored["field_scores"],
        collection_scores=scored["collection_scores"],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return EvalRunResult.model_validate(row.model_dump())
