"""Review-queue endpoint: low-confidence extracted fields needing reviewer attention.

Scans the latest structuring result of every document, flattens it to leaf fields,
and surfaces those whose confidence falls below the review threshold and that a
reviewer hasn't already edited. Presence-kind fields (a boolean "is X present?")
are excluded — a 0.0 confidence there is not an extraction the reviewer can fix.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.doc_types import get_extraction_definition
from app.models import Document, PipelineRun
from app.pipeline.structuring import flatten_field_values
from app.schemas import ReviewQueueDocument, ReviewQueueField, ReviewQueueResponse

router = APIRouter(prefix="/review-queue", tags=["review-queue"])


@router.get("", response_model=ReviewQueueResponse)
def get_review_queue(
    threshold: float | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> ReviewQueueResponse:
    """Return documents with at-risk (low-confidence, unedited) extracted fields.

    ``threshold`` defaults to ``settings.field_review_confidence_threshold``. A field
    is at risk iff ``confidence < threshold``, it hasn't been ``edited``, and it isn't
    a presence-kind field. Documents with zero at-risk fields are omitted.
    """
    effective_threshold = (
        threshold if threshold is not None else settings.field_review_confidence_threshold
    )

    # Latest run per document (max created_at), matching the overview scan pattern.
    latest: dict[str, PipelineRun] = {}
    for run in session.exec(select(PipelineRun)).all():
        cur = latest.get(run.document_id)
        if cur is None or run.created_at > cur.created_at:
            latest[run.document_id] = run

    documents: list[ReviewQueueDocument] = []
    for doc_id, run in latest.items():
        struct = run.stage_results.get("structure")
        if not struct:
            continue
        struct_doc_type = struct.get("doc_type")
        if doc_type is not None and struct_doc_type != doc_type:
            continue

        # Presence-kind top-level fields are excluded from the queue; an unregistered
        # or deleted custom type degrades to "no exclusions" rather than 500.
        try:
            presence_names = {
                f.name
                for f in get_extraction_definition(struct_doc_type).fields
                if f.kind == "presence"
            }
        except ValueError:
            presence_names = set()

        at_risk: list[ReviewQueueField] = []
        for path, node in flatten_field_values(struct.get("fields") or {}).items():
            if node.get("edited"):
                continue
            if path.split(".")[0] in presence_names:
                continue
            confidence = node.get("confidence", 0.0)
            if confidence < effective_threshold:
                at_risk.append(
                    ReviewQueueField(
                        path=path,
                        value=node.get("value"),
                        confidence=confidence,
                        grounding=node.get("grounding"),
                    )
                )

        if not at_risk:
            continue

        at_risk.sort(key=lambda f: f.confidence)  # worst first
        last_decision = run.stage_results.get("decide", {}).get("decision")
        documents.append(
            ReviewQueueDocument(
                document_id=doc_id,
                filename="",  # backfilled from the batch Document load below
                doc_type=struct_doc_type,
                status=struct.get("status"),
                last_decision=last_decision,
                at_risk_count=len(at_risk),
                lowest_confidence=at_risk[0].confidence,
                fields=at_risk,
            )
        )
        # ``status`` is a required placeholder here; the authoritative value is
        # backfilled from the Document row below.

    # Batch-load the Document rows for filename/status (one query, not per-doc).
    doc_ids = [d.document_id for d in documents]
    doc_map: dict[str, Document] = {}
    if doc_ids:
        doc_map = {
            d.id: d for d in session.exec(select(Document).where(Document.id.in_(doc_ids))).all()
        }
    for entry in documents:
        row = doc_map.get(entry.document_id)
        if row is not None:
            entry.filename = row.filename
            entry.status = row.status

    documents.sort(key=lambda d: (-d.at_risk_count, d.lowest_confidence))
    return ReviewQueueResponse(
        threshold=effective_threshold,
        total_at_risk_fields=sum(d.at_risk_count for d in documents),
        documents=documents,
    )
