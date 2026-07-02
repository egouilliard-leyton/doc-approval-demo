"""Offline tests for the declarative rule format + generic interpreter (Phase 2).

Each primitive is exercised directly for its ``(passed, severity)`` contract, and the
two shipped types are checked for parity: ``build_ruleset(INVOICE_RULE_DEFINITION)`` /
``CONTRACT_RULE_DEFINITION`` must reproduce the exact ``(name, passed, severity)`` the
original hand-written ``invoice_checks`` / ``contract_checks`` produced.
"""

from datetime import date, timedelta

from app.rules import DecisionContext
from app.rules.contract import CONTRACT_RULE_DEFINITION
from app.rules.definition import (
    AggregateRuleDef,
    ArithmeticIdentityRuleDef,
    CodedRuleDef,
    DateConstraintRuleDef,
    DocTypeRuleDefinition,
    EqualityRuleDef,
    ExpressionRuleDef,
    FieldDependencyRuleDef,
    FormatRuleDef,
    LlmAdvisoryRuleDef,
    NumericRangeRuleDef,
    PercentageToleranceRuleDef,
    PresenceRuleDef,
    SetMembershipRuleDef,
    ThresholdCompareRuleDef,
    UniquenessVsHistoryRuleDef,
    _interpret,
    build_ruleset,
)
from app.rules.invoice import INVOICE_RULE_DEFINITION
from app.schemas import Check


def fv(value, conf=0.9, page: int | None = 1) -> dict:
    """A FieldValue node as it appears in a dumped StructuredResult.fields."""
    grounding = (
        {"page": page, "char_start": 0, "char_end": 1, "snippet": str(value), "alignment": "exact"}
        if page is not None
        else None
    )
    return {"value": value, "confidence": conf, "grounding": grounding}


def ctx(**kw) -> DecisionContext:
    kw.setdefault("extraction_confidence", 0.9)
    return DecisionContext(**kw)


def run(defn, fields, c=None):
    return build_ruleset(defn)(fields, c or ctx())


def by_name(checks):
    return {c.name: c for c in checks}


# --- primitives: PresenceRuleDef ----------------------------------------------


def test_presence_pass_and_fail():
    rule = PresenceRuleDef(name="p", field_path="x", severity="hard")
    ok = _interpret(rule, {"x": fv("v")}, ctx())
    assert ok.passed and ok.severity == "hard"
    bad = _interpret(rule, {}, ctx())
    assert not bad.passed and bad.severity == "hard"


# --- primitives: ThresholdCompareRuleDef --------------------------------------


def test_threshold_literal_pass_fail_and_ops():
    lte = ThresholdCompareRuleDef(name="t", field_path="v", severity="review", op="lte", threshold=100.0)
    assert _interpret(lte, {"v": fv(50.0)}, ctx()).passed
    assert not _interpret(lte, {"v": fv(150.0)}, ctx()).passed
    gt = ThresholdCompareRuleDef(name="t", field_path="v", severity="review", op="gt", threshold=100.0)
    assert _interpret(gt, {"v": fv(150.0)}, ctx()).passed
    assert not _interpret(gt, {"v": fv(50.0)}, ctx()).passed


def test_threshold_skips_when_field_absent():
    rule = ThresholdCompareRuleDef(name="t", field_path="v", severity="review", threshold=10.0)
    assert _interpret(rule, {}, ctx()) is None
    assert _interpret(rule, {"v": fv("not-a-number")}, ctx()) is None


def test_threshold_resolves_setting_at_call_time():
    rule = ThresholdCompareRuleDef(
        name="t", field_path="total", severity="review", op="lte",
        threshold_setting="invoice_auto_approve_max",
    )
    # default invoice_auto_approve_max == 10000.0
    assert _interpret(rule, {"total": fv(5000.0)}, ctx()).passed
    assert not _interpret(rule, {"total": fv(50000.0)}, ctx()).passed

    from app.config import settings as _settings
    saved = _settings.invoice_auto_approve_max
    try:
        _settings.invoice_auto_approve_max = 200.0
        assert not _interpret(rule, {"total": fv(5000.0)}, ctx()).passed  # 5000 > 200 -> fail
    finally:
        _settings.invoice_auto_approve_max = saved


