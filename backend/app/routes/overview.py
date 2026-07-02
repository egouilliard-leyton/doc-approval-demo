"""Admin overview endpoint: consolidated counts across the whole system.

Aggregates documents (by status), decision outcomes, the correction log, and the
configured doc-types/engines into one payload for the admin dashboard's KPI cards.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import (
    Document,
    DocTypeDefinitionRow,
    FieldCorrectionRow,
    PipelineRun,
    VlmEngineRow,
)
from app.schemas import OverviewStats

router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("", response_model=OverviewStats)
def get_overview(session: Session = Depends(get_session)) -> OverviewStats:
    """Return consolidated system counts for the admin dashboard."""
    docs = session.exec(select(Document)).all()
    by_status: Counter[str] = Counter(d.status.value for d in docs)

    # Latest run per document, for decision + confidence rollups.
    latest: dict[str, PipelineRun] = {}
    for run in session.exec(select(PipelineRun)).all():
        cur = latest.get(run.document_id)
        if cur is None or run.created_at > cur.created_at:
            latest[run.document_id] = run

    decisions: Counter[str] = Counter()
    confidences: list[float] = []
    for run in latest.values():
        decide = run.stage_results.get("decide")
        if isinstance(decide, dict) and decide.get("decision"):
            decisions[str(decide["decision"])] += 1
        struct = run.stage_results.get("structure")
        if isinstance(struct, dict) and struct.get("extraction_confidence") is not None:
            confidences.append(float(struct["extraction_confidence"]))

    corrections = session.exec(select(FieldCorrectionRow)).all()
    doc_types = len(session.exec(select(DocTypeDefinitionRow)).all())
    engines = len(
        session.exec(
            select(VlmEngineRow).where(VlmEngineRow.enabled == True)  # noqa: E712
        ).all()
    )

    return OverviewStats(
        documents_total=len(docs),
        documents_by_status=dict(by_status),
        decisions=dict(decisions),
        corrections_total=len(corrections),
        corrected_documents=len({c.document_id for c in corrections}),
        doc_types=doc_types,
        engines_enabled=engines,
        avg_extraction_confidence=(
            round(sum(confidences) / len(confidences), 4) if confidences else None
        ),
    )
