"""Declarative business-rule definitions and their generic interpreter.

A :class:`DocTypeRuleDefinition` describes a document type's rule set as data — a list
of small rule "primitives" (presence, threshold comparison, arithmetic identity, set
membership, field dependency, history uniqueness) plus two Tier-3 escape hatches (a
fully coded rule and an LLM-advisory rule). :func:`build_ruleset` turns that declaration
into a :class:`~app.rules.base.Ruleset` closure that the agent stage consults exactly
like the old hand-written ``invoice_checks``/``contract_checks`` functions.

This mirrors :mod:`app.extraction.definition`: declarative dataclasses + a ``build_*``
function + per-type data modules + registry generation in ``__init__``. The interpreter
reuses the :mod:`app.rules.base` accessors verbatim and reads settings lazily (at call
time, inside the closure) so thresholds/lists can be tweaked live without rebuilding the
ruleset — this is the parity layer that lets the two built-in types be expressed as data
while preserving their exact ``(name, passed, severity)`` behaviour.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Union

from app.config import settings
from app.schemas import Check

from .base import DecisionContext, Ruleset, as_date, as_number, fval, present, _values_only
from .expression import evaluate_expression, aggregate_list
from .formats import FORMAT_VALIDATORS


# --- declarative rule primitives ----------------------------------------------


@dataclass
class PresenceRuleDef:
    """Emit a check on whether ``field_path`` carries a real value."""

    name: str
    field_path: str
    severity: Literal["hard", "review", "advisory"]
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class ThresholdCompareRuleDef:
    """Compare a numeric field against a threshold (literal or settings-sourced).

    Exactly one of ``threshold`` / ``threshold_setting`` is non-None; when ``threshold``
    is None the value is resolved via ``getattr(settings, threshold_setting)`` at call
    time. Skipped (no check emitted) when the field is absent or non-numeric.
    """

    name: str
    field_path: str
    severity: Literal["hard", "review", "advisory"]
    op: Literal["lte", "gte", "lt", "gt"] = "lte"
    threshold: float | None = None
    threshold_setting: str | None = None
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class ArithmeticIdentityRuleDef:
    """Check ``result == addend_a + addend_b`` within a tolerance.

    Skipped (no check emitted) when any of the three fields is absent or non-numeric, so
    the rule never fails on missing data. ``tolerance_setting`` (when set) overrides the
    literal ``tolerance`` at call time.
    """

    name: str
    result_path: str
    addend_a_path: str
    addend_b_path: str
    severity: Literal["hard", "review", "advisory"]
    tolerance: float = 0.0
    tolerance_setting: str | None = None
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class SetMembershipRuleDef:
    """Check that a field's value is in an allowed list (literal or settings-sourced)."""

    name: str
    field_path: str
    severity: Literal["hard", "review", "advisory"]
    allowed_list: list[str] | None = None
    allowed_list_setting: str | None = None
    match_mode: Literal["exact_ci", "substring_ci"] = "substring_ci"
    absent_behavior: Literal["advisory_pass", "skip"] = "advisory_pass"
    absent_severity: str = "advisory"
    empty_list_behavior: Literal["skip", "always_pass"] = "skip"