# --- primitives: ArithmeticIdentityRuleDef (only covered here) ----------------


def _arith(tolerance=0.0):
    return ArithmeticIdentityRuleDef(
        name="math", result_path="total", addend_a_path="subtotal",
        addend_b_path="tax", severity="hard", tolerance=tolerance,
    )


def test_arithmetic_identity_pass():
    fields = {"total": fv(110.0), "subtotal": fv(100.0), "tax": fv(10.0)}
    out = _interpret(_arith(), fields, ctx())
    assert out.passed and out.severity == "hard"


def test_arithmetic_identity_fail():
    fields = {"total": fv(200.0), "subtotal": fv(100.0), "tax": fv(10.0)}
    out = _interpret(_arith(), fields, ctx())
    assert not out.passed and out.severity == "hard"


def test_arithmetic_identity_skips_when_absent():
    assert _interpret(_arith(), {"total": fv(110.0), "subtotal": fv(100.0)}, ctx()) is None
    assert _interpret(_arith(), {}, ctx()) is None


def test_arithmetic_identity_tolerance():
    fields = {"total": fv(110.5), "subtotal": fv(100.0), "tax": fv(10.0)}
    assert _interpret(_arith(tolerance=1.0), fields, ctx()).passed
    assert not _interpret(_arith(tolerance=0.1), fields, ctx()).passed


# --- primitives: UniquenessVsHistoryRuleDef -----------------------------------


def test_uniqueness_skips_when_absent():
    rule = UniquenessVsHistoryRuleDef(name="dup", field_path="invoice_no")
    assert _interpret(rule, {}, ctx()) is None


def test_uniqueness_hard_fail_on_duplicate():
    rule = UniquenessVsHistoryRuleDef(name="dup", field_path="invoice_no")
    fields = {"invoice_no": fv("INV-1")}
    assert _interpret(rule, fields, ctx()).passed  # not in history
    dup = _interpret(rule, fields, ctx(prior_invoice_numbers={"INV-1"}))
    assert not dup.passed and dup.severity == "hard"


# --- primitives: SetMembershipRuleDef -----------------------------------------


def test_set_membership_absent_advisory_pass():
    rule = SetMembershipRuleDef(
        name="law", field_path="governing_law", severity="review",
        allowed_list=["Delaware"], absent_behavior="advisory_pass", absent_severity="advisory",
    )
    out = _interpret(rule, {}, ctx())
    assert out.passed and out.severity == "advisory"


def test_set_membership_empty_list_skipped():
    rule = SetMembershipRuleDef(
        name="law", field_path="governing_law", severity="review",
        allowed_list=[], empty_list_behavior="skip",
    )
    assert _interpret(rule, {"governing_law": fv("Delaware")}, ctx()) is None


def test_set_membership_empty_list_and_field_absent_emits_advisory_pass():
    """Absent-field wins over empty-list: emit advisory pass (matches original ordering)."""
    rule = SetMembershipRuleDef(
        name="law", field_path="governing_law", severity="review",
        allowed_list=[], empty_list_behavior="skip",
        absent_behavior="advisory_pass", absent_severity="advisory",
    )
    out = _interpret(rule, {}, ctx())
    assert out is not None and out.passed and out.severity == "advisory"


def test_set_membership_substring_match_and_fail():
    rule = SetMembershipRuleDef(
        name="law", field_path="governing_law", severity="review",
        allowed_list=["Delaware"], match_mode="substring_ci",
    )
    ok = _interpret(rule, {"governing_law": fv("State of Delaware, USA")}, ctx())
    assert ok.passed and ok.severity == "review"
    bad = _interpret(rule, {"governing_law": fv("France")}, ctx())
    assert not bad.passed and bad.severity == "review"


# --- primitives: FieldDependencyRuleDef ---------------------------------------


def _dep():
    return FieldDependencyRuleDef(
        name="dep", antecedent_path="renewal_clause",
        consequent_path="termination_clause.notice_period", severity="hard",
    )


