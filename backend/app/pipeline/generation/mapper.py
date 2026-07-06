"""Phase 1 (form-fill) Wave 3: suggest catalogue bindings for a PDF's form fields.

Two providers behind one entrypoint, mirroring ``agent.py`` / ``structuring.py``:

* ``llm`` — a single OpenRouter call (OpenAI-compatible client), imported lazily so
  the app boots and tests run without the optional ``openai`` dep.
* ``mock`` — a deterministic token-overlap heuristic (Jaccard over the field's name +
  nearby label vs each catalogue entry's path + label). It is genuinely useful offline
  and doubles as the *per-field* fallback whenever the LLM omits or mangles a field.

Graceful degradation, like its siblings: a missing key, a failed import, or any LLM
error falls back to the heuristic for the whole request — it never raises to the caller.
"""

from __future__ import annotations

import json
import logging
import re

from app.config import settings
from app.schemas import FieldCatalogueEntry, MappingSuggestion, TemplateFormField

PROVIDERS = {"llm", "mock"}

logger = logging.getLogger(__name__)

# A heuristic match at or above this Jaccard overlap is accepted; below it -> None.
_MATCH_THRESHOLD = 0.3

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(*parts: str | None) -> set[str]:
    """Lowercase, split on non-alphanumerics + camelCase, drop numeric/blank tokens."""
    out: set[str] = set()
    for part in parts:
        if not part:
            continue
        # split camelCase into words before lowercasing.
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", part)
        for tok in _TOKEN_SPLIT.split(spaced.lower()):
            if tok and not tok.isdigit():
                out.add(tok)
    return out


def _catalogue_tokens(entry: FieldCatalogueEntry) -> set[str]:
    return _tokens(entry.path.replace(".", " "), entry.label)


def _heuristic_for(
    field: TemplateFormField, catalogue: list[FieldCatalogueEntry]
) -> MappingSuggestion:
    """Best token-overlap catalogue guess for one form field (offline, deterministic)."""
    is_signature = field.kind == "signature"
    if is_signature:
        # A signature is a stamp target, not a data binding: no catalogue path.
        return MappingSuggestion(
            field_path=None,
            confidence=None,
            source="heuristic",
            is_signature=True,
            rationale="signature field (stamped, not filled)",
        )

    field_tokens = _tokens(field.name, field.nearby_label)
    best_entry: FieldCatalogueEntry | None = None
    best_score = 0.0
    for entry in catalogue:
        entry_tokens = _catalogue_tokens(entry)
        union = field_tokens | entry_tokens
        if not union:
            continue
        score = len(field_tokens & entry_tokens) / len(union)
        if score > best_score:
            best_score, best_entry = score, entry

    if best_entry is None or best_score < _MATCH_THRESHOLD:
        return MappingSuggestion(
            field_path=None, confidence=None, source="heuristic", is_signature=False,
            rationale="no catalogue field overlapped this form field",
        )
    return MappingSuggestion(
        field_path=best_entry.path,
        confidence=round(best_score, 4),
        source="heuristic",
        is_signature=False,
        rationale=f"token overlap with '{best_entry.label}' ({best_entry.path})",
    )


def suggest_mapping(
    doc_type,
    form_fields: list[TemplateFormField],
    catalogue: list[FieldCatalogueEntry],
    provider: str = "",
) -> dict[str, MappingSuggestion]:
    """Suggest a catalogue binding per PDF form field, keyed by field name.

    Resolves the provider (explicit arg else ``settings.mapping_provider``). The ``llm``
    path degrades to the heuristic on any problem; the heuristic always runs offline.
    """
    provider = provider or settings.mapping_provider
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown mapping provider '{provider}'. Available: {', '.join(sorted(PROVIDERS))}"
        )

    heuristic = {f.name: _heuristic_for(f, catalogue) for f in form_fields}
    if provider == "mock":
        return heuristic

    if not settings.openrouter_api_key:
        logger.warning("mapping provider 'llm' has no OPENROUTER_API_KEY; using heuristic")
        return heuristic

    try:
        llm = _suggest_llm(str(getattr(doc_type, "value", doc_type)), form_fields, catalogue)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never raise to caller
        logger.warning("mapping LLM failed (%s); using heuristic", exc)
        return heuristic

    # Merge: keep a valid LLM suggestion per field, else fall back to that field's guess.
    merged: dict[str, MappingSuggestion] = {}
    valid_paths = {e.path for e in catalogue}
    for field in form_fields:
        merged[field.name] = _coerce_llm_entry(
            llm.get(field.name), field, valid_paths, heuristic[field.name]
        )
    return merged


# --- llm provider -------------------------------------------------------------


def _coerce_llm_entry(
    raw: object,
    field: TemplateFormField,
    valid_paths: set[str],
    fallback: MappingSuggestion,
) -> MappingSuggestion:
    """Validate one LLM field entry; any problem falls back to the heuristic guess."""
    if not isinstance(raw, dict):
        return fallback
    is_signature = bool(raw.get("is_signature")) or field.kind == "signature"
    field_path = raw.get("field_path")
    if field_path is not None:
        field_path = str(field_path)
        if field_path not in valid_paths:
            return fallback  # hallucinated path -> trust the offline guess instead
    if field_path is None and not is_signature:
        return fallback
    try:
        confidence = float(raw["confidence"]) if raw.get("confidence") is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None:
        confidence = min(max(confidence, 0.0), 1.0)
    rationale = raw.get("rationale")
    return MappingSuggestion(
        field_path=None if is_signature else field_path,
        confidence=confidence,
        source="ai",
        is_signature=is_signature,
        rationale=str(rationale) if rationale is not None else None,
    )


def _suggest_llm(
    doc_type: str, form_fields: list[TemplateFormField], catalogue: list[FieldCatalogueEntry]
) -> dict:
    """Single OpenRouter call returning ``{pdf_field: {field_path, confidence, ...}}``."""
    import openai  # lazy: optional dep

    client = openai.OpenAI(api_key=settings.openrouter_api_key, base_url=settings.mapping_base_url)
    response = client.chat.completions.create(
        model=settings.mapping_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(doc_type, form_fields, catalogue)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return payload if isinstance(payload, dict) else {}


_SYSTEM_PROMPT = (
    "You map a fillable PDF's form fields onto a catalogue of extractable data fields. "
    "For each PDF field, choose the single best catalogue path (or null if none fits). "
    "Signature fields are stamped, not filled: mark them is_signature=true with a null "
    'field_path. Respond ONLY with a JSON object keyed by the PDF field name: '
    '{"<pdf_field>": {"field_path": "<catalogue path>"|null, "confidence": 0.0-1.0, '
    '"is_signature": true|false, "rationale": "short"}}.'
)


def _build_prompt(
    doc_type: str, form_fields: list[TemplateFormField], catalogue: list[FieldCatalogueEntry]
) -> str:
    """Compact prompt body: the PDF field list and the bindable catalogue."""
    field_lines = [
        f"- {f.name} (kind={f.kind}"
        + (f", label={f.nearby_label!r}" if f.nearby_label else "")
        + ")"
        for f in form_fields
    ]
    catalogue_lines = [f"- {e.path} — {e.label} ({e.kind})" for e in catalogue]
    return (
        f"Document type: {doc_type}\n\n"
        f"PDF form fields to map:\n" + "\n".join(field_lines) + "\n\n"
        f"Bindable catalogue paths:\n" + "\n".join(catalogue_lines) + "\n\n"
        "Return the JSON mapping object."
    )