@dataclass
class FieldDependencyRuleDef:
    """Require ``consequent`` whenever ``antecedent`` is present (implication)."""

    name: str
    antecedent_path: str
    consequent_path: str
    severity: Literal["hard", "review", "advisory"]
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class UniquenessVsHistoryRuleDef:
    """Flag a value already seen on another decided document (e.g. invoice number).

    Skipped (no check emitted) when the field value is None; otherwise checks
    ``str(val) in ctx.prior_invoice_numbers``.
    """

    name: str
    field_path: str
    severity: Literal["hard", "review", "advisory"] = "hard"
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class EqualityRuleDef:
    """Compare a field against a literal or another field, with optional normalization.

    Exactly one of ``expected`` (a literal) / ``expected_field_path`` (another field)
    supplies the expected side. Skipped (no check emitted) when the compared field is
    absent, when ``expected_field_path`` is set but that field is absent, or when a
    ``regex`` pattern fails to compile. ``match_mode`` picks the comparison: ``exact``
    (raw string equality, toggles inert), ``normalized`` (apply the trim/whitespace/case/
    accent toggles to both sides), ``regex`` (``expected`` is a full-match pattern;
    only ``case_insensitive`` applies), or ``fuzzy`` (apply the same normalization as
    ``normalized`` to both sides, then accept when the ``difflib`` similarity ratio is
    ``>= fuzzy_threshold``). ``negate`` flips the result last.
    """

    name: str
    field_path: str
    severity: Literal["hard", "review", "advisory"]
    expected: str | None = None
    expected_field_path: str | None = None
    match_mode: Literal["exact", "normalized", "regex", "fuzzy"] = "exact"
    case_insensitive: bool = False
    trim: bool = False
    collapse_whitespace: bool = False
    normalize_accents: bool = False
    fuzzy_threshold: float = 0.8
    negate: bool = False
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class DateConstraintRuleDef:
    """Check a date field against calendar and/or cross-field ordering constraints.

    Skipped (no check emitted) when the field is unparseable as a date, when a ``min`` /
    ``max`` literal is itself malformed (an authoring bug), or when a referenced
    ``before_field_path`` / ``after_field_path`` is unparseable. Every configured
    constraint is evaluated and any failures are joined into one detail; the check passes
    only when none fail.
    """

    name: str
    field_path: str
    severity: Literal["hard", "review", "advisory"]
    not_future: bool = False
    min: str | None = None
    max: str | None = None
    before_field_path: str | None = None
    after_field_path: str | None = None
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class ExpressionRuleDef:
    """Evaluate a sandboxed author-written formula (see :mod:`app.rules.expression`).

    ``expression`` is a small Python-flavoured boolean/arithmetic formula. It is run via
    :func:`evaluate_expression`, which returns ``None`` on any missing field / unsafe or
    invalid formula — that ``None`` is the skip signal (no check emitted). Otherwise the
    result is coerced to ``bool`` for the pass/fail verdict.
    """

    name: str
    expression: str
    severity: Literal["hard", "review", "advisory"]
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class AggregateRuleDef:
    """Aggregate a list field's numeric values and compare against a value or field.

    ``aggregate_list`` reduces ``list_path`` (optionally digging into ``sub_field`` for
    list_composite rows) to a single number via ``agg``. Skipped (no check emitted) when
    the list is absent/empty-for-min-max-avg or the comparison operand is absent. For
    ``op == "eq"`` the comparison is ``abs(agg - rhs) <= tolerance``; otherwise the
    standard numeric operator is used.
    """

    name: str
    list_path: str
    agg: Literal["sum", "count", "min", "max", "avg"]
    severity: Literal["hard", "review", "advisory"]
    sub_field: str | None = None
    op: Literal["eq", "lte", "gte", "lt", "gt"] = "eq"
    compare_value: float | None = None
    compare_field_path: str | None = None
    tolerance: float = 0.0
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class NumericRangeRuleDef:
    """Check a numeric field falls within an inclusive ``[min, max]`` range.

    At least one bound is set; each configured bound is checked and any breaches are
    joined into one detail (like :class:`DateConstraintRuleDef`). Skipped (no check
    emitted) when the field is absent or non-numeric.
    """

    name: str
    field_path: str
    severity: Literal["hard", "review", "advisory"]
    min: float | None = None
    max: float | None = None
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class PercentageToleranceRuleDef:
    """Check a value is within ``pct`` (a fraction) of a reference field.

    ``passed`` iff ``abs(value - reference) / abs(reference) <= pct``. Skipped (no check
    emitted) when either field is absent/non-numeric or the reference is zero.
    """

    name: str
    value_path: str
    reference_path: str
    pct: float
    severity: Literal["hard", "review", "advisory"]
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class FormatRuleDef:
    """Check a field against a canned format/checksum validator (app.rules.formats).

    ``format`` is a key of ``FORMAT_VALIDATORS``. Skipped (no check) when the field is
    absent or when the format key is unknown — never fails on missing data.
    """

    name: str
    field_path: str
    format: str
    severity: Literal["hard", "review", "advisory"]
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class ConditionalPresenceRuleDef:
    """If the condition field is present (and, when `equals` is set, equals that value),
    then `required_field_path` must be present. Vacuously passes when the condition is
    not met (mirrors FieldDependencyRuleDef)."""
    name: str
    condition_field_path: str
    required_field_path: str
    severity: Literal["hard", "review", "advisory"]
    equals: str | None = None
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class MutualExclusivityRuleDef:
    """Of the given field paths, `mode` controls how many may be present."""
    name: str
    field_paths: list[str]
    severity: Literal["hard", "review", "advisory"]
    mode: Literal["exactly_one", "at_most_one"] = "exactly_one"
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class AtLeastNOfRuleDef:
    """At least `n` of the given field paths must be present."""
    name: str
    field_paths: list[str]
    n: int
    severity: Literal["hard", "review", "advisory"]
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class RequiredTogetherRuleDef:
    """If ANY of the given field paths is present, ALL must be present (all-or-nothing)."""
    name: str
    field_paths: list[str]
    severity: Literal["hard", "review", "advisory"]
    detail_pass: str = ""
    detail_fail: str = ""