def test_field_dependency_antecedent_absent_passes():
    assert _interpret(_dep(), {}, ctx()).passed


def test_field_dependency_antecedent_without_consequent_fails():
    fields = {"renewal_clause": fv("auto-renews")}
    out = _interpret(_dep(), fields, ctx())
    assert not out.passed and out.severity == "hard"


def test_field_dependency_both_present_passes():
    fields = {
        "renewal_clause": fv("auto-renews"),
        "termination_clause": {"notice_period": fv("30 days")},
    }
    assert _interpret(_dep(), fields, ctx()).passed


# --- primitives: CodedRuleDef -------------------------------------------------


def test_coded_rule_passthrough_and_suppression():
    emit = CodedRuleDef(
        name="c", fn=lambda f, c: Check(name="c", passed=False, detail="x", severity="hard")
    )
    out = _interpret(emit, {}, ctx())
    assert out.name == "c" and not out.passed and out.severity == "hard"

    suppress = CodedRuleDef(name="c", fn=lambda f, c: None)
    assert _interpret(suppress, {}, ctx()) is None


# --- primitives: LlmAdvisoryRuleDef (structurally capped at review) -----------


def test_llm_advisory_yes_is_review_fail():
    rule = LlmAdvisoryRuleDef(name="adv", question="concern?", _test_fn=lambda f, c: True)
    out = _interpret(rule, {}, ctx())
    assert not out.passed and out.severity == "review"


def test_llm_advisory_no_is_review_pass():
    rule = LlmAdvisoryRuleDef(name="adv", question="concern?", _test_fn=lambda f, c: False)
    out = _interpret(rule, {}, ctx())
    assert out.passed and out.severity == "review"
    assert out.severity != "hard"  # can never hard-flag


def test_llm_advisory_raise_degrades_to_passing():
    def boom(f, c):
        raise RuntimeError("model down")

    rule = LlmAdvisoryRuleDef(name="adv", question="concern?", _test_fn=boom)
    out = _interpret(rule, {}, ctx())  # must not raise
    assert out.passed and out.severity == "review"


# --- primitives: EqualityRuleDef ----------------------------------------------


def test_equality_exact_pass_and_fail():
    rule = EqualityRuleDef(name="eq", field_path="currency", severity="hard", expected="USD")
    ok = _interpret(rule, {"currency": fv("USD")}, ctx())
    assert ok.passed and ok.severity == "hard"
    bad = _interpret(rule, {"currency": fv("EUR")}, ctx())
    assert not bad.passed and bad.severity == "hard"


def test_equality_exact_toggles_are_inert():
    """Exact mode compares raw strings — case/trim toggles do not apply."""
    rule = EqualityRuleDef(
        name="eq", field_path="currency", severity="review", expected="usd",
        match_mode="exact", case_insensitive=True, trim=True,
    )
    assert not _interpret(rule, {"currency": fv("USD")}, ctx()).passed


def test_equality_normalized_case_insensitive_and_trim():
    rule = EqualityRuleDef(
        name="eq", field_path="name", severity="review", expected="acme corp",
        match_mode="normalized", case_insensitive=True, trim=True, collapse_whitespace=True,
    )
    assert _interpret(rule, {"name": fv("  ACME   Corp ")}, ctx()).passed
    assert not _interpret(rule, {"name": fv("Globex")}, ctx()).passed


def test_equality_normalized_accents():
    rule = EqualityRuleDef(
        name="eq", field_path="city", severity="review", expected="Montreal",
        match_mode="normalized", normalize_accents=True,
    )
    assert _interpret(rule, {"city": fv("Montréal")}, ctx()).passed


def test_equality_regex_match_and_non_match():
    rule = EqualityRuleDef(
        name="eq", field_path="invoice_no", severity="review",
        expected=r"INV-\d+", match_mode="regex",
    )
    assert _interpret(rule, {"invoice_no": fv("INV-123")}, ctx()).passed
    assert not _interpret(rule, {"invoice_no": fv("PO-9")}, ctx()).passed


