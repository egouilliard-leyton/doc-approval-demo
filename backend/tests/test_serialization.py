"""Round-trip + validation tests for the new equality / date_constraint rule kinds.

The serialization layer is pure (no DB / FastAPI), so these exercise
``rule_defn_to_dict`` / ``dict_to_rule_defn`` and ``validate_custom_rule_dict``
directly, mirroring the dict shapes ``test_doc_types_api.py`` builds.
"""

from app.rules.definition import (
    DateConstraintRuleDef,
    DocTypeRuleDefinition,
    EqualityRuleDef,
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
        "match_mode": "fuzzy",
    }
    errors = validate_custom_rule_dict(_defn(rule), DECLARED)
    assert any("match_mode" in e for e in errors)


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
