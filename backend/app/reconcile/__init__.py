"""Cross-document case reconciliation (Phase 2 multi-document cases).

Turns a case's member documents into reconciled canonical fields: a candidate-bag model
(``candidates``), per-kind tolerance comparison (``tolerance``), and the grouped-by-document
exists-match agreement algorithm (``engine``). Deliberately layered ABOVE — and never
importing from — ``app.pipeline``.
"""

from __future__ import annotations

from .candidates import Candidate
from .engine import reconcile_case

__all__ = ["reconcile_case", "Candidate"]
