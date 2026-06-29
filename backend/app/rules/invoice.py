"""Invoice business rules (TASK Phase 5).

Each rule is deterministic and grounded in the structured fields; the agent's LLM
call adds narrative on top but cannot override a failed ``hard`` rule. The rule set is
expressed declaratively as :data:`INVOICE_RULE_DEFINITION` (interpreted by
:func:`app.rules.definition.build_ruleset`); the two cases that don't reduce to a single
primitive — the total-math degraded branch and the config-flipped bank-details rule —
stay as coded escape hatches below, copied verbatim from the original ``invoice_checks``.
"""

from __future__ import annotations

from app.config import settings
from app.schemas import Check

from .base import DecisionContext, as_number, fval, present
from .definition import (
    CodedRuleDef,
    DocTypeRuleDefinition,
    PresenceRuleDef,
    ThresholdCompareRuleDef,
    UniquenessVsHistoryRuleDef,
)

# Fields worth citing in the decision (those a reviewer would check first).
CITATION_PATHS = ["vendor", "invoice_no", "total", "subtotal", "tax"]


def _total_math_fn(fields: dict, ctx: DecisionContext) -> Check | None:
    """total = subtotal + tax (hard); advisory pass when components are absent."""
    # total = subtotal + tax (hard). Skipped when components are absent so we never
    # flag on missing data — that's the confidence gate's job, not a math failure.
    total = as_number(fval(fields, "total"))
    subtotal = as_number(fval(fields, "subtotal"))
    tax = as_number(fval(fields, "tax"))
    if total is not None and subtotal is not None and tax is not None:
        expected = subtotal + tax
        ok = abs(total - expected) <= settings.invoice_total_tolerance
        return Check(
            name="total_math",
            passed=ok,
            detail=(
                f"total {total:.2f} {'=' if ok else '≠'} subtotal {subtotal:.2f} "
                f"+ tax {tax:.2f} ({expected:.2f})"
            ),
            severity="hard",
        )
    else:
        return Check(
            name="total_math",
            passed=True,
            detail="not enough line-total data to verify (subtotal/tax/total)",
            severity="advisory",
        )


def _bank_details_fn(fields: dict, ctx: DecisionContext) -> Check | None:
    """Bank/payment details (advisory by default; hard when flagged in config)."""
    # Bank/payment details (advisory by default; hard when flagged in config). True
    # change-detection needs a vendor baseline — deferred; advisory avoids false flags.
    has_bank = present(fields, "bank_details_present")
    bank_severity = "hard" if settings.invoice_flag_on_bank_details else "advisory"
    return Check(
        name="bank_details",
        passed=not (has_bank and settings.invoice_flag_on_bank_details),
        detail=(
            "payment/bank details "
            + ("present — verify against vendor records" if has_bank else "not present")
        ),
        severity=bank_severity,
    )


INVOICE_RULE_DEFINITION = DocTypeRuleDefinition(
    name="invoice",
    citation_paths=CITATION_PATHS,
    rules=[
        CodedRuleDef(name="total_math", fn=_total_math_fn),
        UniquenessVsHistoryRuleDef(
            name="duplicate_invoice_no", field_path="invoice_no", severity="hard"
        ),
        ThresholdCompareRuleDef(
            name="auto_approve_threshold",
            field_path="total",
            op="lte",
            threshold_setting="invoice_auto_approve_max",
            severity="review",
        ),
        PresenceRuleDef(name="po_present", field_path="po_number", severity="advisory"),
        PresenceRuleDef(name="due_date_present", field_path="due_date", severity="advisory"),
        CodedRuleDef(name="bank_details", fn=_bank_details_fn),
    ],
)