def test_equality_regex_case_insensitive():
    rule = EqualityRuleDef(
        name="eq", field_path="code", severity="review", expected=r"abc",
        match_mode="regex", case_insensitive=True,
    )
    assert _interpret(rule, {"code": fv("ABC")}, ctx()).passed


def test_equality_invalid_regex_skips():
    rule = EqualityRuleDef(
        name="eq", field_path="x", severity="review", expected="(", match_mode="regex",
    )
    assert _interpret(rule, {"x": fv("anything")}, ctx()) is None


def test_equality_negate_flips_result():
    rule = EqualityRuleDef(
        name="eq", field_path="currency", severity="review", expected="USD", negate=True,
    )
    # equal -> negate makes it fail
    assert not _interpret(rule, {"currency": fv("USD")}, ctx()).passed
    # not equal -> negate makes it pass
    assert _interpret(rule, {"currency": fv("EUR")}, ctx()).passed


def test_equality_skips_when_field_absent():
    rule = EqualityRuleDef(name="eq", field_path="currency", severity="hard", expected="USD")
    assert _interpret(rule, {}, ctx()) is None


def test_equality_skips_when_expected_field_absent():
    rule = EqualityRuleDef(
        name="eq", field_path="bill_to", severity="hard", expected_field_path="ship_to",
    )
    assert _interpret(rule, {"bill_to": fv("Acme")}, ctx()) is None


def test_equality_compare_against_another_field():
    rule = EqualityRuleDef(
        name="eq", field_path="bill_to", severity="hard", expected_field_path="ship_to",
    )
    same = _interpret(rule, {"bill_to": fv("Acme"), "ship_to": fv("Acme")}, ctx())
    assert same.passed
    diff = _interpret(rule, {"bill_to": fv("Acme"), "ship_to": fv("Globex")}, ctx())
    assert not diff.passed


# --- primitives: EqualityRuleDef (fuzzy match mode) ---------------------------


def test_equality_fuzzy_near_match_passes_at_default_threshold():
    """'Jean Dupont' vs 'Jean Dupond' has a difflib ratio ~0.909 >= 0.8."""
    rule = EqualityRuleDef(
        name="eq", field_path="name", severity="review",
        expected="Jean Dupont", match_mode="fuzzy",
    )
    out = _interpret(rule, {"name": fv("Jean Dupond")}, ctx())
    assert out.passed and out.severity == "review"


def test_equality_fuzzy_clear_non_match_fails():
    rule = EqualityRuleDef(
        name="eq", field_path="name", severity="review",
        expected="Jean Dupont", match_mode="fuzzy",
    )
    out = _interpret(rule, {"name": fv("Pierre Dupont")}, ctx())
    assert not out.passed


def test_equality_fuzzy_composes_with_case_insensitive():
    """Normalization (lowercasing) applies before the ratio, so casing is ignored."""
    rule = EqualityRuleDef(
        name="eq", field_path="name", severity="review",
        expected="jean dupont", match_mode="fuzzy", case_insensitive=True,
    )
    out = _interpret(rule, {"name": fv("JEAN DUPONT")}, ctx())
    assert out.passed  # ratio == 1.0 after lowercasing both sides


def test_equality_fuzzy_negate_flips_result():
    rule = EqualityRuleDef(
        name="eq", field_path="name", severity="review",
        expected="Jean Dupont", match_mode="fuzzy", negate=True,
    )
    # near-match (would pass) -> negate makes it fail
    assert not _interpret(rule, {"name": fv("Jean Dupond")}, ctx()).passed
    # clear non-match (would fail) -> negate makes it pass
    assert _interpret(rule, {"name": fv("Pierre Dupont")}, ctx()).passed


def test_equality_fuzzy_threshold_boundary_is_inclusive():
    """The ~0.909 ratio for 'Jean Dupont'/'Jean Dupond' proves the comparison is `>=`."""
    fields = {"name": fv("Jean Dupond")}
    just_below = EqualityRuleDef(
        name="eq", field_path="name", severity="review",
        expected="Jean Dupont", match_mode="fuzzy", fuzzy_threshold=0.9,
    )
    assert _interpret(just_below, fields, ctx()).passed  # 0.909 >= 0.90
    just_above = EqualityRuleDef(
        name="eq", field_path="name", severity="review",
        expected="Jean Dupont", match_mode="fuzzy", fuzzy_threshold=0.95,
    )
    assert not _interpret(just_above, fields, ctx()).passed  # 0.909 < 0.95