@dataclass
class CodedRuleDef:
    """Tier-3 escape hatch: delegate entirely to a hand-written function.

    The function receives ``(fields, ctx)`` and may return ``None`` to suppress emission.
    """

    name: str
    fn: Callable[[dict, DecisionContext], Check | None]


@dataclass
class LlmAdvisoryRuleDef:
    """Tier-3 escape hatch: a yes/no LLM judgment, structurally capped at "review".

    No severity field — the interpreter forces ``"review"`` unconditionally so a soft LLM
    opinion can never hard-flag. ``_test_fn`` short-circuits the LLM call for offline
    tests (and any raise from it degrades to a passing advisory).
    """

    name: str
    question: str
    _test_fn: Callable[[dict, DecisionContext], bool] | None = None


RuleDef = Union[
    PresenceRuleDef,
    ThresholdCompareRuleDef,
    ArithmeticIdentityRuleDef,
    SetMembershipRuleDef,
    FieldDependencyRuleDef,
    UniquenessVsHistoryRuleDef,
    EqualityRuleDef,
    DateConstraintRuleDef,
    ExpressionRuleDef,
    AggregateRuleDef,
    NumericRangeRuleDef,
    PercentageToleranceRuleDef,
    FormatRuleDef,
    ConditionalPresenceRuleDef,
    MutualExclusivityRuleDef,
    AtLeastNOfRuleDef,
    RequiredTogetherRuleDef,
    CodedRuleDef,
    LlmAdvisoryRuleDef,
]


@dataclass
class DocTypeRuleDefinition:
    """A document type's rule set expressed declaratively, ready for :func:`build_ruleset`."""

    name: str
    rules: list[RuleDef]
    citation_paths: list[str] = field(default_factory=list)


# --- interpreter ---------------------------------------------------------------

_OPS: dict[str, Callable[[float, float], bool]] = {
    "lte": lambda v, t: v <= t,
    "gte": lambda v, t: v >= t,
    "lt": lambda v, t: v < t,
    "gt": lambda v, t: v > t,
}


def _detail(template: str, default: str, ctx_dict: dict) -> str:
    """Use a non-empty author-supplied template (``str.format_map``) else the default."""
    if template:
        return template.format_map(ctx_dict)
    return default


