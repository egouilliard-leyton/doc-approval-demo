"""Admin overview endpoint: consolidated counts across the whole system.

Aggregates documents (by status), decision outcomes, the correction log, and the
configured doc-types/engines into one payload for the admin dashboard's KPI cards.
The KPI dashboard extension adds evaluation-accuracy rollups, 30-day throughput /
maintenance time series, and a per-doc-type KPI breakdown — all additive.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import (
    Document,
    DocTypeDefinitionRow,
    EvalRunRow,
    FieldCorrectionRow,
    PipelineRun,
    VlmEngineRow,
)
from app.schemas import (
    AccuracySummary,
    DayBucket,
    DocTypeKpi,
    OverviewStats,
    TimeSeries,
)

router = APIRouter(prefix="/overview", tags=["overview"])

# Grouping key for documents that never resolved a doc type. It is a display /
# grouping label ONLY — never passed to get_extraction_definition or any registry.
UNCLASSIFIED = "unclassified"


def _resolve_doc_type(doc: Document, run: PipelineRun | None) -> str:
    """Best-known doc type for a document: structure result -> Document.doc_type -> fallback.

    Mirrors the review-queue precedent (it reads ``struct.get("doc_type")``); prefers the
    latest run's structuring result, then the persisted ``Document.doc_type``, else the
    ``UNCLASSIFIED`` grouping label.
    """
    if run is not None:
        struct = run.stage_results.get("structure")
        if isinstance(struct, dict) and struct.get("doc_type"):
            return str(struct["doc_type"])
    if doc.doc_type:
        return doc.doc_type
    return UNCLASSIFIED


def _utc_date(dt: datetime) -> date:
    """UTC calendar date of ``dt``, correct whether it is tz-aware or naive.

    SQLite round-trips our ``_utcnow()`` (tz-aware) timestamps back as NAIVE datetimes, so
    this normalizes both forms to a plain UTC ``date`` — sidestepping any naive-vs-aware
    comparison (dates carry no tzinfo).
    """
    return (dt.replace(tzinfo=None) if dt.tzinfo else dt).date()


def _day_window(days: int) -> list[date]:
    """Ascending list of the last ``days`` UTC calendar days, ending today (inclusive)."""
    today = datetime.now(timezone.utc).date()
    return [date.fromordinal(today.toordinal() - offset) for offset in range(days - 1, -1, -1)]


def _bucket_by_day(dts: Iterable[datetime], window: list[date]) -> TimeSeries:
    """Count ``dts`` per UTC day, zero-filled over ``window`` (ascending oldest -> newest)."""
    counts: Counter[date] = Counter()
    window_set = set(window)
    for dt in dts:
        d = _utc_date(dt)
        if d in window_set:
            counts[d] += 1
    buckets = [DayBucket(date=d.isoformat(), count=counts.get(d, 0)) for d in window]
    return TimeSeries(window_days=len(window), buckets=buckets)


def _accuracy_summary(eval_rows: list[EvalRunRow]) -> AccuracySummary:
    """Roll up evaluation-accuracy headline numbers across all eval runs.

    Empty -> all None / 0. Otherwise the latest row (by ``created_at`` desc) supplies the
    latest overall + line-item scores; totals span every row.
    """
    if not eval_rows:
        return AccuracySummary(
            latest_overall_score=None,
            latest_line_item_score=None,
            eval_runs_total=0,
            doc_types_evaluated=0,
        )
    latest = max(eval_rows, key=lambda r: r.created_at)
    line_item = (
        max(v["line_item_score"] for v in latest.collection_scores.values())
        if latest.collection_scores
        else None
    )
    return AccuracySummary(
        latest_overall_score=latest.overall_score,
        latest_line_item_score=line_item,
        eval_runs_total=len(eval_rows),
        doc_types_evaluated=len({r.doc_type for r in eval_rows}),
    )


def _by_doc_type(
    docs: list[Document],
    latest: dict[str, PipelineRun],
    corrections: list[FieldCorrectionRow],
    eval_rows: list[EvalRunRow],
    documents_total: int,
) -> list[DocTypeKpi]:
    """Per-doc-type KPI slices, sorted by document count desc (doc_type asc tie-break)."""
    doc_type_of: dict[str, str] = {
        doc.id: _resolve_doc_type(doc, latest.get(doc.id)) for doc in docs
    }

    # Documents grouped by resolved doc type.
    docs_by_type: dict[str, list[Document]] = {}
    for doc in docs:
        docs_by_type.setdefault(doc_type_of[doc.id], []).append(doc)

    # Corrections grouped by (row.doc_type OR the document's resolved type when the row's
    # doc_type is missing/empty). Never creates an empty-string bucket.
    corr_by_type: dict[str, list[FieldCorrectionRow]] = {}
    for corr in corrections:
        key = corr.doc_type or doc_type_of.get(corr.document_id, UNCLASSIFIED)
        corr_by_type.setdefault(key, []).append(corr)

    # Eval rows grouped by doc type (any engine).
    evals_by_type: dict[str, list[EvalRunRow]] = {}
    for row in eval_rows:
        evals_by_type.setdefault(row.doc_type, []).append(row)

    kpis: list[DocTypeKpi] = []
    for doc_type, group in docs_by_type.items():
        documents = len(group)

        confidences: list[float] = []
        decisions: Counter[str] = Counter()
        for doc in group:
            run = latest.get(doc.id)
            if run is None:
                continue
            struct = run.stage_results.get("structure")
            if isinstance(struct, dict) and struct.get("extraction_confidence") is not None:
                confidences.append(float(struct["extraction_confidence"]))
            decide = run.stage_results.get("decide")
            if isinstance(decide, dict) and decide.get("decision"):
                decisions[str(decide["decision"])] += 1

        group_corrections = corr_by_type.get(doc_type, [])
        group_evals = evals_by_type.get(doc_type, [])
        latest_eval = max(group_evals, key=lambda r: r.created_at) if group_evals else None
        latest_line_item = None
        if latest_eval is not None and latest_eval.collection_scores:
            latest_line_item = max(
                v["line_item_score"] for v in latest_eval.collection_scores.values()
            )

        kpis.append(
            DocTypeKpi(
                doc_type=doc_type,
                documents=documents,
                pct_of_total=(
                    round(documents / documents_total, 4) if documents_total else 0.0
                ),
                avg_extraction_confidence=(
                    round(sum(confidences) / len(confidences), 4) if confidences else None
                ),
                decisions=dict(decisions),
                corrections_total=len(group_corrections),
                corrected_documents=len({c.document_id for c in group_corrections}),
                latest_accuracy=latest_eval.overall_score if latest_eval else None,
                latest_accuracy_engine=latest_eval.engine if latest_eval else None,
                latest_line_item_score=latest_line_item,
                eval_runs=len(group_evals),
            )
        )

    kpis.sort(key=lambda k: (-k.documents, k.doc_type))
    return kpis


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
    eval_rows = session.exec(select(EvalRunRow)).all()
    doc_types = len(session.exec(select(DocTypeDefinitionRow)).all())
    engines = len(
        session.exec(
            select(VlmEngineRow).where(VlmEngineRow.enabled == True)  # noqa: E712
        ).all()
    )

    # KPI dashboard extension (all additive).
    window = _day_window(30)
    by_doc_type = _by_doc_type(docs, latest, corrections, eval_rows, len(docs))
    doc_types_used = len(
        {dt for dt in (_resolve_doc_type(d, latest.get(d.id)) for d in docs) if dt != UNCLASSIFIED}
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
        doc_types_used=doc_types_used,
        accuracy=_accuracy_summary(eval_rows),
        throughput=_bucket_by_day([d.created_at for d in docs], window),
        maintenance=_bucket_by_day([c.created_at for c in corrections], window),
        by_doc_type=by_doc_type,
    )
