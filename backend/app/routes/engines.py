"""OCR engine registry endpoints: pick engines + manage connected VLM models.

Docling is a code-defined layout engine (always available); VLM engines are
:class:`app.models.VlmEngineRow` rows — one OpenRouter model each — that the user
connects from the settings UI. Connecting a model is a row, not a code change,
because every VLM speaks the same OpenAI-compatible API behind OpenRouter.

``GET /engines/openrouter-models`` proxies OpenRouter's live model list (filtered to
image-capable models) so the settings dropdown always reflects what's actually
available; ``CURATED_VLM_MODELS`` is only a fallback when the key/network is absent.
"""

from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models import VlmEngineRow
from app.schemas import (
    EngineCreate,
    EngineInfo,
    EngineUpdate,
    OpenRouterModel,
    VlmEngineResponse,
)

router = APIRouter(prefix="/engines", tags=["engines"])

# Fallback list for the add-model dropdown when the live OpenRouter list can't be
# fetched (no key / offline). The live endpoint is the source of truth, so these
# best-effort slugs self-correct when online — keep as a convenience seed only.
CURATED_VLM_MODELS: list[OpenRouterModel] = [
    OpenRouterModel(id="qwen/qwen3-vl-235b-a22b-instruct", name="Qwen3-VL 235B A22B"),
    OpenRouterModel(id="qwen/qwen3-vl-72b-instruct", name="Qwen3-VL 72B"),
    OpenRouterModel(id="qwen/qwen3-vl-8b-instruct", name="Qwen3-VL 8B"),
    OpenRouterModel(id="google/gemini-3-pro", name="Gemini 3 Pro"),
    OpenRouterModel(id="google/gemini-3-flash", name="Gemini 3 Flash"),
    OpenRouterModel(id="openai/gpt-5.2", name="GPT-5.2"),
    OpenRouterModel(id="anthropic/claude-sonnet-4.5", name="Claude Sonnet 4.5"),
    OpenRouterModel(id="anthropic/claude-sonnet-4.7", name="Claude Sonnet 4.7"),
    OpenRouterModel(id="opengvlab/internvl3.5-38b", name="InternVL 3.5 38B"),
    OpenRouterModel(id="z-ai/glm-4.6v", name="GLM-4.6V"),
    OpenRouterModel(id="z-ai/glm-4.7v", name="GLM-4.7V"),
]


def _key_from_model(model: str) -> str:
    """Derive a url-safe, unique engine key from an OpenRouter slug.

    ``google/gemini-3-pro`` -> ``google-gemini-3-pro``. Keeps the provider prefix so
    same-named models from different providers don't collide.
    """
    key = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    return key or "engine"


def seed_default_engine(session: Session) -> None:
    """Seed the default ``qwen-vl`` engine row on a fresh DB (idempotent).

    Reuses the existing key so any previously-stored ``stage_results["ocr"]["qwen-vl"]``
    still resolves and the frontend selector is populated out of the box.
    """
    if session.get(VlmEngineRow, "qwen-vl") is not None:
        return
    session.add(
        VlmEngineRow(key="qwen-vl", label="Qwen3-VL", model=settings.ocr_vlm_model, enabled=True)
    )
    session.commit()


@router.get("", response_model=list[EngineInfo])
def list_engines(session: Session = Depends(get_session)) -> list[EngineInfo]:
    """Engines selectable at upload time: docling (layout) + every enabled VLM."""
    engines = [EngineInfo(key="docling", label="Docling", kind="layout")]
    rows = session.exec(
        select(VlmEngineRow).where(VlmEngineRow.enabled == True).order_by(VlmEngineRow.created_at)  # noqa: E712
    ).all()
    engines += [EngineInfo(key=r.key, label=r.label, kind="vlm") for r in rows]
    return engines


@router.get("/catalog", response_model=list[VlmEngineResponse])
def list_catalog(session: Session = Depends(get_session)) -> list[VlmEngineRow]:
    """All connected VLM engines (enabled + disabled), for the settings view."""
    return session.exec(select(VlmEngineRow).order_by(VlmEngineRow.created_at)).all()


@router.get("/openrouter-models", response_model=list[OpenRouterModel])
def list_openrouter_models() -> list[OpenRouterModel]:
    """Image-capable models offered by OpenRouter, for the add-model dropdown.

    Best-effort: on a missing key or any network/parse error, returns the curated
    fallback instead of 500ing, so the settings UI always has something to show.
    """
    if not settings.openrouter_api_key:
        return CURATED_VLM_MODELS
    try:
        resp = httpx.get(
            f"{settings.ocr_vlm_base_url}/models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception:  # noqa: BLE001 — never fail the settings page on a flaky fetch
        return CURATED_VLM_MODELS

    models: list[OpenRouterModel] = []
    for entry in data:
        modalities = (entry.get("architecture") or {}).get("input_modalities") or []
        if "image" not in modalities:
            continue
        mid = entry.get("id")
        if not mid:
            continue
        models.append(OpenRouterModel(id=mid, name=entry.get("name") or mid))
    models.sort(key=lambda m: m.name.lower())
    return models or CURATED_VLM_MODELS


@router.post("", response_model=VlmEngineResponse, status_code=201)
def create_engine(
    body: EngineCreate, session: Session = Depends(get_session)
) -> VlmEngineRow:
    """Connect a new VLM engine (one OpenRouter model)."""
    key = body.key or _key_from_model(body.model)
    if session.get(VlmEngineRow, key) is not None:
        raise HTTPException(status_code=409, detail=f"Engine '{key}' already exists.")

    row = VlmEngineRow(key=key, label=body.label, model=body.model, enabled=body.enabled)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.patch("/{key}", response_model=VlmEngineResponse)
def update_engine(
    key: str, body: EngineUpdate, session: Session = Depends(get_session)
) -> VlmEngineRow:
    """Enable/disable or relabel a connected VLM engine."""
    row = session.get(VlmEngineRow, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Engine '{key}' not found.")
    if body.label is not None:
        row.label = body.label
    if body.enabled is not None:
        row.enabled = body.enabled
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.delete("/{key}", status_code=204)
def delete_engine(key: str, session: Session = Depends(get_session)) -> None:
    """Disconnect a VLM engine. Docling isn't a row, so it can't be removed."""
    row = session.get(VlmEngineRow, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Engine '{key}' not found.")
    session.delete(row)
    session.commit()