def test_equality_fuzzy_skips_when_field_absent():
    rule = EqualityRuleDef(
        name="eq", field_path="name", severity="review",
        expected="Jean Dupont", match_mode="fuzzy",
    )
    assert _interpret(rule, {}, ctx()) is None


def test_equality_fuzzy_skips_when_expected_field_absent():
    rule = EqualityRuleDef(
        name="eq", field_path="bill_to", severity="review",
        expected_field_path="ship_to", match_mode="fuzzy",
    )
    assert _interpret(rule, {"bill_to": fv("Acme")}, ctx()) is None


# --- primitives: DateConstraintRuleDef ----------------------------------------


def test_date_not_future_pass_and_fail():
    rule = DateConstraintRuleDef(name="dc", field_path="issued", severity="hard", not_future=True)
    past = (date.today() - timedelta(days=5)).isoformat()
    assert _interpret(rule, {"issued": fv(past)}, ctx()).passed
    future = (date.today() + timedelta(days=5)).isoformat()
    out = _interpret(rule, {"issued": fv(future)}, ctx())
    assert not out.passed and out.severity == "hard"


def test_date_min_max_in_range_and_out_of_range():
    rule = DateConstraintRuleDef(
        name="dc", field_path="d", severity="review", min="2026-01-01", max="2026-12-31",
    )
    assert _interpret(rule, {"d": fv("2026-06-15")}, ctx()).passed
    assert not _interpret(rule, {"d": fv("2025-12-31")}, ctx()).passed  # before min
    assert not _interpret(rule, {"d": fv("2027-01-01")}, ctx()).passed  # after max


def test_date_before_field_ordering():
    rule = DateConstraintRuleDef(
        name="dc", field_path="start", severity="hard", before_field_path="end",
    )
    ok = _interpret(rule, {"start": fv("2026-01-01"), "end": fv("2026-02-01")}, ctx())
    assert ok.passed
    bad = _interpret(rule, {"start": fv("2026-03-01"), "end": fv("2026-02-01")}, ctx())
    assert not bad.passed


def test_date_after_field_ordering():
    rule = DateConstraintRuleDef(
        name="dc", field_path="end", severity="hard", after_field_path="start",
    )
    ok = _interpret(rule, {"end": fv("2026-02-01"), "start": fv("2026-01-01")}, ctx())
    assert ok.passed
    bad = _interpret(rule, {"end": fv("2026-01-01"), "start": fv("2026-02-01")}, ctx())
    assert not bad.passed


def test_date_skips_when_unparseable():
    rule = DateConstraintRuleDef(name="dc", field_path="d", severity="hard", not_future=True)
    assert _interpret(rule, {"d": fv("not-a-date")}, ctx()) is None
    assert _interpret(rule, {}, ctx()) is None


def test_date_skips_when_min_literal_malformed():
    rule = DateConstraintRuleDef(name="dc", field_path="d", severity="hard", min="garbage")
    assert _interpret(rule, {"d": fv("2026-06-15")}, ctx()) is None


def test_date_skips_when_referenced_field_unparseable():
    rule = DateConstraintRuleDef(
        name="dc", field_path="start", severity="hard", before_field_path="end",
    )
    assert _interpret(rule, {"start": fv("2026-01-01"), "end": fv("nope")}, ctx()) is None


def test_date_compound_failures_joined():
    rule = DateConstraintRuleDef(
        name="dc", field_path="d", severity="review", not_future=True, min="2027-01-01",
    )
    future = (date.today() + timedelta(days=10)).isoformat()
    out = _interpret(rule, {"d": fv(future)}, ctx())
    assert not out.passed
    assert "in the future" in out.detail and "before 2027-01-01" in out.detail


# --- wired together: equality + date_constraint through build_ruleset ----------


