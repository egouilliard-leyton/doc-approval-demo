"""Case-level pipeline stage endpoints (Phase 2 multi-document cases).

Mirrors :mod:`app.routes.pipeline`, but each stage runs over a CASE (its assembled
members) rather than a single document, and the results accumulate on a
:class:`~app.models.CaseRun` keyed by ``case_id``. The reconcile/decide stage endpoints
follow the same POST-computes-and-persists / GET-refetches twin pattern; the small
``_latest_run`` / ``get_or_create_run`` / ``_save_stage`` helpers mirror the ``PipelineRun``
versions in ``routes/pipeline.py`` verbatim, reimplemented locally against ``CaseRun``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app import case_types
from app.case_assembly import assemble_case
from app.case_decision import run_case_decision
from app.db import get_session
from app.models import Case, CaseRun, _utcnow
from app.reconcile import reconcile_case
from app.schemas import CaseDecisionResult, CaseReconciliation

router = APIRouter(prefix="/cases", tags=["cases"])


def _latest_run(session: Session, case_id: str) -> CaseRun | None:
    """Return the newest case run for the case, or ``None`` if there are none."""
    return session.exec(
        select(CaseRun).where(CaseRun.case_id == case_id).order_by(CaseRun.created_at.desc())
    ).first()


def get_or_create_run(session: Session, case_id: str) -> CaseRun:
    """Return the newest case run for the case, creating one if none exist."""
    run = _latest_run(session, case_id)
    if run is None:
        run = CaseRun(case_id=case_id)
        session.add(run)
        session.commit()
        session.refresh(run)
    return run


def _save_stage(session: Session, run: CaseRun, stage_key: str, payload: object, run_status: str) -> None:
    """Persist one stage's result onto the run and advance its status.

    A fresh dict is assigned (rather than mutating in place) so SQLAlchemy detects the
    change on the JSON column.
    """
    run.stage_results = {**run.stage_results, stage_key: payload}
    run.status = run_status
    run.updated_at = _utcnow()
    session.add(run)
    session.commit()


def _defn_for(case: Case):
    """The resolved case-type definition for a defined case, or ``None`` for an open pile."""
    return case_types.get_definition(case.case_type) if case.case_type else None


@router.post("/{case_id}/reconcile", response_model=CaseReconciliation)
def reconcile_case_endpoint(
    case_id: str, session: Session = Depends(get_session)
) -> CaseReconciliation:
    """Reconcile a case's members into its canonical fields and persist the result.

    Runs even with zero structured members (returns empty ``canonical_fields`` — not a 409),
    so a partially-assembled case still surfaces its reconciliation state.
    """
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    detail = assemble_case(session, case)
    result = reconcile_case(case, _defn_for(case), detail.members)

    run = get_or_create_run(session, case_id)
    _save_stage(session, run, "reconcile", result.model_dump(mode="json"), "reconciled")
    return result


@router.get("/{case_id}/reconcile", response_model=CaseReconciliation)
def get_reconcile(case_id: str, session: Session = Depends(get_session)) -> CaseReconciliation:
    """Return the persisted reconciliation without recomputing it."""
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    run = _latest_run(session, case_id)
    reconcile = run.stage_results.get("reconcile") if run else None
    if not reconcile:
        raise HTTPException(status_code=404, detail="No reconciliation for this case.")
    return CaseReconciliation(**reconcile)


@router.post("/{case_id}/decide", response_model=CaseDecisionResult)
def decide_case_endpoint(
    case_id: str,
    provider: str = Query(default=""),
    session: Session = Depends(get_session),
) -> CaseDecisionResult:
    """Decide a reconciled case (approve | flag | needs_review) and persist it.

    Reads the persisted ``stage_results["reconcile"]`` (run reconcile first, else 409).
    Deterministic cross-document checks run in code; the LLM (opt-in ``?provider=llm``) only
    adds judgment it can't use to override a failed review check.
    """
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    run = _latest_run(session, case_id)
    reconcile = run.stage_results.get("reconcile") if run else None
    if not reconcile:
        raise HTTPException(status_code=409, detail="Run reconcile before deciding this case.")
    reconciliation = CaseReconciliation(**reconcile)

    detail = assemble_case(session, case)
    result = run_case_decision(reconciliation, detail.members, _defn_for(case), provider)

    # ``run`` is non-None here: a reconcile result was found above, which requires a run.
    _save_stage(session, run, "decide", result.model_dump(mode="json"), result.status)
    return result


@router.get("/{case_id}/decide", response_model=CaseDecisionResult)
def get_case_decision(case_id: str, session: Session = Depends(get_session)) -> CaseDecisionResult:
    """Return the persisted case decision without recomputing it."""
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    run = _latest_run(session, case_id)
    decide = run.stage_results.get("decide") if run else None
    if not decide:
        raise HTTPException(status_code=404, detail="No decision for this case.")
    return CaseDecisionResult(**decide)
