"""Phase 2 case-decision unit tests. Hand-built objects, NO DB/HTTP/network.

Mirrors ``test_agent.py``'s idiom: construct the reconciliation + members in code and prove
the deterministic cross-document checks reconcile with — and override — the LLM judgment.
The locked policy is that a CONFLICT or a MISSING required document routes to needs_review
(severity ``review``), never a hard ``flag``.
"""

from types import SimpleNamespace

from app import case_decision
from app.case_decision import cross_case_checks, run_case_decision
from app.case_type_definition import CaseTypeDefinition, CaseTypeMemberDef
from app.schemas import CanonicalFieldResult, CaseReconciliation, Citation


# --- builders -----------------------------------------------------------------


def _field(
    name: str,
    value,
    agreement: bool = True,
    conflict_detail: str | None = None,
    kind: str = "money",
    doc_ids: tuple[str, ...] = ("d1",),
) -> CanonicalFieldResult:
    return CanonicalFieldResult(
        name=name,
        value=value,
        agreement=agreement,
        kind=kind,
        candidates=[],
        conflict_detail=conflict_detail,
        citations=[Citation(field=name, source="page 1", document_id=d) for d in doc_ids],
    )


def _recon(fields: list[CanonicalFieldResult], member_count: int = 2, structured_count: int = 2) -> CaseReconciliation:
    return CaseReconciliation(
        case_id="c1",
        case_type="test_case",
        status="reconciled",
        canonical_fields=fields,
        member_count=member_count,
        structured_count=structured_count,
    )


def _member(doc_type: str, conf: float = 0.9, structured: bool = True) -> SimpleNamespace:
    struct = SimpleNamespace(extraction_confidence=conf) if structured else None
    return SimpleNamespace(document_id=f"{doc_type}-doc", doc_type=doc_type, structured=struct)


def _defn(*required_doc_types: str) -> CaseTypeDefinition:
    return CaseTypeDefinition(
        name="test_case",
        label="Test",
        members=[CaseTypeMemberDef(doc_type=dt, min_count=1, max_count=1) for dt in required_doc_types],
    )


# --- tests --------------------------------------------------------------------


def test_all_agree_complete_case_approves():
    defn = _defn("invoice", "contract")
    recon = _recon(
        [
            _field("total_amount", 100.0, doc_ids=("invoice-doc", "contract-doc")),
            _field("vendor_name", "Acme", kind="string", doc_ids=("invoice-doc", "contract-doc")),
        ]
    )
    members = [_member("invoice"), _member("contract")]

    result = run_case_decision(recon, members, defn, provider="mock")
    assert result.decision == "approve"
    assert result.status == "decided"
    assert result.llm_decision is None  # offline: no network, no LLM judgment
    assert result.checks, "expected a cross-document check trace"
    assert result.citations, "expected citations from the reconciled fields"


def test_conflict_routes_to_needs_review_not_flag():
    defn = _defn("invoice", "contract")
    recon = _recon(
        [
            _field(
                "total_amount",
                100.0,
                agreement=False,
                conflict_detail="invoice: 100.0; contract: 999999.0",
                doc_ids=("invoice-doc", "contract-doc"),
            ),
        ]
    )
    members = [_member("invoice"), _member("contract")]

    result = run_case_decision(recon, members, defn, provider="mock")
    assert result.decision == "needs_review"
    assert result.decision != "flag"  # a disagreement is a review, never an auto-reject
    conflict = next(c for c in result.checks if c.name == "conflict:total_amount")
    assert not conflict.passed and conflict.severity == "review"


def test_missing_required_member_routes_to_needs_review():
    defn = _defn("invoice", "po")
    recon = _recon(
        [_field("total_amount", 100.0, doc_ids=("invoice-doc",))],
        member_count=1,
        structured_count=1,
    )
    members = [_member("invoice")]  # the required "po" member is absent

    result = run_case_decision(recon, members, defn, provider="mock")
    assert result.decision == "needs_review"
    missing = next(c for c in result.checks if c.name == "missing:po")
    assert not missing.passed and missing.severity == "review"


def test_llm_cannot_override_failed_review_check(monkeypatch):
    """Even a forced LLM 'approve' still yields needs_review when a review check failed —
    the deterministic precedence (reused verbatim from agent._reconcile) wins."""
    monkeypatch.setattr(
        case_decision,
        "_decide_llm_case",
        lambda *a, **k: ("approve", 0.99, ["forced approve"]),
    )
    defn = _defn("invoice", "contract")
    recon = _recon(
        [
            _field(
                "total_amount",
                100.0,
                agreement=False,
                conflict_detail="conflict",
                doc_ids=("invoice-doc", "contract-doc"),
            ),
        ]
    )
    members = [_member("invoice"), _member("contract")]

    result = run_case_decision(recon, members, defn, provider="llm")
    assert result.llm_decision == "approve"  # the LLM proposed approve
    assert result.decision == "needs_review"  # ...but the review check capped it


def test_llm_provider_offline_degrades_to_no_judgment(monkeypatch):
    """With no API key the real _decide_llm_case degrades to None (still offline), so the
    decision comes purely from the deterministic checks."""
    monkeypatch.setattr(case_decision.settings, "openrouter_api_key", "")
    defn = _defn("invoice", "contract")
    recon = _recon([_field("total_amount", 100.0, doc_ids=("invoice-doc", "contract-doc"))])
    members = [_member("invoice"), _member("contract")]

    result = run_case_decision(recon, members, defn, provider="llm")
    assert result.llm_decision is None
    assert result.decision == "approve"


def test_cross_case_checks_open_pile_skips_completeness():
    """An open pile (case_type_defn is None) emits conflict checks but no completeness checks."""
    recon = _recon([_field("total_amount", 100.0, doc_ids=("invoice-doc", "contract-doc"))])
    members = [_member("invoice"), _member("contract")]

    checks = cross_case_checks(recon, members, None)
    assert any(c.name == "conflict:total_amount" for c in checks)
    assert not any(c.name.startswith(("missing:", "unstructured:", "present:")) for c in checks)