def _normalize_equality_value(raw: str, rule: EqualityRuleDef) -> str:
    """Apply the equality normalization toggles in a fixed, documented order.

    ``trim`` (strip) -> ``collapse_whitespace`` (fold runs to single spaces) ->
    ``case_insensitive`` (lowercase) -> ``normalize_accents`` (NFKD + drop combining
    marks). Each step is gated on its own boolean, so a rule opts into exactly the
    normalizations it needs.
    """
    s = raw
    if rule.trim:
        s = s.strip()
    if rule.collapse_whitespace:
        s = " ".join(s.split())
    if rule.case_insensitive:
        s = s.lower()
    if rule.normalize_accents:
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
    return s


def _interpret(rule: RuleDef, fields: dict, ctx: DecisionContext) -> Check | None:
    """Evaluate one rule primitive against the structured fields, or ``None`` to skip."""
    if isinstance(rule, PresenceRuleDef):
        passed = present(fields, rule.field_path)
        default = f"{rule.field_path} {'present' if passed else 'absent'}"
        fmt = {"value": fval(fields, rule.field_path), "field_path": rule.field_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, ThresholdCompareRuleDef):
        v = as_number(fval(fields, rule.field_path))
        if v is None:
            return None
        threshold = (
            rule.threshold
            if rule.threshold is not None
            else getattr(settings, rule.threshold_setting)
        )
        passed = _OPS[rule.op](v, threshold)
        default = f"{rule.field_path} {v} {rule.op} {threshold}"
        fmt = {"value": v, "threshold": threshold, "field_path": rule.field_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, ArithmeticIdentityRuleDef):
        c = as_number(fval(fields, rule.result_path))
        a = as_number(fval(fields, rule.addend_a_path))
        b = as_number(fval(fields, rule.addend_b_path))
        if a is None or b is None or c is None:
            return None
        expected = a + b
        tol = (
            getattr(settings, rule.tolerance_setting)
            if rule.tolerance_setting is not None
            else rule.tolerance
        )
        passed = abs(c - expected) <= tol
        default = (
            f"{rule.result_path} {c} {'==' if passed else '!='} "
            f"{rule.addend_a_path}+{rule.addend_b_path} ({expected})"
        )
        fmt = {"value": c, "expected": expected, "field_path": rule.result_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, SetMembershipRuleDef):
        allowed = (
            rule.allowed_list
            if rule.allowed_list is not None
            else getattr(settings, rule.allowed_list_setting)
        )
        law = fval(fields, rule.field_path)  # absent-field FIRST
        if law is None:
            if rule.absent_behavior == "advisory_pass":
                return Check(
                    name=rule.name,
                    passed=True,
                    detail=f"{rule.field_path} absent",
                    severity=rule.absent_severity,
                )
            return None  # skip
        if not allowed:  # empty-list SECOND
            if rule.empty_list_behavior == "always_pass":
                return Check(
                    name=rule.name,
                    passed=True,
                    detail=f"{rule.field_path}: no allowed-list configured",
                    severity=rule.severity,
                )
            return None  # skip
        if rule.match_mode == "exact_ci":
            ok = str(law).lower() in {item.lower() for item in allowed}
        else:  # substring_ci
            ok = any(item.lower() in str(law).lower() for item in allowed)
        return Check(
            name=rule.name,
            passed=ok,
            detail=(f"{rule.field_path} {law!r} " + ("is allowed" if ok else f"not in {allowed}")),
            severity=rule.severity,
        )

    if isinstance(rule, FieldDependencyRuleDef):
        passed = (not present(fields, rule.antecedent_path)) or present(
            fields, rule.consequent_path
        )
        default = (
            f"{rule.consequent_path} present for {rule.antecedent_path}"
            if passed
            else f"{rule.antecedent_path} present but {rule.consequent_path} missing"
        )
        fmt = {"field_path": rule.antecedent_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, UniquenessVsHistoryRuleDef):
        val = fval(fields, rule.field_path)
        if val is None:
            return None
        dup = str(val) in ctx.prior_invoice_numbers
        passed = not dup
        default = (
            f"{rule.field_path} {val!r} "
            + ("already seen on another document" if dup else "is unique")
        )
        fmt = {"value": val, "field_path": rule.field_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, EqualityRuleDef):
        law = fval(fields, rule.field_path)
        if law is None:
            return None
        if rule.expected_field_path is not None:
            exp = fval(fields, rule.expected_field_path)
            if exp is None:
                return None
        else:
            exp = rule.expected
        ratio: float | None = None
        if rule.match_mode == "normalized":
            ok = _normalize_equality_value(str(law), rule) == _normalize_equality_value(
                str(exp), rule
            )
        elif rule.match_mode == "regex":
            flags = re.IGNORECASE if rule.case_insensitive else 0
            try:
                ok = re.fullmatch(str(exp), str(law), flags) is not None
            except re.error:
                return None
        elif rule.match_mode == "fuzzy":
            a_norm = _normalize_equality_value(str(law), rule)
            b_norm = _normalize_equality_value(str(exp), rule)
            ratio = difflib.SequenceMatcher(None, a_norm, b_norm).ratio()
            ok = ratio >= rule.fuzzy_threshold
        else:  # exact
            ok = str(law) == str(exp)
        ok = ok != rule.negate
        if ratio is not None:
            default = (
                f"{rule.field_path} {law!r} ~{ratio:.2f} "
                f"{'>=' if ok else '<'} {rule.fuzzy_threshold} vs {exp!r}"
            )
        else:
            default = f"{rule.field_path} {law!r} {'==' if ok else '!='} {exp!r}"
        fmt = {"value": law, "expected": exp, "field_path": rule.field_path}
        return Check(
            name=rule.name,
            passed=ok,
            detail=_detail(rule.detail_pass if ok else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, DateConstraintRuleDef):
        d = as_date(fval(fields, rule.field_path))
        if d is None:
            return None
        failures: list[str] = []
        if rule.not_future and d > date.today():
            failures.append("in the future")
        if rule.min:
            md = as_date(rule.min)
            if md is None:
                return None
            if d < md:
                failures.append(f"before {rule.min}")
        if rule.max:
            mx = as_date(rule.max)
            if mx is None:
                return None
            if d > mx:
                failures.append(f"after {rule.max}")
        if rule.before_field_path:
            bd = as_date(fval(fields, rule.before_field_path))
            if bd is None:
                return None
            if not d < bd:
                failures.append(f"not before {rule.before_field_path}")
        if rule.after_field_path:
            ad = as_date(fval(fields, rule.after_field_path))
            if ad is None:
                return None
            if not d > ad:
                failures.append(f"not after {rule.after_field_path}")
        passed = not failures
        default = (
            f"{rule.field_path} {d.isoformat()} ok"
            if passed
            else f"{rule.field_path} {d.isoformat()}: " + "; ".join(failures)
        )
        fmt = {"value": d.isoformat(), "field_path": rule.field_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, ExpressionRuleDef):
        result = evaluate_expression(rule.expression, fields)
        if result is None:
            return None
        passed = bool(result)
        default = f"{rule.expression} -> {result!r}"
        fmt = {"value": result, "expression": rule.expression}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, AggregateRuleDef):
        agg_value = aggregate_list(fields, rule.list_path, rule.agg, rule.sub_field)
        if agg_value is None:
            return None
        compare_to = (
            as_number(fval(fields, rule.compare_field_path))
            if rule.compare_field_path
            else rule.compare_value
        )
        if compare_to is None:
            return None
        if rule.op == "eq":
            passed = abs(agg_value - compare_to) <= rule.tolerance
        else:
            passed = _OPS[rule.op](agg_value, compare_to)
        sub = f".{rule.sub_field}" if rule.sub_field else ""
        default = (
            f"{rule.agg}({rule.list_path}{sub}) = {agg_value} {rule.op} {compare_to}"
        )
        fmt = {"value": agg_value, "expected": compare_to, "field_path": rule.list_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, NumericRangeRuleDef):
        v = as_number(fval(fields, rule.field_path))
        if v is None:
            return None
        failures: list[str] = []
        if rule.min is not None and v < rule.min:
            failures.append(f"below {rule.min}")
        if rule.max is not None and v > rule.max:
            failures.append(f"above {rule.max}")
        passed = not failures
        default = (
            f"{rule.field_path} {v} in range"
            if passed
            else f"{rule.field_path} {v}: " + "; ".join(failures)
        )
        fmt = {"value": v, "field_path": rule.field_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, PercentageToleranceRuleDef):
        a = as_number(fval(fields, rule.value_path))
        b = as_number(fval(fields, rule.reference_path))
        if a is None or b is None:
            return None
        if b == 0:
            return None
        ratio = abs(a - b) / abs(b)
        passed = ratio <= rule.pct
        default = f"|{a} - {b}| / |{b}| = {ratio:.4f} {'<=' if passed else '>'} {rule.pct}"
        fmt = {"value": a, "expected": b, "field_path": rule.value_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, FormatRuleDef):
        val = fval(fields, rule.field_path)
        if val is None:
            return None
        validator = FORMAT_VALIDATORS.get(rule.format)
        if validator is None:
            return None  # unknown format key -> skip defensively
        passed = validator(str(val))
        default = (
            f"{rule.field_path} {val!r} "
            + ("is a valid" if passed else "is not a valid")
            + f" {rule.format}"
        )
        fmt = {"value": val, "field_path": rule.field_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, ConditionalPresenceRuleDef):
        cond_present = present(fields, rule.condition_field_path)
        condition_met = cond_present and (
            rule.equals is None
            or str(fval(fields, rule.condition_field_path)) == rule.equals
        )
        passed = (not condition_met) or present(fields, rule.required_field_path)
        if passed and not condition_met:
            default = f"{rule.condition_field_path} condition not met"
        elif passed:
            default = f"{rule.required_field_path} present as required"
        else:
            default = (
                f"{rule.condition_field_path} met but {rule.required_field_path} missing"
            )
        fmt = {"field_path": rule.condition_field_path}
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, MutualExclusivityRuleDef):
        present_paths = [p for p in rule.field_paths if present(fields, p)]
        count = len(present_paths)
        passed = (count == 1) if rule.mode == "exactly_one" else (count <= 1)
        default = f"{count} of {len(rule.field_paths)} present ({rule.mode}): {present_paths}"
        fmt = {
            "field_path": rule.field_paths[0] if rule.field_paths else "",
            "present": present_paths,
            "count": count,
        }
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, AtLeastNOfRuleDef):
        count = sum(1 for p in rule.field_paths if present(fields, p))
        passed = count >= rule.n
        default = f"{count} of {len(rule.field_paths)} present (need >= {rule.n})"
        fmt = {
            "field_path": rule.field_paths[0] if rule.field_paths else "",
            "count": count,
        }
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, RequiredTogetherRuleDef):
        present_paths = [p for p in rule.field_paths if present(fields, p)]
        count = len(present_paths)
        passed = count == 0 or count == len(rule.field_paths)
        if passed:
            default = f"{count} of {len(rule.field_paths)} present (all-or-nothing)"
        else:
            missing = [p for p in rule.field_paths if p not in present_paths]
            default = f"present {present_paths} but missing {missing}"
        fmt = {
            "field_path": rule.field_paths[0] if rule.field_paths else "",
            "present": present_paths,
            "count": count,
        }
        return Check(
            name=rule.name,
            passed=passed,
            detail=_detail(rule.detail_pass if passed else rule.detail_fail, default, fmt),
            severity=rule.severity,
        )

    if isinstance(rule, CodedRuleDef):
        return rule.fn(fields, ctx)

    if isinstance(rule, LlmAdvisoryRuleDef):
        check = _evaluate_llm_advisory(rule, fields, ctx)
        # Structurally cap at "review": a soft LLM opinion can never hard-flag.
        check.severity = "review"
        return check

    raise ValueError(f"unknown rule type {type(rule).__name__!r}")  # pragma: no cover


