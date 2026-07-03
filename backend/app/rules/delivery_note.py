"""Delivery-note business rules.

A delivery note rounds out the AP 3-way match as a completeness-only member — its presence
(and, once structured, its received quantities) matters, but it carries no standalone
domain checks. So it uses the minimal ruleset the codebase already supports — no rule
primitives, just the fields worth citing — expressed declaratively as
:data:`DELIVERY_NOTE_RULE_DEFINITION` and interpreted by
:func:`app.rules.definition.build_ruleset` exactly like invoice/contract.
"""

from __future__ import annotations

from .definition import DocTypeRuleDefinition

CITATION_PATHS = ["delivery_note_no", "delivery_date", "vendor"]


DELIVERY_NOTE_RULE_DEFINITION = DocTypeRuleDefinition(
    name="delivery_note",
    citation_paths=CITATION_PATHS,
    rules=[],
)
