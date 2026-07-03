"""Phase 2 reconciler unit tests. PURE — hand-built members, no DB / no HTTP / no network."""

import types

from app.case_type_definition import AP_MATCH_DEFINITION, CaseTypeDefinition
from app.config import settings
from app.models import DocumentStatus
from app.reconcile import reconcile_case
from app.schemas import CaseReconciliation, StructuredResult


# --- builders (mirror test_agent.py's in-memory StructuredResult construction) ----


def fv(value, conf=0.9, page: int | None = 1) -> dict:
    """A FieldValue node as it appears in a dumped StructuredResult.fields."""
    grounding = (
        {"page": page, "char_start": 0, "char_end": 1, "snippet": str(value), "alignment": "exact"}
        if page is not None
        else None
    )
    return {"value": value, "confidence": conf, "grounding": grounding}


def _member(document_id: str, doc_type: str, fields: dict):
    """A case member: document_id + doc_type + its persisted structured result."""
    structured = StructuredResult(
        document_id=document_id,
        status=DocumentStatus.structured,
        doc_type=doc_type,
        provider="mock",
        model="mock",
        ocr_engine="mock",
        fields=fields,
        extraction_confidence=0.9,
    )
    return types.SimpleNamespace(document_id=document_id, doc_type=doc_type, structured=structured)


def _case(case_type: str | None = "ap_match", cid: str = "case1"):
    return types.SimpleNamespace(id=cid, case_type=case_type)


def _field(result: CaseReconciliation, name: str):
    return next(f for f in result.canonical_fields if f.name == name)


# --- money -------------------------------------------------------------------


def test_money_agreement_within_tolerance():
    members = [
        _member("d1", "invoice", {"total": fv(135.00)}),
        _member("d2", "contract", {"total_value": fv(135.009)}),  # within 0.01 abs tol
    ]
    result = reconcile_case(_case(), AP_MATCH_DEFINITION, members)
    ta = _field(result, "total_amount")
    assert ta.kind == "money"
    assert ta.agreement is True
    assert ta.conflict_detail is None
    assert ta.value == 135.00  # first non-null candidate in document order
    assert len(ta.candidates) == 2
    # one citation per contributing document, each carrying its document_id.
    assert {c.document_id for c in ta.citations} == {"d1", "d2"}


def test_money_conflict_beyond_tolerance():
    members = [
        _member("d1", "invoice", {"total": fv(135.00)}),
        _member("d2", "contract", {"total_value": fv(200.00)}),
    ]
    result = reconcile_case(_case(), AP_MATCH_DEFINITION, members)
    ta = _field(result, "total_amount")
    assert ta.agreement is False
    assert ta.conflict_detail is not None
    assert "135.0" in ta.conflict_detail and "200.0" in ta.conflict_detail


# --- string / fuzzy + scalar-vs-list exists-match ----------------------------


def test_vendor_scalar_vs_parties_list_exists_match_no_false_conflict():
    """A scalar vendor must match SOME party, not every party (exists-match)."""
    members = [
        _member("d1", "invoice", {"vendor": fv("Acme Robotics Inc")}),
        _member(
            "d2",
            "contract",
            {"parties": [fv("Beta Corp"), fv("Acme Robotics Inc")]},  # 1:N
        ),
    ]
    result = reconcile_case(_case(), AP_MATCH_DEFINITION, members)
    vn = _field(result, "vendor_name")
    assert vn.kind == "string"
    assert vn.agreement is True  # matches the second party despite Beta Corp not matching
    assert len(vn.candidates) == 3  # 1 vendor + 2 parties, all listed


def test_string_fuzzy_match_agrees(monkeypatch):
    # "Acme Ltd" vs "Acme Limited" have a SequenceMatcher ratio of 0.8, so they agree
    # under a fuzzy threshold at/below that. Exercise the fuzzy branch at 0.75.
    monkeypatch.setattr(settings, "reconcile_string_fuzzy_threshold", 0.75)
    members = [
        _member("d1", "invoice", {"vendor": fv("Acme Ltd")}),
        _member("d2", "contract", {"parties": [fv("Acme Limited")]}),
    ]
    result = reconcile_case(_case(), AP_MATCH_DEFINITION, members)
    assert _field(result, "vendor_name").agreement is True


