"""Accuracy-evaluation harness: score a structuring result against a golden fixture.

The pure scorer (:mod:`app.evaluation.scorer`) and the golden loader
(:mod:`app.evaluation.golden`) are import-cheap and side-effect free. The runner
(:mod:`app.evaluation.runner`) pulls in the DB + pipeline, so it is imported lazily on
first access to keep this package importable in pure unit tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.evaluation.golden import GoldenCase, get_golden, load_goldens
from app.evaluation.scorer import score_extraction

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.evaluation.runner import run_and_score, score_existing


def __getattr__(name: str):
    """Lazily expose the runner entrypoints without importing the DB/pipeline eagerly."""
    if name in ("run_and_score", "score_existing", "ensure_document"):
        from app.evaluation import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "GoldenCase",
    "load_goldens",
    "get_golden",
    "score_extraction",
    "run_and_score",
    "score_existing",
]
