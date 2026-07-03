"""Phase 4 (Vision QA) Wave 1: judge a rendered template against a reference.

Two providers behind one entrypoint, mirroring :mod:`app.pipeline.ocr.qwen_vl` and
:mod:`app.pipeline.decision`:

* ``llm`` — one multimodal OpenRouter call (OpenAI-compatible client) whose user message
  interleaves text labels with base64 ``image_url`` parts (rendered page N, then the
  reference page N when available), returning a JSON fidelity report. Imported lazily so
  the app boots without the optional ``openai`` dep.
* ``mock`` — a fixed, deterministic outcome (no network), so the whole QA path is
  offline-testable.

Any failure on the ``llm`` path — no key, network error, unparsable output — degrades to
the mock outcome with a warning appended, never raising into the caller (same graceful
degradation as the OCR/decision stages).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field as dc_field

from app.config import settings

PROVIDERS = {"llm", "mock"}

_SEVERITIES = {"low", "medium", "high"}
_CATEGORIES = {"layout", "color", "table", "spacing", "text", "missing"}

_SYSTEM_PROMPT = (
    "You are a meticulous document-fidelity reviewer. You are shown a rendered document "
    "and, when available, a reference the render should match. Identify concrete visual "
    "issues — layout, color, table, spacing, text, or missing content — and for each give "
    "a short description and a suggested fix. Do not invent issues; report only what you "
    "can see. Respond ONLY with a JSON object: "
    '{"summary": str, "ok": bool, "findings": [{"severity": "low"|"medium"|"high", '
    '"category": "layout"|"color"|"table"|"spacing"|"text"|"missing", "description": str, '
    '"suggested_fix": str, "page": int}]}.'
)


@dataclass
class QaOutcome:
    """Result of :func:`run_qa`: the vision judge's findings + provenance."""

    findings: list[dict]
    summary: str
    ok: bool
    provider_used: str
    model: str
    warnings: list[str] = dc_field(default_factory=list)


def _mock_outcome(warnings: list[str] | None = None) -> QaOutcome:
    """A fixed, deterministic outcome — the offline provider and the llm fallback."""
    return QaOutcome(
        findings=[
            {
                "severity": "medium",
                "category": "spacing",
                "description": "Header block sits too close to the first body paragraph.",
                "suggested_fix": "Add ~12px top margin above the body content.",
                "page": 1,
            },
            {
                "severity": "low",
                "category": "color",
                "description": "Label text uses a lighter grey than the reference.",
                "suggested_fix": "Darken the label color toward the reference tone.",
                "page": 1,
            },
        ],
        summary="2 potential issues found.",
        ok=False,
        provider_used="mock",
        model="mock",
        warnings=list(warnings or []),
    )


def run_qa(
    rendered_pngs: list[bytes],
    reference_pngs: list[bytes],
    doc_type,
    html_excerpt: str,
    instructions: str | None,
    provider: str = "",
) -> QaOutcome:
    """Judge ``rendered_pngs`` (optionally against ``reference_pngs``) for visual fidelity.

    ``provider`` defaults to ``settings.qa_vision_provider``; an unknown value raises
    :class:`ValueError`. The ``mock`` provider returns a fixed outcome offline. The ``llm``
    provider sends the images to a multimodal model and, on any failure, degrades to the
    mock outcome with a warning appended.
    """
    provider = provider or settings.qa_vision_provider
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown qa vision provider '{provider}'. Available: {', '.join(sorted(PROVIDERS))}"
        )

    if provider == "mock":
        return _mock_outcome()

    return _qa_llm(rendered_pngs, reference_pngs, doc_type, html_excerpt, instructions)


# --- providers ----------------------------------------------------------------


def _image_part(png: bytes) -> dict:
    """Wrap PNG bytes as an OpenAI-style base64 ``image_url`` content part."""
    b64 = base64.b64encode(png).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def _build_content(
    rendered_pngs: list[bytes],
    reference_pngs: list[bytes],
    doc_type,
    html_excerpt: str,
    instructions: str | None,
) -> tuple[list[dict], list[str]]:
    """Build the interleaved (text + image) user content array, plus any warnings."""
    warnings: list[str] = []
    cap = settings.qa_max_pages
    rendered = rendered_pngs[:cap]
    reference = reference_pngs[:cap]
    if len(rendered_pngs) > cap or len(reference_pngs) > cap:
        warnings.append(f"QA images capped at qa_max_pages={cap}")

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Document type: {doc_type}\n"
                f"Template HTML (excerpt):\n{html_excerpt}\n\n"
                + (f"Extra instructions: {instructions}\n\n" if instructions else "")
                + "Review the rendered page(s) below for visual-fidelity issues."
            ),
        }
    ]

    for page_no, png in enumerate(rendered, start=1):
        content.append({"type": "text", "text": f"Rendered page {page_no}:"})
        content.append(_image_part(png))

    if reference:
        for page_no, png in enumerate(reference, start=1):
            content.append({"type": "text", "text": f"Reference page {page_no}:"})
            content.append(_image_part(png))
    else:
        content.append(
            {
                "type": "text",
                "text": (
                    "No reference available — critique the rendered page(s) against the "
                    "described HTML and the document type's expected fields."
                ),
            }
        )

    return content, warnings


def _parse_findings(raw: object) -> list[dict]:
    """Coerce the model's findings into a clean, validated list of dicts."""
    if not isinstance(raw, list):
        return []
    findings: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "low"))
        category = str(item.get("category", "layout"))
        try:
            page = int(item.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        findings.append(
            {
                "severity": severity if severity in _SEVERITIES else "low",
                "category": category if category in _CATEGORIES else "layout",
                "description": str(item.get("description", "")),
                "suggested_fix": str(item.get("suggested_fix", "")),
                "page": page,
            }
        )
    return findings


def _qa_llm(
    rendered_pngs: list[bytes],
    reference_pngs: list[bytes],
    doc_type,
    html_excerpt: str,
    instructions: str | None,
) -> QaOutcome:
    """Single multimodal OpenRouter call returning a fidelity report.

    On any error (missing key, network, unparsable output) degrades to the fixed mock
    outcome with a warning appended — never raises into the caller.
    """
    content, warnings = _build_content(
        rendered_pngs, reference_pngs, doc_type, html_excerpt, instructions
    )
    try:
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set; the 'llm' qa provider needs it.")

        import openai  # lazy: optional dep (the `agent` extra)

        client = openai.OpenAI(
            api_key=settings.openrouter_api_key, base_url=settings.qa_vision_base_url
        )
        response = client.chat.completions.create(
            model=settings.qa_vision_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001 — degrade to mock, surface as a warning
        return _mock_outcome([*warnings, f"qa vision LLM error: {exc}"])

    findings = _parse_findings(payload.get("findings"))
    summary = str(payload.get("summary", f"{len(findings)} potential issues found."))
    ok = bool(payload.get("ok", not findings))
    return QaOutcome(
        findings=findings,
        summary=summary,
        ok=ok,
        provider_used="llm",
        model=settings.qa_vision_model,
        warnings=warnings,
    )
