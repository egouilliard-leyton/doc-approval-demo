"""Phase 2 case-decision stage: a reconciled case -> approve | flag | needs_review.

Mirrors the single-document decision stage (:mod:`app.pipeline.agent`) but case-shaped.
Deterministic cross-document checks run in code (:func:`cross_case_checks`); an optional
LLM adds qualitative judgment it can never use to override a failed check. The two are
combined under the SAME fixed precedence as the single-doc path — ``agent._reconcile`` is
imported and REUSED verbatim, never reimplemented.

The DEFAULT path is fully OFFLINE: with the ``mock``/empty provider no network is touched
(``llm_decision`` stays ``None`` and the decision comes purely from the deterministic
checks). Only the explicit ``llm`` provider makes a single OpenRouter call, imported lazily
and degrading to no-judgment on any failure. Tests run offline.

Locked product decision: a cross-document CONFLICT (fields disagree) and a MISSING required
document are "flag for a human" -> severity ``"review"`` (which ``_reconcile`` caps at
``needs_review``), never a hard ``flag``.
"""

from __future__ import annotations

import json
import logging
from statistics import mean

from app.config import settings
from app.pipeline.agent import _reconcile
from app.schemas import CaseDecisionResult, CaseReconciliation, Check, Citation

logger = logging.getLogger(__name__)

PROVIDERS = {"llm", "mock"}

_VALID_DECISIONS = {"approve", "flag", "needs_review"}


# --- deterministic cross-document checks --------------------------------------


def cross_case_checks(reconciliation: CaseReconciliation, members, case_type_defn) -> list[Check]:
    """Authoritative, code-computed cross-document checks (parallels ``cross_cutting_checks``).

    Two families, both surfaced (passing checks listed for visibility, as ``agent.py`` does):

    * **Conflict** — a canonical field whose sources disagree (``agreement is False``) fails a
      ``severity="review"`` check, so the case routes to human review (the locked conflict
      policy). NEVER ``"hard"``: a disagreement is a flag-for-a-human, not an auto-reject.
    * **Completeness** (defined case types only) — for each required member doc-type
      (``min_count >= 1``): a doc-type with no member at all fails ``review``; one present but
      not yet structured fails ``advisory`` (a note only, never caps the decision).
    """
    checks: list[Check] = []

    # 1. Conflict checks over the reconciled canonical fields.
    for field in reconciliation.canonical_fields:
        if field.agreement is False:
            checks.append(
                Check(
                    name=f"conflict:{field.name}",
                    passed=False,
                    detail=field.conflict_detail or f"sources disagree on {field.name}",
                    severity="review",
                )
            )
        elif field.value is not None:
            checks.append(
                Check(
                    name=f"conflict:{field.name}",
                    passed=True,
                    detail=f"sources agree on {field.name} = {field.value}",
                    severity="review",
                )
            )

    # 2. Completeness checks — use the FULL member list (including unstructured members).
    if case_type_defn is not None:
        for member_def in case_type_defn.members:
            if member_def.min_count < 1:
                continue  # optional member — nothing to require
            present = [m for m in members if getattr(m, "doc_type", None) == member_def.doc_type]
            if not present:
                checks.append(
                    Check(
                        name=f"missing:{member_def.doc_type}",
                        passed=False,
                        detail="required document not uploaded",
                        severity="review",
                    )
                )
            elif not any(getattr(m, "structured", None) is not None for m in present):
                checks.append(
                    Check(
                        name=f"unstructured:{member_def.doc_type}",
                        passed=False,
                        detail="required document present but not yet structured",
                        severity="advisory",
                    )
                )
            else:
                checks.append(
                    Check(
                        name=f"present:{member_def.doc_type}",
                        passed=True,
                        detail="required document present and structured",
                        severity="advisory",
                    )
                )
    return checks


# --- decision -----------------------------------------------------------------


