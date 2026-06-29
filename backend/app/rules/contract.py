"""Contract business rules (TASK Phase 5).

Expressed declaratively as :data:`CONTRACT_RULE_DEFINITION` (interpreted by
:func:`app.rules.definition.build_ruleset`); every contract rule reduces to a single
primitive, so no coded escape hatches are needed.
"""

from __future__ import annotations

from .definition import (
    DocTypeRuleDefinition,
    FieldDependencyRuleDef,
    PresenceRuleDef,
    SetMembershipRuleDef,
    ThresholdCompareRuleDef,
)

CITATION_PATHS = [
    "parties.0",
    "effective_date",
    "governing_law",
    "total_value",
    "termination_clause.text",
]


CONTRACT_RULE_DEFINITION = DocTypeRuleDefinition(
    name="contract",
    citation_paths=CITATION_PATHS,
    rules=[
        PresenceRuleDef(name="signatures_present", field_path="signatures_present", severity="hard"),
        FieldDependencyRuleDef(
            name="auto_renew_without_notice",
            antecedent_path="renewal_clause",
            consequent_path="termination_clause.notice_period",
            severity="hard",
        ),
        PresenceRuleDef(
            name="termination_clause_present",
            field_path="termination_clause.text",
            severity="review",
        ),
        PresenceRuleDef(name="liability_cap_present", field_path="liability_cap", severity="review"),
        SetMembershipRuleDef(
            name="governing_law_allowed",
            field_path="governing_law",
            severity="review",
            allowed_list_setting="contract_allowed_governing_law",
            match_mode="substring_ci",
            absent_behavior="advisory_pass",
            absent_severity="advisory",
            empty_list_behavior="skip",
        ),
        ThresholdCompareRuleDef(
            name="value_over_threshold",
            field_path="total_value",
            op="lte",
            threshold_setting="contract_value_review_threshold",
            severity="review",
        ),
    ],
)
