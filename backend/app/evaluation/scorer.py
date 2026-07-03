"""Pure scoring over plain dicts: a golden's expected values vs. a structuring result.

No DB / HTTP / pipeline imports — every function here works on the plain JSON shapes
``StructuredResult.fields`` uses, so the scorer is trivially unit-testable offline. The
value comparators are REUSED from the reconciler (``app.reconcile.tolerance``) so a
field "agrees" here under exactly the same money/date/string tolerance the cross-document
reconciler applies; number parsing reuses ``app.rules.base.as_number``.

``fields`` shapes (confirmed against the live dataclasses):
  * scalar / presence  -> a FieldValue dict at the top-level key.
  * ``list_composite``  -> a LIST of row dicts, each ``{sub_field: FieldValue-dict}``.
  * ``list_scalar``     -> a flat LIST of FieldValue dicts.
  * ``composite``       -> one nested ``{sub_field: FieldValue-dict}`` (dotted access).
"""

from __future__ import annotations

from app.config import settings
from app.reconcile.tolerance import infer_kind, values_agree
from app.rules.base import as_number


def _is_field_value(node: object) -> bool:
    """A dumped FieldValue node — a dict carrying a ``value`` key."""
    return isinstance(node, dict) and "value" in node


def _unwrap(cell: object) -> object:
    """Strip a FieldValue dict down to its ``value``; pass plain values through."""
    if _is_field_value(cell):
        return cell.get("value")
    return cell


def resolve_path(fields: dict, path: str) -> object | None:
    """Walk a dotted path into a ``fields``-shaped dict to a FieldValue leaf's value.

    Steps into nested composite dicts too, so ``"termination_clause.notice_period"``
    resolves through the composite to its sub-field's value. Returns ``None`` when any
    segment is missing or the path doesn't land on a FieldValue leaf.
    """
    node: object = fields
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    if _is_field_value(node):
        return node.get("value")
    return None


def infer_field_kind(path: str, expected_value: object) -> str:
    """The comparison kind for a field: ``"money"`` | ``"date"`` | ``"string"``.

    Thin wrapper over the reconciler's ``infer_kind`` (name + sample value), so the
    scorer and the cross-document reconciler classify fields identically.
    """
    return infer_kind(path, [expected_value])


def values_match(expected: object, actual: object, kind: str) -> tuple[bool, bool]:
    """Compare one value pair, returning ``(exact_match, normalized_match)``.

    ``exact`` is literal equality after minimal coercion — numbers compared as floats
    within a 1e-9 epsilon (so ``658.8 == 658.80``), strings ``.strip()``-compared, bools
    directly. ``normalized`` is ``exact`` OR agreement under the field's ``kind`` via the
    reconciler's ``values_agree`` (money/date tolerance, fuzzy string). Both ``None`` ->
    ``(True, True)``; exactly one ``None`` -> ``(False, False)``.
    """
    if expected is None and actual is None:
        return True, True
    if expected is None or actual is None:
        return False, False

    exact = _exact_equal(expected, actual)
    if exact:
        return True, True
    normalized = values_agree(kind, expected, actual, settings)
    return False, bool(normalized)


def _exact_equal(expected: object, actual: object) -> bool:
    """Literal equality after minimal coercion (see :func:`values_match`)."""
    # Bools first: ``bool`` is an ``int`` subclass, so guard before numeric coercion.
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    en, an = as_number(expected), as_number(actual)
    if en is not None and an is not None:
        return abs(en - an) <= 1e-9
    if en is not None or an is not None:
        return False  # one numeric, one not -> never exactly equal
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip() == actual.strip()
    return expected == actual


def score_scalar_fields(expected_fields: dict, actual_fields: dict) -> list[dict]:
    """One score row per expected scalar/dotted field.

    Each row is ``{path, expected, actual, kind, exact_match, normalized_match}``.
    """
    rows: list[dict] = []
    for path, expected in expected_fields.items():
        actual = resolve_path(actual_fields, path)
        kind = infer_field_kind(path, expected)
        exact, normalized = values_match(expected, actual, kind)
        rows.append(
            {
                "path": path,
                "expected": expected,
                "actual": actual,
                "kind": kind,
                "exact_match": exact,
                "normalized_match": normalized,
            }
        )
    return rows


def _normalize_row(row: object, columns: list[str]) -> dict:
    """Normalize one collection row to a plain ``{column: value}`` dict.

    A composite row (a dict keyed by column names, values either FieldValue dicts or
    already-plain golden values) is unwrapped per column. A list_scalar row (a FieldValue
    dict or a plain scalar) maps onto the single synthetic column.
    """
    if isinstance(row, dict) and not _is_field_value(row):
        return {c: _unwrap(row.get(c)) for c in columns}
    return {columns[0]: _unwrap(row)}


def _cell_score(exp_row: dict, act_row: dict, columns: list[str]) -> float:
    """Mean over columns of ``normalized_match`` (as 0/1) for one aligned row pair."""
    if not columns:
        return 0.0
    total = 0.0
    for c in columns:
        expected = exp_row.get(c)
        kind = infer_field_kind(c, expected)
        _, normalized = values_match(expected, act_row.get(c), kind)
        total += 1.0 if normalized else 0.0
    return total / len(columns)


