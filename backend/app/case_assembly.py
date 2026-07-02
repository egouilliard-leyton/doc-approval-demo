"""Case assembly (read model): group a case's member documents + their results.

Given a :class:`~app.models.Case`, :func:`assemble_case` collects each member document,
finds its latest :class:`~app.models.PipelineRun`, and pulls the persisted
``stage_results["structure"]`` into a :class:`~app.schemas.StructuredResult` (or ``None``
when the document hasn't been structured yet). This is the "route & collate" view — the
substrate the Phase 2 reconciler reads. It performs no cross-document reasoning.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models import Case, CaseMembership, Document, PipelineRun
from app.schemas import CaseDetail, CaseMemberAssembly, StructuredResult


def _latest_run(session: Session, doc_id: str) -> PipelineRun | None:
    """Return the newest pipeline run for the document, or ``None`` if there are none.

    Re-implemented locally (rather than importing the route module's private helper) so
    the read model has no dependency on the pipeline routes.
    """
    return session.exec(
        select(PipelineRun)
        .where(PipelineRun.document_id == doc_id)
        .order_by(PipelineRun.created_at.desc())
    ).first()


def _structured_for(session: Session, doc_id: str) -> StructuredResult | None:
    """The document's persisted structuring result, or ``None`` if not yet structured."""
    run = _latest_run(session, doc_id)
    structure = run.stage_results.get("structure") if run else None
    return StructuredResult(**structure) if structure else None


def assemble_case(session: Session, case: Case) -> CaseDetail:
    """Assemble a case's member documents + their grouped structured results."""
    memberships = session.exec(
        select(CaseMembership)
        .where(CaseMembership.case_id == case.id)
        .order_by(CaseMembership.created_at)
    ).all()

    members: list[CaseMemberAssembly] = []
    for membership in memberships:
        doc = session.get(Document, membership.document_id)
        if doc is None:
            continue  # membership orphaned by a deleted document — skip defensively
        members.append(
            CaseMemberAssembly(
                document_id=doc.id,
                filename=doc.filename,
                doc_type=doc.doc_type,
                status=doc.status,
                structured=_structured_for(session, doc.id),
            )
        )

    return CaseDetail(
        id=case.id,
        case_type=case.case_type,
        label=case.label,
        created_at=case.created_at,
        members=members,
    )