def _evaluate_llm_advisory(
    rule: LlmAdvisoryRuleDef, fields: dict, ctx: DecisionContext
) -> Check:
    """Evaluate an LLM-advisory rule to a yes/no, never raising into the caller.

    ``passed=True`` means the answer to ``rule.question`` is "no" (no concern). A test
    hook (``_test_fn``) short-circuits the network call; any failure on either path
    degrades to a passing advisory so a broken LLM never blocks a document. The caller
    overwrites the severity to "review" regardless.
    """
    if rule._test_fn is not None:
        try:
            ans = rule._test_fn(fields, ctx)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            return Check(
                name=rule.name,
                passed=True,
                severity="advisory",
                detail=f"LLM advisory check unavailable: {exc}",
            )
        return Check(
            name=rule.name,
            passed=not ans,
            severity="advisory",
            detail=f"{rule.question} -> {'yes' if ans else 'no'}",
        )

    try:
        import openai  # lazy: optional dep

        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        client = openai.OpenAI(
            api_key=settings.openrouter_api_key, base_url=settings.decision_base_url
        )
        import json

        prompt = (
            f"Given these document fields (values only):\n{json.dumps(_values_only(fields), indent=2)}\n\n"
            f"Question: {rule.question}\n"
            'Answer ONLY with a JSON object: {"answer": "yes"|"no"}.'
        )
        response = client.chat.completions.create(
            model=settings.decision_model,
            messages=[
                {"role": "system", "content": "Answer the yes/no question about the document."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        ans = str(payload.get("answer", "")).strip().lower() == "yes"
    except Exception as exc:  # noqa: BLE001 — never raise into the caller
        return Check(
            name=rule.name,
            passed=True,
            severity="advisory",
            detail=f"LLM advisory check unavailable: {exc}",
        )
    return Check(
        name=rule.name,
        passed=not ans,
        severity="advisory",
        detail=f"{rule.question} -> {'yes' if ans else 'no'}",
    )


def build_ruleset(defn: DocTypeRuleDefinition) -> Ruleset:
    """Interpret a :class:`DocTypeRuleDefinition` into a runnable :class:`Ruleset` closure.

    The returned closure reads settings lazily (inside the loop, via ``_interpret``) so
    thresholds/allowed-lists can be tweaked live, and preserves rule order in its output.
    """

    def ruleset(fields: dict, ctx: DecisionContext) -> list[Check]:
        checks: list[Check] = []
        for rule in defn.rules:
            check = _interpret(rule, fields, ctx)
            if check is not None:
                checks.append(check)
        return checks

    return ruleset


__all__ = [
    "PresenceRuleDef",
    "ThresholdCompareRuleDef",
    "ArithmeticIdentityRuleDef",
    "SetMembershipRuleDef",
    "FieldDependencyRuleDef",
    "UniquenessVsHistoryRuleDef",
    "EqualityRuleDef",
    "DateConstraintRuleDef",
    "ExpressionRuleDef",
    "AggregateRuleDef",
    "NumericRangeRuleDef",
    "PercentageToleranceRuleDef",
    "FormatRuleDef",
    "ConditionalPresenceRuleDef",
    "MutualExclusivityRuleDef",
    "AtLeastNOfRuleDef",
    "RequiredTogetherRuleDef",
    "CodedRuleDef",
    "LlmAdvisoryRuleDef",
    "DocTypeRuleDefinition",
    "build_ruleset",
]
