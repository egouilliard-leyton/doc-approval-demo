"""Accuracy-evaluation harness endpoints.

Lists the golden catalogue, runs a golden through the pipeline (or re-scores an existing
document's persisted structure), and lists/reads the persisted scored runs. The scoring
itself is pure (:mod:`app.evaluation.scorer`); this router is the thin read/write side,
mirroring the style of ``routes.corrections`` + ``routes.overview``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.evaluation.golden import get_golden, load_goldens
from app.evaluation.runner import run_and_score, score_existing
from app.models import EvalRunRow
from app.schemas import (
    EvalGoldenDetail,
    EvalGoldenSummary,
    EvalRunRequest,
    EvalRunResult,
    EvalRunSummary,
)

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.get("/goldens", response_model=list[EvalGoldenSummary])
def list_goldens() -> list[EvalGoldenSummary]:
    """The golden catalogue (compact), sorted by id."""
    return [
        EvalGoldenSummary(
            id=g.id,
            sample_file=g.sample_file,
            doc_type=g.doc_type,
            field_count=len(g.expected_fields),
            collection_count=len(g.expected_collections),
        )
        for g in load_goldens()
    ]


@router.get("/goldens/{golden_id}", response_model=EvalGoldenDetail)
def get_golden_detail(golden_id: str) -> EvalGoldenDetail:
    """One golden's full expected values (404 when unknown)."""
    try:
        g = get_golden(golden_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown golden '{golden_id}'.") from None
    return EvalGoldenDetail(
        id=g.id,
        sample_file=g.sample_file,
        doc_type=g.doc_type,
        field_count=len(g.expected_fields),
        collection_count=len(g.expected_collections),
        expected_fields=g.expected_fields,
        expected_collections=g.expected_collections,
    )


@router.post("/run", response_model=EvalRunResult)
def run_eval(
    body: EvalRunRequest, session: Session = Depends(get_session)
) -> EvalRunResult:
    """Score a golden and persist the run.

    With ``document_id`` set, re-scores that document's persisted structure stage (404 if
    absent); otherwise runs OCR + structuring over the golden's sample first.
    """
    try:
        golden = get_golden(body.golden_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Unknown golden '{body.golden_id}'."
        ) from None

    if body.document_id:
        try:
            return score_existing(session, golden, body.document_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
    return run_and_score(session, golden, body.engine, body.provider)


@router.get("/runs", response_model=list[EvalRunSummary])
def list_runs(
    golden_id: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    engine: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[EvalRunRow]:
    """Persisted eval runs, newest first; optionally filtered by golden/doc-type/engine."""
    stmt = select(EvalRunRow)
    if golden_id:
        stmt = stmt.where(EvalRunRow.golden_id == golden_id)
    if doc_type:
        stmt = stmt.where(EvalRunRow.doc_type == doc_type)
    if engine:
        stmt = stmt.where(EvalRunRow.engine == engine)
    stmt = stmt.order_by(EvalRunRow.created_at.desc())
    return session.exec(stmt).all()


@router.get("/runs/{run_id}", response_model=EvalRunResult)
def get_run(run_id: str, session: Session = Depends(get_session)) -> EvalRunResult:
    """One persisted eval run in full detail (404 when unknown)."""
    row = session.get(EvalRunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown eval run '{run_id}'.")
    return EvalRunResult.model_validate(row.model_dump())
