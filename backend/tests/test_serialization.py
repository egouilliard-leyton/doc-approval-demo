"""Round-trip + validation tests for the new equality / date_constraint rule kinds.

The serialization layer is pure (no DB / FastAPI), so these exercise
``rule_defn_to_dict`` / ``dict_to_rule_defn`` and ``validate_custom_rule_dict``
directly, mirroring the dict shapes ``test_doc_types_api.py`` builds.
"""

from app.rules.definition import (
    AggregateRuleDef,
    AtLeastNOfRuleDef,
    ConditionalPresenceRuleDef,
    ContainsRuleDef,
    DateConstraintRuleDef,
    DocTypeRuleDefinition,
    EqualityRuleDef,
    ExpressionRuleDef,
    FieldConfidenceFloorRuleDef,
    FormatRuleDef,
    GroundedOnPageRuleDef,
    LengthBoundsRuleDef,
    MutualExclusivityRuleDef,
    NumericRangeRuleDef,
    PercentageToleranceRuleDef,
    RequiredTogetherRuleDef,
)
from app.serialization import (
    dict_to_rule_defn,
    rule_defn_to_dict,
    validate_custom_rule_dict,
)


DECLARED = {"currency", "issued", "start", "end", "bill_to", "ship_to"}


def _valid_rules() -> list[dict]:
    return [
        {
            "kind": "equality",
            "name": "currency_usd",
            "field_path": "currency",
            "severity": "hard",
            "expected": "USD",
        },
        {
            "kind": "date_constraint",
            "name": "issued_not_future",
            "field_path": "issued",
            "severity": "review",
            "not_future": True,
        },
    ]


# --- round-trip ---------------------------------------------------------------


def test_round_trip_equality_and_date_constraint():
    original = DocTypeRuleDefinition(
        name="mixed",
        rules=[
            EqualityRuleDef(
                name="currency_usd",
                field_path="currency",
                severity="hard",
                expected="USD",
                match_mode="normalized",
                case_insensitive=True,
                trim=True,
            ),
            DateConstraintRuleDef(
                name="dates_ok",
                field_path="start",
                severity="review",
                not_future=True,
                min="2026-01-01",
                before_field_path="end",
            ),
        ],
        citation_paths=["currency", "start"],
    )

    d = rule_defn_to_dict(original)
    kinds = [r["kind"] for r in d["rules"]]
    assert kinds == ["equality", "date_constraint"]

    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], EqualityRuleDef)
    assert isinstance(rebuilt.rules[1], DateConstraintRuleDef)


def test_round_trip_equality_fuzzy():
    original = DocTypeRuleDefinition(
        name="fuzzy",
        rules=[
            EqualityRuleDef(
                name="name_fuzzy",
                field_path="bill_to",
                severity="review",
                expected="Acme Corp",
                match_mode="fuzzy",
                fuzzy_threshold=0.85,
                case_insensitive=True,
            ),
        ],
        citation_paths=["bill_to"],
    )

    d = rule_defn_to_dict(original)
    assert d["rules"][0]["match_mode"] == "fuzzy"
    assert d["rules"][0]["fuzzy_threshold"] == 0.85

    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert rebuilt.rules[0].fuzzy_threshold == 0.85


# --- validation: rejections ---------------------------------------------------


def _defn(rule: dict) -> dict:
    return {"name": "t", "rules": [rule], "citation_paths": []}


def test_valid_pair_has_no_errors():
    d = {"name": "t", "rules": _valid_rules(), "citation_paths": []}
    assert validate_custom_rule_dict(d, DECLARED) == []