def run_case_decision(
    reconciliation: CaseReconciliation,
    members,
    case_type_defn,
    provider: str = "",
) -> CaseDecisionResult:
    """Decide a reconciled case (approve | flag | needs_review)."""
    # Deliberate OFFLINE default: the case-decision stage never touches the network unless
    # the caller explicitly asks for the "llm" provider (mirrors how agent.run_decision's
    # mock/empty provider stays offline). The demo default + all tests run fully offline.
    provider = provider or "mock"
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown case decision provider '{provider}'. Available: {', '.join(sorted(PROVIDERS))}"
        )

    # 1. Authoritative, code-computed cross-document checks.
    checks = cross_case_checks(reconciliation, members, case_type_defn)

    # 2. Extraction confidence: mean over the structured members (0.0 if none).
    confidences = [
        m.structured.extraction_confidence
        for m in members
        if getattr(m, "structured", None) is not None
    ]
    extraction_confidence = mean(confidences) if confidences else 0.0

    # 3. Optional qualitative judgment. Offline (mock/empty) -> no network, no LLM decision.
    llm_decision: str | None = None
    llm_conf: float = extraction_confidence
    llm_reasons: list[str] = []
    if provider == "llm":
        judgment = _decide_llm_case(reconciliation, checks, extraction_confidence)
        if judgment is not None:
            llm_decision, llm_conf, llm_reasons = judgment

    # 4. Reconcile under the SAME fixed precedence as the single-doc path (imported verbatim).
    #    With no LLM the base decision falls back to "approve", so a clean, complete case
    #    auto-approves while any failed review check (conflict / missing doc) caps at
    #    needs_review — the LLM can never override that.
    decision, confidence, reasons = _reconcile(
        checks, llm_decision or "approve", llm_conf, llm_reasons, extraction_confidence
    )

    # 5. Citations: one per contributing document per reconciled field (document_id set).
    citations: list[Citation] = [
        citation for field in reconciliation.canonical_fields for citation in field.citations
    ]

    status = "needs_review" if decision == "needs_review" else "decided"

    return CaseDecisionResult(
        case_id=reconciliation.case_id,
        case_type=reconciliation.case_type,
        status=status,
        decision=decision,
        confidence=confidence,
        reasons=reasons,
        checks=checks,
        citations=citations,
        llm_decision=llm_decision,
    )


# --- providers ----------------------------------------------------------------


def _decide_llm_case(
    reconciliation: CaseReconciliation, checks: list[Check], extraction_confidence: float
) -> tuple[str, float, list[str]] | None:
    """Single OpenRouter call returning ``{decision, confidence, reasons}``, or ``None``.

    Mirrors :func:`app.pipeline.agent._decide_llm`: the OpenAI-compatible client is imported
    LAZILY (optional dep) and constructed inside the function, so the network is only ever
    touched here. ANY failure — missing key, missing dep, unparsable / invalid output —
    degrades to ``None`` (no judgment) rather than raising into the request path.
    """
    try:
        if not settings.openrouter_api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not set; the llm case decision provider needs it."
            )

        import openai  # lazy: optional dep

        client = openai.OpenAI(
            api_key=settings.openrouter_api_key, base_url=settings.decision_base_url
        )
        response = client.chat.completions.create(
            model=settings.decision_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_prompt(reconciliation, checks, extraction_confidence),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001 — degrade gracefully to no judgment
        logger.warning("case decision LLM failed for %s: %s", reconciliation.case_id, exc)
        return None

    decision = payload.get("decision")
    if decision not in _VALID_DECISIONS:
        return None
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)
    raw_reasons = payload.get("reasons") or []
    reasons = [str(r) for r in raw_reasons] if isinstance(raw_reasons, list) else [str(raw_reasons)]
    return decision, confidence, reasons


_SYSTEM_PROMPT = (
    "You are an approvals assistant reconciling a CASE — a set of related documents (e.g. "
    "an invoice, a purchase order, a contract). You are given the case's reconciled canonical "
    "fields (whether the documents agree on each) and the results of deterministic checks "
    "already computed in code. The code checks are authoritative — do not contradict a failed "
    "check; explain it. Respond ONLY with a JSON object: "
    '{"decision": "approve"|"flag"|"needs_review", "confidence": 0.0-1.0, '
    '"reasons": ["short bullet", ...]}.'
)


def _build_prompt(
    reconciliation: CaseReconciliation, checks: list[Check], extraction_confidence: float
) -> str:
    """Compact, deterministic prompt body (canonical-field agreements + the check trace)."""
    field_lines = [
        f"- {f.name} [{f.kind}]: {'AGREE' if f.agreement else 'CONFLICT'} value={f.value!r}"
        + (f" — {f.conflict_detail}" if f.conflict_detail else "")
        for f in reconciliation.canonical_fields
    ]
    check_lines = [
        f"- {c.name} [{c.severity}]: {'PASS' if c.passed else 'FAIL'} — {c.detail}"
        for c in checks
    ]
    return (
        f"Case type: {reconciliation.case_type or 'open pile'}\n"
        f"Members: {reconciliation.member_count} "
        f"({reconciliation.structured_count} structured)\n\n"
        "Reconciled canonical fields:\n" + "\n".join(field_lines) + "\n\n"
        "Deterministic checks:\n" + "\n".join(check_lines) + "\n\n"
        f"Overall extraction confidence: {extraction_confidence:.2f}\n\n"
        "Give your decision, confidence, and concise reasons."
    )
