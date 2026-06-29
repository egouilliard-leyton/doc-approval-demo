"""FastAPI entrypoint for the document auto-approval backend."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.config import settings
from app.db import engine, init_db
from app.routes import doc_types, documents, pipeline

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
    if settings.pre_warm_models:
        # Warm OCR models off the startup path so the server is immediately live and
        # the first real request doesn't pay the cold model-load cost on camera.
        import threading

        from app.pipeline.ocr import available_engines, prewarm

        engines = [e for e in available_engines() if e != "mock"]
        threading.Thread(
            target=prewarm, args=(engines,), kwargs={"log": print}, daemon=True
        ).start()
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
app.include_router(doc_types.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend status indicator."""
    return {"status": "ok"}
