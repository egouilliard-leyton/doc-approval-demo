"""Per-document-type extraction specs (prompt + few-shot + field model + assembly).

The registry now lives in :mod:`app.doc_types` (which serves both built-in and custom
types). :func:`get_spec` delegates there lazily — the import is done inside the function
body to avoid a circular import: ``app.doc_types`` imports the per-type modules in this
package, so this package's ``__init__`` must not import ``app.doc_types`` at module top.
"""

from __future__ import annotations

from .base import DocTypeSpec


def get_spec(doc_type: str) -> DocTypeSpec:
    """Return the extraction spec for a document type (delegates to the registry)."""
    from app import doc_types

    return doc_types.get_spec(doc_type)


__all__ = ["get_spec", "DocTypeSpec"]
