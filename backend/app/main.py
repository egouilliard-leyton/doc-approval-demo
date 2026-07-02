"""FastAPI entrypoint for the document auto-approval backend."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.config import settings
from app.db import engine, init_db
from app.routes import (
    case_types,
    cases,
    corrections,
    doc_types,
    doctype_assist,
    documents,
    engines as engines_route,
    overview,
    pipeline,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Seed built-in doc-type rows and register any custom (DB-backed) types. A seeding
    # failure must not crash boot — the built-ins still resolve from code regardless.
    try:
        from app.doc_types import load_custom_types, seed_builtins

        with Session(engine) as session:
            seed_builtins(session)
            load_custom_types(session)
    except Exception as exc:  # noqa: BLE001 — never block startup on doc-type seeding
        logger.warning("Doc-type seeding/loading failed: %s", exc)
    # Seed the built-in case-type row(s) and register any custom (DB-backed) case types.
    # A seeding failure must not crash boot — the built-in still resolves from code.
    try:
        from app.case_types import load_custom_types, seed_builtins

        with Session(engine) as session:
            seed_builtins(session)
            load_custom_types(session)
    except Exception as exc:  # noqa: BLE001 — never block startup on case-type seeding
        logger.warning("Case-type seeding/loading failed: %s", exc)
    # Seed the default VLM engine row (qwen-vl) so the OCR selector is populated on a
    # fresh DB. Keeps the same key as before so existing stored results still resolve.
    try:
        from app.routes.engines import seed_default_engine

        with Session(engine) as session:
            seed_default_engine(session)
    except Exception as exc:  # noqa: BLE001 — never block startup on engine seeding
        logger.warning("VLM engine seeding failed: %s", exc)
    if settings.pre_warm_models:
        # Warm OCR models off the startup path so the server is immediately live and
        # the first real request doesn't pay the cold model-load cost on camera.
        import threading

        from app.pipeline.ocr import available_engines, prewarm

        with Session(engine) as session:
            engines = [e for e in available_engines(session) if e != "mock"]
        threading.Thread(
            target=prewarm, args=(engines,), kwargs={"log": print}, daemon=True
        ).start()

        if settings.signature_detection_enabled:
            # Warm the signature model too. Best-effort: a missing model / optional deps
            # only logs a warning and never blocks startup.
            def _warm_signatures() -> None:
                try:
                    from app.pipeline import signature_detector

                    signature_detector.warm()
                except Exception as exc:  # noqa: BLE001 — never block startup on warming
                    logger.warning("Signature model warm failed: %s", exc)

            threading.Thread(target=_warm_signatures, daemon=True).start()
    yield


app = FastAPI(title="Document Approval System", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # The API is token-/cookie-free, so credentialed requests aren't needed. Leaving
    # this off also avoids the wildcard-origin footgun if cors_origins is ever widened.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Importing app.db ensures the data dir exists; mount it for serving page images.
app.mount("/files", StaticFiles(directory=settings.data_path), name="files")

app.include_router(documents.router)
app.include_router(pipeline.router)
app.include_router(cases.router)
app.include_router(case_types.router)
app.include_router(doc_types.router)
app.include_router(doctype_assist.router)
app.include_router(engines_route.router)
app.include_router(corrections.router)
app.include_router(overview.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend status indicator."""
    return {"status": "ok"}
