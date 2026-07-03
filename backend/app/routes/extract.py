"""Black-box extraction endpoints (Track 1).

One synchronous call runs the WHOLE single-document pipeline
(upload -> prescan -> ocr -> [classify] -> structure -> decide) and returns the
final structured result + decision. Everything here REUSES the existing stage
functions and the persistence helpers from :mod:`app.routes.pipeline` (the same
seam the eval runner uses), so a black-box run lands identical stage results to
driving the staged ``/documents/{id}/...`` routes by hand — it does not
re-implement any stage, nor call one route handler from another.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from app import storage
from app.config import settings
from app.db import get_session
from app.doc_types import is_registered
from app.models import Document, DocumentStatus, FieldCorrectionRow
from app.pipeline.agent import run_decision
from app.pipeline.classify import run_classify
from app.pipeline.ocr import build_engine_objects, resolve_engine_chain, run_ocr_chain
from app.pipeline.prescan import run_prescan
from app.pipeline.structuring import run_structuring
from app.routes.pipeline import (
    _prior_invoice_numbers,
    _run_stage,
    _save_stage,
    get_or_create_run,
)
from app.rules import DecisionContext
from app.schemas import (
    BatchExtractionItem,
    BatchExtractionResult,
    ExtractionResult,
    FieldCorrection,
    OCRResult,
    QualityReport,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extract", tags=["extract"])


def _upload_core(session: Session, file: UploadFile, content: bytes) -> Document:
    """Persist an uploaded file as a Document and rasterize its pages.

    Replicates ``routes.documents.upload_document``'s body (detect_type -> size /
    empty checks -> save_original -> normalize_to_pages -> persist) and raises the
    SAME HTTPExceptions (415/413/400/422). Takes the already-read ``content`` so the
    caller can decide when to consume the upload stream.
    """
    try:
        ext, mime = storage.detect_type(file.filename or "")
    except storage.UnsupportedFileType:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Accepted: {', '.join(sorted(storage.ALLOWED_TYPES))}",
        ) from None

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb} MB upload limit.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    doc = Document(filename=file.filename or f"upload{ext}", doc_type=None, mime=mime)
    original = storage.save_original(doc.id, ext, content)
    try:
        doc.page_count = storage.normalize_to_pages(doc.id, original, mime)
    except Exception as exc:  # corrupt/unreadable file
        raise HTTPException(
            status_code=422, detail="Could not process file; it may be corrupt or unsupported."
        ) from exc

    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


async def _run_extract(
    session: Session,
    file: UploadFile,
    content: bytes,
    *,
    doc_type_override: str | None,
    ocr_engine: str,
    run_prescan_stage: bool,
    deskew: bool,
    clean: bool,
    classify_provider: str,
    structuring_provider: str,
    decision_provider: str,
    on_upload: Callable[[Document], None] | None = None,
) -> ExtractionResult:
    """Run the full single-document pipeline synchronously and return its result.

    Every stage is persisted onto ONE ``PipelineRun`` (via ``get_or_create_run`` +
    ``_save_stage``) so the stage_results dict is built up exactly as the staged
    routes would (order OCR -> [classify] -> structure -> decide). ``on_upload`` is
    invoked as soon as the Document exists, so a batch caller can record the id even
    if a later stage fails.
    """
    doc = _upload_core(session, file, content)
    if on_upload is not None:
        on_upload(doc)

    run = get_or_create_run(session, doc.id)

    # --- prescan (optional, advisory) ----------------------------------------
    report: QualityReport | None = None
    if run_prescan_stage:
        if storage.is_spreadsheet(doc.mime):
            # Spreadsheets have no page image to pre-flight; trivial pass so the
            # pipeline advances (image-quality metrics are meaningless for a grid).
            report = QualityReport(
                document_id=doc.id,
                status=DocumentStatus.prescanned,
                verdict="pass",
                reasons=[],
                preprocess_applied=False,
                pages=[],
            )
        else:
            report = await _run_stage(
                "Prescan", settings.prescan_timeout_s, run_prescan, doc, deskew=deskew, clean=clean
            )
        _save_stage(
            session, run, doc, "prescan", report.model_dump(mode="json"),
            "prescanned", DocumentStatus.prescanned,
        )

    # --- OCR -----------------------------------------------------------------
    # An explicit engine (or a spreadsheet, which must use the dedicated cell-parser)
    # disables routing: the chain is exactly that one engine. Otherwise the doc type's
    # preferred/fallback chain (or the global default) is resolved from the DB.
    if storage.is_spreadsheet(doc.mime):
        chain = ["spreadsheet"]
    elif ocr_engine:
        chain = [ocr_engine]
    else:
        chain = resolve_engine_chain(doc_type_override, session)
    # resolve_engine_chain + build_engine_objects read the Session — request thread
    # only; only the session-free run_ocr_chain enters the worker thread below.
    engine_objs = build_engine_objects(chain, session)
    if not engine_objs:
        raise HTTPException(
            status_code=400,
            detail=f"No usable OCR engine resolved from {chain}.",
        )
    ocr_result = await _run_stage(
        "OCR", settings.ocr_timeout_s, run_ocr_chain, doc, engine_objs
    )
    existing_ocr = dict(run.stage_results.get("ocr") or {})
    # Persist under the ACTUAL engine that produced the result (not the requested one).
    existing_ocr[ocr_result.engine_name] = ocr_result.model_dump(mode="json")
    _save_stage(session, run, doc, "ocr", existing_ocr, "ocr_done", DocumentStatus.ocr_done)

    # --- doc-type resolution (explicit override, else auto-classify) ---------
    classify = None
    doc_type = doc_type_override or doc.doc_type
    if doc_type is None:
        classify = await _run_stage(
            "Classify", settings.llm_timeout_s, run_classify, doc, ocr_result, classify_provider
        )
        if classify.doc_type is None:
            raise HTTPException(
                status_code=422,
                detail="Could not auto-classify the document; pass doc_type explicitly.",
            )
        resolved_type = classify.doc_type
    else:
        resolved_type = doc_type

    if not is_registered(resolved_type):
        raise HTTPException(status_code=422, detail=f"Unknown doc_type '{resolved_type}'")

    # --- structuring ---------------------------------------------------------
    # Active-learning loop: feed this doc type's past reviewer corrections into
    # structuring (NO-OP for the mock provider / no corrections / disabled flag).
    rows = session.exec(
        select(FieldCorrectionRow).where(FieldCorrectionRow.doc_type == resolved_type)
    ).all()
    corrections = [
        FieldCorrection(
            document_id=row.document_id,
            doc_type=row.doc_type,
            field_path=row.field_path,
            original_value=row.original_value,
            new_value=row.new_value,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]

    structured = await _run_stage(
        "Structuring",
        settings.llm_timeout_s,
        run_structuring,
        doc,
        ocr_result,
        resolved_type,
        structuring_provider,
        corrections=corrections,
    )
    _save_stage(
        session, run, doc, "structure", structured.model_dump(mode="json"),
        "structured", DocumentStatus.structured,
    )

    # --- decision ------------------------------------------------------------
    prescan = run.stage_results.get("prescan") or {}
    ctx = DecisionContext(
        extraction_confidence=structured.extraction_confidence,
        prescan_verdict=prescan.get("verdict"),
        prescan_reasons=list(prescan.get("reasons") or []),
        prior_invoice_numbers=_prior_invoice_numbers(session, doc.id),
    )
    decision = await _run_stage(
        "Decision", settings.llm_timeout_s, run_decision, doc, structured, ctx, decision_provider
    )
    _save_stage(
        session, run, doc, "decide", decision.model_dump(mode="json"),
        decision.status.value, decision.status,
    )

    warnings = list(structured.warnings) + list(decision.warnings)
    if classify is not None:
        warnings.append(f"doc_type was auto-classified as '{resolved_type}'.")

    return ExtractionResult(
        document_id=doc.id,
        doc_type=resolved_type,
        classify=classify,
        prescan=report,
        structured=structured,
        decision=decision,
        warnings=warnings,
    )


@router.post("", response_model=ExtractionResult)
async def extract_document(
    file: UploadFile = File(...),
    doc_type: str = Form(default=""),
    ocr_engine: str = Form(default=""),
    run_prescan: bool = Form(default=True),
    deskew: bool = Form(default=True),
    clean: bool = Form(default=False),
    classify_provider: str = Form(default=""),
    structuring_provider: str = Form(default=""),
    decision_provider: str = Form(default=""),
    session: Session = Depends(get_session),
) -> ExtractionResult:
    """Run the whole pipeline over one uploaded file and return the final result.

    ``doc_type`` may be omitted (empty) to auto-classify. HTTPExceptions from the
    underlying stages propagate with the same status codes as the staged routes
    (415/413/400/422/504).
    """
    content = await file.read()
    return await _run_extract(
        session,
        file,
        content,
        doc_type_override=doc_type or None,
        ocr_engine=ocr_engine,
        run_prescan_stage=run_prescan,
        deskew=deskew,
        clean=clean,
        classify_provider=classify_provider,
        structuring_provider=structuring_provider,
        decision_provider=decision_provider,
    )


@router.post("/batch", response_model=BatchExtractionResult)
async def extract_batch(
    files: list[UploadFile] = File(...),
    doc_type: str = Form(default=""),
    ocr_engine: str = Form(default=""),
    run_prescan: bool = Form(default=True),
    deskew: bool = Form(default=True),
    clean: bool = Form(default=False),
    classify_provider: str = Form(default=""),
    structuring_provider: str = Form(default=""),
    decision_provider: str = Form(default=""),
    session: Session = Depends(get_session),
) -> BatchExtractionResult:
    """Run the full pipeline over each uploaded file, applying the same options.

    Sequential by design: the ``_prior_invoice_numbers`` dedup scan reads other
    documents' committed decide results, so concurrent runs would race. Always
    returns HTTP 200; per-file failures are reported inside each item.
    """
    items: list[BatchExtractionItem] = []
    for file in files:
        item = BatchExtractionItem(filename=file.filename or "")
        try:
            content = await file.read()
            item.result = await _run_extract(
                session,
                file,
                content,
                doc_type_override=doc_type or None,
                ocr_engine=ocr_engine,
                run_prescan_stage=run_prescan,
                deskew=deskew,
                clean=clean,
                classify_provider=classify_provider,
                structuring_provider=structuring_provider,
                decision_provider=decision_provider,
                on_upload=lambda doc, _item=item: setattr(_item, "document_id", doc.id),
            )
            item.document_id = item.result.document_id
        except HTTPException as exc:
            item.error = str(exc.detail)
            item.error_status = exc.status_code
        except Exception as exc:  # noqa: BLE001 — one bad file must not sink the batch
            logger.exception("Unexpected error extracting %s", file.filename)
            item.error = f"Unexpected error: {exc}"
        items.append(item)

    succeeded = sum(1 for it in items if it.result is not None)
    return BatchExtractionResult(items=items, succeeded=succeeded, failed=len(items) - succeeded)