def test_equality_and_date_constraint_wired_through_build_ruleset():
    defn = DocTypeRuleDefinition(
        name="mixed",
        rules=[
            EqualityRuleDef(
                name="currency_usd", field_path="currency", severity="hard", expected="USD",
            ),
            DateConstraintRuleDef(
                name="issued_not_future", field_path="issued", severity="review",
                not_future=True,
            ),
        ],
    )
    past = (date.today() - timedelta(days=1)).isoformat()
    fields = {"currency": fv("USD"), "issued": fv(past)}
    got = by_name(run(defn, fields))
    assert set(got) == {"currency_usd", "issued_not_future"}
    assert (got["currency_usd"].passed, got["currency_usd"].severity) == (True, "hard")
    assert (got["issued_not_future"].passed, got["issued_not_future"].severity) == (True, "review")


# --- primitives: AggregateRuleDef ---------------------------------------------


def _line_items():
    return [{"desc": fv("W"), "amount": fv(125.0)}, {"desc": fv("G"), "amount": fv(10.0)}]


def test_aggregate_sum_eq_pass():
    rule = AggregateRuleDef(
        name="agg", list_path="line_items", agg="sum", severity="hard",
        sub_field="amount", op="eq", compare_value=135.0,
    )
    out = _interpret(rule, {"line_items": _line_items()}, ctx())
    assert out.passed and out.severity == "hard"


def test_aggregate_sum_eq_fail_and_tolerance():
    fields = {"line_items": _line_items()}
    strict = AggregateRuleDef(
        name="agg", list_path="line_items", agg="sum", severity="hard",
        sub_field="amount", op="eq", compare_value=130.0,
    )
    assert not _interpret(strict, fields, ctx()).passed  # |135-130|=5 > 0
    tol = AggregateRuleDef(
        name="agg", list_path="line_items", agg="sum", severity="hard",
        sub_field="amount", op="eq", compare_value=130.0, tolerance=10.0,
    )
    assert _interpret(tol, fields, ctx()).passed  # 5 <= 10


def test_aggregate_lte_and_gte_ops():
    fields = {"line_items": _line_items()}
    lte = AggregateRuleDef(
        name="agg", list_path="line_items", agg="sum", severity="review",
        sub_field="amount", op="lte", compare_value=200.0,
    )
    assert _interpret(lte, fields, ctx()).passed  # 135 <= 200
    gte = AggregateRuleDef(
        name="agg", list_path="line_items", agg="sum", severity="review",
        sub_field="amount", op="gte", compare_value=200.0,
    )
    assert not _interpret(gte, fields, ctx()).passed  # 135 < 200


def test_aggregate_compare_field_path():
    fields = {"line_items": _line_items(), "total": fv(135.0)}
    rule = AggregateRuleDef(
        name="agg", list_path="line_items", agg="sum", severity="hard",
        sub_field="amount", op="eq", compare_field_path="total",
    )
    assert _interpret(rule, fields, ctx()).passed
    mismatch = {"line_items": _line_items(), "total": fv(999.0)}
    assert not _interpret(rule, mismatch, ctx()).passed


def test_aggregate_count_op():
    rule = AggregateRuleDef(
        name="agg", list_path="line_items", agg="count", severity="review",
        op="eq", compare_value=2.0,
    )
    assert _interpret(rule, {"line_items": _line_items()}, ctx()).passed


def test_aggregate_skips_when_list_absent():
    rule = AggregateRuleDef(
        name="agg", list_path="line_items", agg="sum", severity="hard",
        sub_field="amount", op="eq", compare_value=135.0,
    )
    assert _interpret(rule, {}, ctx()) is None


def test_aggregate_skips_when_compare_field_absent():
    rule = AggregateRuleDef(
        name="agg", list_path="line_items", agg="sum", severity="hard",
        sub_field="amount", op="eq", compare_field_path="total",
    )
    assert _interpret(rule, {"line_items": _line_items()}, ctx()) is None


# --- primitives: ExpressionRuleDef --------------------------------------------


