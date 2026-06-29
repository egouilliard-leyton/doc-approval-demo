"""Deterministic per-doc-type business rules for the agent decision layer.

The registry now lives in :mod:`app.doc_types` (which serves both built-in and custom
types). :func:`get_ruleset` / :func:`get_citation_paths` delegate there lazily — the
import is done inside the function body to avoid a circular import: ``app.doc_types``
imports the per-type modules in this package, so this package's ``__init__`` must not
import ``app.doc_types`` at module top.
"""

from __future__ import annotations

from .base import (
    DecisionContext,
    Ruleset,
    citations_from_grounding,
    cross_cutting_checks,
)


def get_ruleset(doc_type: str) -> Ruleset:
    """Return the rule set for a document type (delegates to the registry)."""
    from app import doc_types

    return doc_types.get_ruleset(doc_type)


def get_citation_paths(doc_type: str) -> list[str]:
    """Field paths to cite for a document type (delegates to the registry)."""
    from app import doc_types

    return doc_types.get_citation_paths(doc_type)


__all__ = [
    "DecisionContext",
    "Ruleset",
    "citations_from_grounding",
    "cross_cutting_checks",
    "get_citation_paths",
    "get_ruleset",
]