def align_collection(
    expected_rows: list, actual_rows: list, columns: list[str]
) -> dict:
    """Greedily align two collections and score row + cell agreement.

    Generalized over ``list_composite`` (``columns`` = sub-field names) and
    ``list_scalar`` (a single synthetic column = the field name). Both sides are
    normalized to plain ``{column: value}`` dicts, an expected x actual similarity matrix
    of per-row cell scores is built, then a greedy bipartite match repeatedly takes the
    highest-scoring remaining pair (stopping when either pool empties or the best
    remaining score is 0.0). Unmatched expected rows are misses, unmatched actual rows are
    extras.

    Returns row precision/recall/F1, cell accuracy over MATCHED pairs only,
    ``line_item_score = row_f1 * cell_accuracy``, the matched count, expected/actual
    counts, and a per-matched-pair detail list.
    """
    exp_norm = [_normalize_row(r, columns) for r in expected_rows]
    act_norm = [_normalize_row(r, columns) for r in actual_rows]
    n_expected = len(exp_norm)
    n_actual = len(act_norm)

    # Similarity matrix, then greedy highest-first bipartite match.
    scored: list[tuple[float, int, int]] = []
    for i, exp in enumerate(exp_norm):
        for j, act in enumerate(act_norm):
            scored.append((_cell_score(exp, act, columns), i, j))
    scored.sort(key=lambda t: t[0], reverse=True)

    used_e: set[int] = set()
    used_a: set[int] = set()
    matched_pairs: list[tuple[int, int, float]] = []
    for score, i, j in scored:
        if i in used_e or j in used_a:
            continue
        if score == 0.0:
            break  # best remaining pair scores nothing -> not a real match
        used_e.add(i)
        used_a.add(j)
        matched_pairs.append((i, j, score))

    matched = len(matched_pairs)
    row_precision = matched / n_actual if n_actual else 1.0
    row_recall = matched / n_expected if n_expected else 1.0
    denom = row_precision + row_recall
    row_f1 = (2 * row_precision * row_recall / denom) if denom else 0.0

    if matched_pairs:
        cell_accuracy = sum(s for _, _, s in matched_pairs) / matched
    elif n_expected == 0 and n_actual == 0:
        cell_accuracy = 1.0
    else:
        cell_accuracy = 0.0

    detail = [
        {
            "expected_index": i,
            "actual_index": j,
            "expected": exp_norm[i],
            "actual": act_norm[j],
            "cell_score": round(s, 6),
        }
        for i, j, s in matched_pairs
    ]

    return {
        "row_precision": round(row_precision, 6),
        "row_recall": round(row_recall, 6),
        "row_f1": round(row_f1, 6),
        "cell_accuracy": round(cell_accuracy, 6),
        "line_item_score": round(row_f1 * cell_accuracy, 6),
        "matched": matched,
        "n_expected": n_expected,
        "n_actual": n_actual,
        "detail": detail,
    }


def _collection_columns(key: str, expected_rows: list) -> list[str]:
    """Column names for a collection: composite sub-fields, or the synthetic scalar col.

    A ``list_composite`` golden holds row dicts -> the ordered union of their keys. A
    ``list_scalar`` golden holds plain scalars (or is empty) -> one synthetic column named
    after the collection field.
    """
    if expected_rows and isinstance(expected_rows[0], dict):
        cols: list[str] = []
        for row in expected_rows:
            for k in row:
                if k not in cols:
                    cols.append(k)
        return cols
    return [key]


def score_extraction(golden, structured_fields: dict) -> dict:
    """Score a whole structuring result against a golden case.

    Runs :func:`score_scalar_fields` over ``expected_fields`` and
    :func:`align_collection` over each ``expected_collections`` key. ``field_accuracy_*``
    are the means of the scalar rows' exact/normalized flags. ``overall_score`` is the
    mean over ALL pooled leaf comparisons — every scalar field's ``normalized_match`` plus
    every matched/missing collection cell's per-cell score (extra actual rows are excluded
    from the pool; they only depress ``row_precision``).
    """
    field_scores = score_scalar_fields(golden.expected_fields, structured_fields)

    pool_sum = 0.0
    pool_count = 0
    exacts: list[float] = []
    norms: list[float] = []
    for row in field_scores:
        exacts.append(1.0 if row["exact_match"] else 0.0)
        norms.append(1.0 if row["normalized_match"] else 0.0)
        pool_sum += 1.0 if row["normalized_match"] else 0.0
        pool_count += 1

    collection_scores: dict[str, dict] = {}
    for key, expected_rows in golden.expected_collections.items():
        actual_rows = structured_fields.get(key)
        if not isinstance(actual_rows, list):
            actual_rows = []
        columns = _collection_columns(key, expected_rows)
        result = align_collection(expected_rows, actual_rows, columns)
        collection_scores[key] = result

        ncols = len(columns)
        for pair in result["detail"]:
            pool_sum += pair["cell_score"] * ncols
            pool_count += ncols
        missed = result["n_expected"] - result["matched"]  # unmatched expected rows
        pool_count += missed * ncols  # each missed cell contributes 0 to pool_sum

    field_accuracy_exact = round(sum(exacts) / len(exacts), 6) if exacts else 1.0
    field_accuracy_normalized = round(sum(norms) / len(norms), 6) if norms else 1.0
    overall_score = round(pool_sum / pool_count, 6) if pool_count else 1.0

    return {
        "overall_score": overall_score,
        "field_accuracy_exact": field_accuracy_exact,
        "field_accuracy_normalized": field_accuracy_normalized,
        "field_scores": field_scores,
        "collection_scores": collection_scores,
    }
