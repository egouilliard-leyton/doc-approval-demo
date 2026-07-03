"""Phase 2 classify stage: OCR text -> a doc-type guess (+ candidate ranking).

Two providers behind one entrypoint, mirroring the OCR / structuring / decision layers:

* ``heuristic`` — the DEFAULT and fully OFFLINE. For each registered doc type, the
  extraction vocabulary (its ``extraction_classes`` split into tokens) is matched against
  the OCR ``full_text``; the fraction of vocabulary tokens present scores the type, and
  the scores are normalized into a confidence distribution. No network, deterministic.
* ``llm`` — optional. A single OpenRouter call (OpenAI-compatible client) imported LAZILY
  so the app boots and tests run without the ``openai`` dep; ANY failure degrades to a
  no-guess result (``doc_type=None``, ``confidence=0.0``, no candidates) plus a warning.

The classifier is advisory: the user confirms/corrects the guess before extraction
commits (the "auto-classify + confirm" decision), so a wrong or empty guess is safe.
"""

from __future__ import annotations

import logging
import re

from app import doc_types
from app.config import settings
from app.models import Document
from app.schemas import ClassifyCandidate, ClassifyResult, OCRResult

logger = logging.getLogger(__name__)

PROVIDERS = {"heuristic", "llm"}

# Split a doc type's extraction-class labels into lowercase word tokens on ``_``.
_TOKEN_SPLIT = re.compile(r"_+")


def run_classify(doc: Document, ocr_result: OCRResult, provider: str = "") -> ClassifyResult:
    """Guess a document's doc-type from its OCR text, with a ranked candidate list."""
    provider = provider or settings.classify_provider
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown classify provider '{provider}'. Available: {', '.join(sorted(PROVIDERS))}"
        )

    if provider == "llm":
        return _classify_llm(doc, ocr_result)
    return _classify_heuristic(doc, ocr_result)


# --- providers ----------------------------------------------------------------


def _vocabulary(name: str) -> set[str]:
    """The lowercase token vocabulary for a doc type (its extraction classes, split)."""
    tokens: set[str] = set()
    for cls in doc_types.get_spec(name).extraction_classes:
        for token in _TOKEN_SPLIT.split(cls.lower()):
            if token:
                tokens.add(token)
    return tokens


def _classify_heuristic(doc: Document, ocr_result: OCRResult) -> ClassifyResult:
    """Offline classifier: fraction of each doc type's vocabulary present in the text.

    Each doc type scores as the fraction of its vocabulary tokens found (word-boundary
    match) in the lowercased OCR ``full_text``. Raw scores are normalized into a
    confidence distribution (each divided by their sum); the argmax is the guess, or
    ``None`` when every score is zero. Candidates are returned sorted best-first.
    """
    text = ocr_result.full_text.lower()
    raw: dict[str, float] = {}
    for name in doc_types.list_names():
        vocab = _vocabulary(name)
        if not vocab:
            raw[name] = 0.0
            continue
        hits = sum(1 for token in vocab if _token_in_text(token, text))
        raw[name] = hits / len(vocab)

    total = sum(raw.values())
    if total > 0:
        norm = {name: score / total for name, score in raw.items()}
    else:
        norm = {name: 0.0 for name in raw}

    candidates = sorted(
        (ClassifyCandidate(doc_type=name, score=round(score, 4)) for name, score in norm.items()),
        key=lambda c: (-c.score, c.doc_type),
    )
    top = candidates[0] if candidates else None
    doc_type = top.doc_type if top is not None and top.score > 0 else None
    confidence = top.score if doc_type is not None else 0.0
    return ClassifyResult(
        document_id=doc.id,
        provider="heuristic",
        doc_type=doc_type,
        confidence=round(confidence, 4),
        candidates=candidates,
    )


def _token_in_text(token: str, text: str) -> bool:
    """Whether ``token`` occurs as a whole word in the (already-lowercased) ``text``."""
    return re.search(rf"\b{re.escape(token)}\b", text) is not None


def _classify_llm(doc: Document, ocr_result: OCRResult) -> ClassifyResult:
    """Optional LLM classifier over OpenRouter; degrades to a no-guess on any failure.

    Lazily constructs the OpenAI-compatible client INSIDE the function (never at import
    time), so the network is only ever touched here. Any exception — missing key, missing
    dep, bad response, unregistered guess — is logged and swallowed into a no-guess
    result, so the classify call never raises.
    """
    empty = ClassifyResult(
        document_id=doc.id, provider="llm", doc_type=None, confidence=0.0, candidates=[]
    )
    try:
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set; the llm classifier needs it.")

        import openai  # lazy: optional dep

        client = openai.OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.classify_base_url or settings.structuring_base_url,
        )
        names = doc_types.list_names()
        prompt = (
            "Classify the following document into exactly one of these types: "
            f"{', '.join(names)}. Reply with ONLY the type name.\n\n"
            f"{ocr_result.full_text[: settings.structuring_max_char_buffer]}"
        )
        response = client.chat.completions.create(
            model=settings.classify_model or settings.structuring_model,
            messages=[{"role": "user", "content": prompt}],
        )
        guess = (response.choices[0].message.content or "").strip().lower()
        if not doc_types.is_registered(guess):
            raise ValueError(f"llm returned an unregistered doc_type {guess!r}")
        return ClassifyResult(
            document_id=doc.id,
            provider="llm",
            doc_type=guess,
            confidence=1.0,
            candidates=[ClassifyCandidate(doc_type=guess, score=1.0)],
        )
    except Exception as exc:  # noqa: BLE001 - classify never raises; degrade to no-guess
        logger.warning("LLM classify failed for %s: %s", doc.id, exc)
        return empty