def test_equality_both_expected_set_errors():
    rule = {
        "kind": "equality",
        "name": "eq",
        "field_path": "bill_to",
        "severity": "hard",
        "expected": "Acme",
        "expected_field_path": "ship_to",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("exactly one of 'expected'" in e for e in errors)


def test_equality_neither_expected_set_errors():
    rule = {"kind": "equality", "name": "eq", "field_path": "currency", "severity": "hard"}
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("exactly one of 'expected'" in e for e in errors)


def test_equality_bad_match_mode_errors():
    rule = {
        "kind": "equality",
        "name": "eq",
        "field_path": "currency",
        "severity": "hard",
        "expected": "USD",
        "match_mode": "nonsense",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("match_mode" in e for e in errors)


def test_equality_fuzzy_match_mode_accepted():
    rule = {
        "kind": "equality",
        "name": "eq",
        "field_path": "currency",
        "severity": "hard",
        "expected": "USD",
        "match_mode": "fuzzy",
        "fuzzy_threshold": 0.9,
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert not any("match_mode" in e for e in errors)
    assert not any("fuzzy_threshold" in e for e in errors)


def test_equality_fuzzy_threshold_too_high_errors():
    rule = {
        "kind": "equality",
        "name": "eq",
        "field_path": "currency",
        "severity": "hard",
        "expected": "USD",
        "match_mode": "fuzzy",
        "fuzzy_threshold": 1.5,
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("fuzzy_threshold" in e for e in errors)


def test_equality_fuzzy_threshold_negative_errors():
    rule = {
        "kind": "equality",
        "name": "eq",
        "field_path": "currency",
        "severity": "hard",
        "expected": "USD",
        "match_mode": "fuzzy",
        "fuzzy_threshold": -0.1,
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("fuzzy_threshold" in e for e in errors)


def test_equality_invalid_regex_errors():
    rule = {
        "kind": "equality",
        "name": "eq",
        "field_path": "currency",
        "severity": "hard",
        "expected": "(",
        "match_mode": "regex",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("regex" in e for e in errors)


def test_date_constraint_no_constraint_errors():
    rule = {
        "kind": "date_constraint",
        "name": "dc",
        "field_path": "issued",
        "severity": "review",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("at least one constraint" in e for e in errors)


def test_date_constraint_malformed_min_errors():
    rule = {
        "kind": "date_constraint",
        "name": "dc",
        "field_path": "issued",
        "severity": "review",
        "min": "01/01/2026",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("ISO date string" in e for e in errors)


def test_date_constraint_empty_string_min_is_not_a_constraint():
    """The UI writes "" for a cleared date input; "" must count as absent, not as a
    malformed ISO literal (no spurious 422) — and must not satisfy the has-constraint
    check on its own."""
    rule = {
        "kind": "date_constraint",
        "name": "dc",
        "field_path": "issued",
        "severity": "review",
        "not_future": True,
        "min": "",
        "max": "",
    }
    # Real constraint (not_future) present + blank min/max → valid, no ISO error.
    assert validate_custom_rule_dict(_defn(rule), DECLARED) == []


def test_date_constraint_only_empty_strings_still_errors():
    """Blank min/max/before/after with no real constraint is a no-op rule → rejected."""
    rule = {
        "kind": "date_constraint",
        "name": "dc",
        "field_path": "issued",
        "severity": "review",
        "min": "",
        "before_field_path": "",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("at least one constraint" in e for e in errors)


# --- round-trip: Wave B kinds -------------------------------------------------


def test_round_trip_expression():
    original = DocTypeRuleDefinition(
        name="expr",
        rules=[
            ExpressionRuleDef(
                name="balances", expression="start == end", severity="hard",
                detail_fail="mismatch",
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "expression"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], ExpressionRuleDef)


def test_round_trip_aggregate():
    original = DocTypeRuleDefinition(
        name="agg",
        rules=[
            AggregateRuleDef(
                name="sum_amounts", list_path="start", agg="sum", severity="review",
                sub_field="amount", op="lte", compare_value=1000.0, tolerance=0.5,
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "aggregate"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], AggregateRuleDef)


def test_round_trip_numeric_range():
    original = DocTypeRuleDefinition(
        name="nr",
        rules=[
            NumericRangeRuleDef(
                name="qty_range", field_path="start", severity="hard", min=0.0, max=100.0,
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "numeric_range"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], NumericRangeRuleDef)


def test_round_trip_percentage_tolerance():
    original = DocTypeRuleDefinition(
        name="pct",
        rules=[
            PercentageToleranceRuleDef(
                name="within_5pct", value_path="start", reference_path="end",
                pct=0.05, severity="review",
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "percentage_tolerance"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], PercentageToleranceRuleDef)


# --- validation: Wave B rejections --------------------------------------------


def test_expression_undeclared_field_errors():
    rule = {
        "kind": "expression",
        "name": "expr",
        "expression": "gross == 1",
        "severity": "hard",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("gross" in e for e in errors)


def test_expression_valid_has_no_errors():
    rule = {
        "kind": "expression",
        "name": "expr",
        "expression": "start == end",
        "severity": "hard",
    }
    assert validate_custom_rule_dict(_defn(rule), DECLARED) == []


def test_aggregate_both_compare_set_errors():
    rule = {
        "kind": "aggregate",
        "name": "agg",
        "list_path": "start",
        "agg": "sum",
        "severity": "review",
        "sub_field": "amount",
        "compare_value": 100.0,
        "compare_field_path": "end",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("exactly one of 'compare_value'" in e for e in errors)


def test_aggregate_bad_agg_errors():
    rule = {
        "kind": "aggregate",
        "name": "agg",
        "list_path": "start",
        "agg": "median",
        "severity": "review",
        "compare_value": 100.0,
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'agg'" in e for e in errors)


def test_aggregate_sub_field_not_treated_as_undeclared_field():
    """Regression: 'sub_field' is not a '*_path' and must NOT be checked against
    declared field names, so a sub_field like 'amount' (not a declared field) is fine."""
    rule = {
        "kind": "aggregate",
        "name": "agg",
        "list_path": "start",
        "agg": "sum",
        "severity": "review",
        "op": "eq",
        "sub_field": "amount",
        "compare_value": 100.0,
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert not any("amount" in e for e in errors)
    assert errors == []


def test_aggregate_non_numeric_compare_value_errors():
    """A non-numeric compare_value must be rejected at save time — otherwise it passes
    the dataclass (no runtime type enforcement) and raises TypeError in the interpreter's
    arithmetic → an unhandled 500 at decision time. Reachable via the raw JSON API."""
    rule = {
        "kind": "aggregate",
        "name": "agg",
        "list_path": "start",
        "agg": "sum",
        "severity": "review",
        "op": "eq",
        "compare_value": "abc",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'compare_value' must be a number" in e for e in errors)
    # bool is an int subclass — must also be rejected.
    rule["compare_value"] = True
    assert any(
        "'compare_value' must be a number" in e
        for e in validate_custom_rule_dict(_defn(rule), DECLARED)
    )


def test_numeric_range_neither_bound_errors():
    rule = {
        "kind": "numeric_range",
        "name": "nr",
        "field_path": "start",
        "severity": "hard",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("at least one of 'min'" in e for e in errors)


def test_numeric_range_min_greater_than_max_errors():
    rule = {
        "kind": "numeric_range",
        "name": "nr",
        "field_path": "start",
        "severity": "hard",
        "min": 100.0,
        "max": 0.0,
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'min' must be <= 'max'" in e for e in errors)


def test_percentage_tolerance_negative_pct_errors():
    rule = {
        "kind": "percentage_tolerance",
        "name": "pct",
        "value_path": "start",
        "reference_path": "end",
        "pct": -0.1,
        "severity": "review",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'pct'" in e for e in errors)


# --- format kind --------------------------------------------------------------


def test_round_trip_format():
    original = DocTypeRuleDefinition(
        name="fmt",
        rules=[
            FormatRuleDef(name="iban_ok", field_path="account", format="iban", severity="hard"),
        ],
        citation_paths=["account"],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "format"
    assert d["rules"][0]["format"] == "iban"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], FormatRuleDef)


def test_format_unknown_key_errors():
    rule = {
        "kind": "format",
        "name": "f",
        "field_path": "currency",
        "format": "not_real",
        "severity": "review",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'format' must be one of" in e for e in errors)


def test_format_known_key_valid():
    rule = {
        "kind": "format",
        "name": "f",
        "field_path": "currency",
        "format": "iso_currency",
        "severity": "review",
    }
    assert validate_custom_rule_dict(_defn(rule), DECLARED) == []


# --- presence/cardinality kinds: round-trip -----------------------------------


def test_round_trip_conditional_presence():
    original = DocTypeRuleDefinition(
        name="cp",
        rules=[
            ConditionalPresenceRuleDef(
                name="wire_needs_iban", condition_field_path="currency",
                required_field_path="bill_to", severity="hard", equals="USD",
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "conditional_presence"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], ConditionalPresenceRuleDef)


def test_round_trip_mutual_exclusivity():
    original = DocTypeRuleDefinition(
        name="mx",
        rules=[
            MutualExclusivityRuleDef(
                name="one_of", field_paths=["bill_to", "ship_to"],
                severity="review", mode="at_most_one",
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "mutual_exclusivity"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], MutualExclusivityRuleDef)


def test_round_trip_at_least_n_of():
    original = DocTypeRuleDefinition(
        name="atl",
        rules=[
            AtLeastNOfRuleDef(
                name="two_of", field_paths=["bill_to", "ship_to", "currency"],
                n=2, severity="hard",
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "at_least_n_of"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], AtLeastNOfRuleDef)


def test_round_trip_required_together():
    original = DocTypeRuleDefinition(
        name="rt",
        rules=[
            RequiredTogetherRuleDef(
                name="together", field_paths=["start", "end"], severity="hard",
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "required_together"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], RequiredTogetherRuleDef)


# --- presence/cardinality kinds: validation rejections ------------------------


def test_field_paths_undeclared_field_errors():
    rule = {
        "kind": "mutual_exclusivity",
        "name": "mx",
        "field_paths": ["bill_to", "nope"],
        "severity": "review",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("nope" in e for e in errors)


def test_field_paths_empty_list_errors():
    rule = {
        "kind": "required_together",
        "name": "rt",
        "field_paths": [],
        "severity": "hard",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("non-empty list" in e for e in errors)


def test_mutual_exclusivity_bad_mode_errors():
    rule = {
        "kind": "mutual_exclusivity",
        "name": "mx",
        "field_paths": ["bill_to", "ship_to"],
        "severity": "review",
        "mode": "nonsense",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'mode'" in e for e in errors)


def test_at_least_n_of_zero_errors():
    rule = {
        "kind": "at_least_n_of",
        "name": "atl",
        "field_paths": ["bill_to", "ship_to"],
        "n": 0,
        "severity": "hard",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'n'" in e for e in errors)


def test_at_least_n_of_n_greater_than_len_errors():
    rule = {
        "kind": "at_least_n_of",
        "name": "atl",
        "field_paths": ["bill_to", "ship_to"],
        "n": 3,
        "severity": "hard",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("must be <= the number of field_paths" in e for e in errors)


def test_presence_cardinality_valid_has_no_errors():
    for rule in (
        {
            "kind": "conditional_presence",
            "name": "cp",
            "condition_field_path": "currency",
            "required_field_path": "bill_to",
            "severity": "hard",
        },
        {
            "kind": "mutual_exclusivity",
            "name": "mx",
            "field_paths": ["bill_to", "ship_to"],
            "severity": "review",
            "mode": "exactly_one",
        },
        {
            "kind": "at_least_n_of",
            "name": "atl",
            "field_paths": ["bill_to", "ship_to", "currency"],
            "n": 2,
            "severity": "hard",
        },
        {
            "kind": "required_together",
            "name": "rt",
            "field_paths": ["start", "end"],
            "severity": "hard",
        },
    ):
        assert validate_custom_rule_dict(_defn(rule), DECLARED) == [], rule["kind"]


# --- text / provenance kinds: round-trip --------------------------------------


def test_round_trip_contains():
    original = DocTypeRuleDefinition(
        name="ct",
        rules=[
            ContainsRuleDef(
                name="has_kw", field_path="currency", keywords=["USD", "EUR"],
                severity="review", mode="any", case_insensitive=True,
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "contains"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], ContainsRuleDef)


def test_round_trip_length_bounds():
    original = DocTypeRuleDefinition(
        name="lb",
        rules=[
            LengthBoundsRuleDef(
                name="len_ok", field_path="currency", severity="hard",
                min_length=3, max_length=3,
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "length_bounds"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], LengthBoundsRuleDef)


def test_round_trip_field_confidence_floor():
    original = DocTypeRuleDefinition(
        name="cf",
        rules=[
            FieldConfidenceFloorRuleDef(
                name="conf_ok", field_path="currency", floor=0.8, severity="review",
            ),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "field_confidence_floor"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], FieldConfidenceFloorRuleDef)


def test_round_trip_grounded_on_page():
    original = DocTypeRuleDefinition(
        name="g",
        rules=[
            GroundedOnPageRuleDef(name="grounded", field_path="currency", severity="hard"),
        ],
        citation_paths=[],
    )
    d = rule_defn_to_dict(original)
    assert d["rules"][0]["kind"] == "grounded_on_page"
    rebuilt = dict_to_rule_defn(d)
    assert rebuilt == original
    assert isinstance(rebuilt.rules[0], GroundedOnPageRuleDef)


# --- text / provenance kinds: validation rejections ---------------------------


def test_contains_empty_keywords_errors():
    rule = {
        "kind": "contains",
        "name": "ct",
        "field_path": "currency",
        "keywords": [],
        "severity": "review",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("keywords" in e for e in errors)


def test_contains_bad_mode_errors():
    rule = {
        "kind": "contains",
        "name": "ct",
        "field_path": "currency",
        "keywords": ["USD"],
        "severity": "review",
        "mode": "nonsense",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'mode'" in e for e in errors)


def test_length_bounds_no_bounds_errors():
    rule = {
        "kind": "length_bounds",
        "name": "lb",
        "field_path": "currency",
        "severity": "review",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("at least one of" in e for e in errors)


def test_field_confidence_floor_too_high_errors():
    rule = {
        "kind": "field_confidence_floor",
        "name": "cf",
        "field_path": "currency",
        "floor": 1.5,
        "severity": "review",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("'floor'" in e for e in errors)