def test_expression_pass():
    rule = ExpressionRuleDef(
        name="expr", expression="gross == net + tax", severity="hard",
    )
    fields = {"gross": fv(135.0), "net": fv(125.0), "tax": fv(10.0)}
    out = _interpret(rule, fields, ctx())
    assert out.passed and out.severity == "hard"


def test_expression_fail():
    rule = ExpressionRuleDef(
        name="expr", expression="gross == net + tax", severity="hard",
    )
    fields = {"gross": fv(200.0), "net": fv(125.0), "tax": fv(10.0)}
    assert not _interpret(rule, fields, ctx()).passed


def test_expression_skips_when_field_absent():
    rule = ExpressionRuleDef(
        name="expr", expression="gross == net + tax", severity="hard",
    )
    assert _interpret(rule, {"gross": fv(135.0), "net": fv(125.0)}, ctx()) is None


# --- primitives: NumericRangeRuleDef ------------------------------------------


def test_numeric_range_in_range_pass():
    rule = NumericRangeRuleDef(
        name="nr", field_path="qty", severity="review", min=0.0, max=100.0,
    )
    out = _interpret(rule, {"qty": fv(50.0)}, ctx())
    assert out.passed and out.severity == "review"


def test_numeric_range_below_min_and_above_max_fail():
    rule = NumericRangeRuleDef(
        name="nr", field_path="qty", severity="hard", min=0.0, max=100.0,
    )
    below = _interpret(rule, {"qty": fv(-5.0)}, ctx())
    assert not below.passed and "below 0" in below.detail
    above = _interpret(rule, {"qty": fv(150.0)}, ctx())
    assert not above.passed and "above 100" in above.detail


def test_numeric_range_one_sided_bound():
    only_min = NumericRangeRuleDef(name="nr", field_path="qty", severity="review", min=10.0)
    assert _interpret(only_min, {"qty": fv(20.0)}, ctx()).passed
    assert not _interpret(only_min, {"qty": fv(5.0)}, ctx()).passed
    only_max = NumericRangeRuleDef(name="nr", field_path="qty", severity="review", max=10.0)
    assert _interpret(only_max, {"qty": fv(5.0)}, ctx()).passed
    assert not _interpret(only_max, {"qty": fv(20.0)}, ctx()).passed


def test_numeric_range_skips_when_absent():
    rule = NumericRangeRuleDef(
        name="nr", field_path="qty", severity="review", min=0.0, max=100.0,
    )
    assert _interpret(rule, {}, ctx()) is None
    assert _interpret(rule, {"qty": fv("not-a-number")}, ctx()) is None


# --- primitives: PercentageToleranceRuleDef -----------------------------------


def test_percentage_tolerance_within_pass():
    rule = PercentageToleranceRuleDef(
        name="pct", value_path="actual", reference_path="expected", pct=0.05, severity="review",
    )
    out = _interpret(rule, {"actual": fv(102.0), "expected": fv(100.0)}, ctx())
    assert out.passed and out.severity == "review"  # 2% <= 5%


def test_percentage_tolerance_outside_fail():
    rule = PercentageToleranceRuleDef(
        name="pct", value_path="actual", reference_path="expected", pct=0.05, severity="review",
    )
    assert not _interpret(rule, {"actual": fv(120.0), "expected": fv(100.0)}, ctx()).passed


def test_percentage_tolerance_skips_when_reference_absent_or_zero():
    rule = PercentageToleranceRuleDef(
        name="pct", value_path="actual", reference_path="expected", pct=0.05, severity="review",
    )
    assert _interpret(rule, {"actual": fv(100.0)}, ctx()) is None
    assert _interpret(rule, {"actual": fv(100.0), "expected": fv(0.0)}, ctx()) is None


# --- parity: invoice ----------------------------------------------------------


