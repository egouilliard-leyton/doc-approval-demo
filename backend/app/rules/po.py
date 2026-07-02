"""Purchase-order business rules.

A purchase order participates in the AP match as a reconciliation SOURCE (its
``po_number`` / ``vendor`` / ``total`` are compared against the invoice by the case
reconciler), not as a document that needs its own domain checks. So it carries the
minimal ruleset the codebase already supports — no rule primitives, just the fields worth
citing — expressed declaratively as :data:`PO_RULE_DEFINITION` and interpreted by
:func:`app.rules.definition.build_ruleset` exactly like invoice/contract.
"""

from __future__ import annotations

from .definition import DocTypeRuleDefinition

CITATION_PATHS = ["po_number", "vendor", "total"]


PO_RULE_DEFINITION = DocTypeRuleDefinition(
    name="po",
    citation_paths=CITATION_PATHS,
    rules=[],
)