def test_company_suffix_names_agree_at_default_threshold():
    """Legal-suffix variants of one company agree WITHOUT loosening the fuzzy threshold.

    At the default 0.85 threshold the raw fuzzy ratio of "Acme Ltd"/"Acme Limited" (0.8) is
    NOT enough; suffix normalization reduces both to "acme" so they exact-match instead.
    """
    assert settings.reconcile_string_fuzzy_threshold == 0.85  # threshold untouched
    for a, b in [
        ("Acme Ltd", "Acme Limited"),
        ("Acme Ltd", "Acme Limited Company"),
        ("Acme Limited", "Acme Limited Company"),
    ]:
        members = [
            _member("d1", "invoice", {"vendor": fv(a)}),
            _member("d2", "contract", {"parties": [fv(b)]}),
        ]
        result = reconcile_case(_case(), AP_MATCH_DEFINITION, members)
        vn = _field(result, "vendor_name")
        assert vn.agreement is True, (a, b)
        assert vn.conflict_detail is None, (a, b)


def test_genuinely_different_vendor_still_conflicts():
    """Suffix normalization must not conflate two DIFFERENT companies."""
    members = [
        _member("d1", "invoice", {"vendor": fv("Acme Ltd")}),
        _member("d2", "contract", {"parties": [fv("Globex Inc")]}),
    ]
    result = reconcile_case(_case(), AP_MATCH_DEFINITION, members)
    vn = _field(result, "vendor_name")
    assert vn.agreement is False
    assert vn.conflict_detail is not None


def test_values_agree_strips_legal_suffixes():
    """Focused unit test on the string comparator's company-suffix normalization."""
    from app.reconcile.tolerance import values_agree

    assert values_agree("string", "Acme Ltd", "Acme Limited", settings) is True
    assert values_agree("string", "Acme Ltd.", "Acme Limited Company", settings) is True
    assert values_agree("string", "Acme Ltd", "Globex Inc", settings) is False
    # A name that is ENTIRELY a suffix token never collapses to empty (which would make
    # every all-suffix name spuriously agree).
    assert values_agree("string", "Company", "Limited", settings) is False


# --- date --------------------------------------------------------------------


_DATE_CASE_TYPE = CaseTypeDefinition(
    name="date_case",
    label="Date Case",
    canonical_fields={
        "the_date": [
            {"doc_type": "invoice", "field_path": "invoice_date"},
            {"doc_type": "contract", "field_path": "effective_date"},
        ]
    },
)


def test_date_within_tolerance_agrees():
    members = [
        _member("d1", "invoice", {"invoice_date": fv("2024-03-01")}),
        _member("d2", "contract", {"effective_date": fv("2024-03-03")}),  # 2 days apart
    ]
    result = reconcile_case(_case("date_case"), _DATE_CASE_TYPE, members)
    td = _field(result, "the_date")
    assert td.kind == "date"
    assert td.agreement is True


def test_date_beyond_tolerance_conflicts():
    members = [
        _member("d1", "invoice", {"invoice_date": fv("2024-03-01")}),
        _member("d2", "contract", {"effective_date": fv("2024-03-10")}),  # 9 > 3 days
    ]
    result = reconcile_case(_case("date_case"), _DATE_CASE_TYPE, members)
    td = _field(result, "the_date")
    assert td.agreement is False
    assert td.conflict_detail is not None


# --- 1:1, single-document, and absent bags -----------------------------------


def test_one_to_one_and_single_document_field_agree():
    members = [
        _member("d1", "invoice", {"total": fv(135.00), "po_number": fv("PO-1")}),
        _member("d2", "contract", {"total_value": fv(135.00)}),
    ]
    result = reconcile_case(_case(), AP_MATCH_DEFINITION, members)
    # total_amount is a 1:1 pair -> agrees.
    assert _field(result, "total_amount").agreement is True
    # po_number is sourced from the invoice only -> a single document -> agrees, no conflict.
    po = _field(result, "po_number")
    assert po.agreement is True
    assert po.conflict_detail is None
    assert po.value == "PO-1"
    assert result.member_count == 2
    assert result.structured_count == 2


def test_absent_canonical_field_is_not_a_conflict():
    """A canonical field no member supplies -> no value, agrees (missing signal)."""
    members = [_member("d1", "invoice", {"total": fv(135.00)})]
    result = reconcile_case(_case(), AP_MATCH_DEFINITION, members)
    vn = _field(result, "vendor_name")  # no vendor / parties supplied
    assert vn.value is None
    assert vn.agreement is True
    assert vn.conflict_detail is None


# --- open-pile inference -----------------------------------------------------


def test_open_pile_infers_overlapping_field_across_two_docs():
    members = [
        _member("d1", "invoice", {"total": fv(100.00), "vendor": fv("Acme")}),
        _member("d2", "invoice", {"total": fv(100.005), "invoice_no": fv("X-1")}),
    ]
    result = reconcile_case(_case(None), None, members)
    names = {f.name for f in result.canonical_fields}
    # "total" appears (non-null) in both docs -> canonical; "vendor"/"invoice_no" don't.
    assert "total" in names
    assert "vendor" not in names and "invoice_no" not in names
    total = _field(result, "total")
    assert total.kind == "money"
    assert total.agreement is True