def test_invoice_parity_clean():
    fields = {
        "total": fv(110.0), "subtotal": fv(100.0), "tax": fv(10.0),
        "invoice_no": fv("INV-1"), "po_number": fv("PO-9"), "due_date": fv("2026-01-01"),
    }
    got = by_name(run(INVOICE_RULE_DEFINITION, fields))
    expected = {
        "total_math": (True, "hard"),
        "duplicate_invoice_no": (True, "hard"),
        "auto_approve_threshold": (True, "review"),
        "po_present": (True, "advisory"),
        "due_date_present": (True, "advisory"),
        "bank_details": (True, "advisory"),
    }
    assert set(got) == set(expected)
    for name, (passed, sev) in expected.items():
        assert (got[name].passed, got[name].severity) == (passed, sev), name


def test_invoice_parity_total_mismatch():
    fields = {
        "total": fv(200.0), "subtotal": fv(100.0), "tax": fv(10.0), "invoice_no": fv("INV-2"),
    }
    got = by_name(run(INVOICE_RULE_DEFINITION, fields))
    assert (got["total_math"].passed, got["total_math"].severity) == (False, "hard")


def test_invoice_parity_duplicate():
    fields = {"invoice_no": fv("INV-1"), "total": fv(50.0)}
    got = by_name(run(INVOICE_RULE_DEFINITION, fields, ctx(prior_invoice_numbers={"INV-1"})))
    assert (got["duplicate_invoice_no"].passed, got["duplicate_invoice_no"].severity) == (False, "hard")


# --- parity: contract ---------------------------------------------------------


def test_contract_parity_clean():
    fields = {
        "signatures_present": fv(True),
        "renewal_clause": fv("auto-renews"),
        "termination_clause": {"text": fv("..."), "notice_period": fv("30 days")},
        "liability_cap": fv("1,000,000"),
        "governing_law": fv("Delaware"),
        "total_value": fv(5000.0),
    }
    got = by_name(run(CONTRACT_RULE_DEFINITION, fields))
    expected = {
        "signatures_present": (True, "hard"),
        "auto_renew_without_notice": (True, "hard"),
        "termination_clause_present": (True, "review"),
        "liability_cap_present": (True, "review"),
        "governing_law_allowed": (True, "review"),
        "value_over_threshold": (True, "review"),
    }
    assert set(got) == set(expected)
    for name, (passed, sev) in expected.items():
        assert (got[name].passed, got[name].severity) == (passed, sev), name


def test_contract_parity_missing_signatures():
    fields = {"signatures_present": fv(False, conf=0.0, page=None), "governing_law": fv("Delaware")}
    got = by_name(run(CONTRACT_RULE_DEFINITION, fields))
    assert (got["signatures_present"].passed, got["signatures_present"].severity) == (False, "hard")


def test_contract_parity_auto_renew_without_notice():
    fields = {
        "signatures_present": fv(True),
        "renewal_clause": fv("auto-renews"),
        "termination_clause": {"text": fv("...")},  # no notice_period
    }
    got = by_name(run(CONTRACT_RULE_DEFINITION, fields))
    ar = got["auto_renew_without_notice"]
    assert (ar.passed, ar.severity) == (False, "hard")


# --- FormatRuleDef ------------------------------------------------------------


def _fmt(field_path, fmt, **kw):
    return FormatRuleDef(name="fmt", field_path=field_path, format=fmt, severity="review", **kw)


def test_format_pass():
    fields = {"country": fv("US")}
    c = _interpret(_fmt("country", "iso_country"), fields, ctx())
    assert (c.passed, c.severity) == (True, "review")


def test_format_fail():
    fields = {"country": fv("ZZ")}
    c = _interpret(_fmt("country", "iso_country"), fields, ctx())
    assert c.passed is False


def test_format_skip_when_field_absent():
    assert _interpret(_fmt("country", "iso_country"), {}, ctx()) is None


def test_format_skip_on_unknown_format_key():
    fields = {"country": fv("US")}
    assert _interpret(_fmt("country", "not_a_real_format"), fields, ctx()) is None


def test_format_email_and_checksum():
    assert _interpret(_fmt("e", "email"), {"e": fv("a@b.co")}, ctx()).passed is True
    assert _interpret(_fmt("n", "luhn"), {"n": fv("79927398713")}, ctx()).passed is True
    assert _interpret(_fmt("n", "luhn"), {"n": fv("79927398714")}, ctx()).passed is False
