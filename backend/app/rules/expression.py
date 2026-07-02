"""A sandboxed AST-based formula evaluator for the declarative rule engine.

This is the *security boundary* for user-authored formula rules. A doc-type author
writes a small Python-flavoured boolean/arithmetic expression (e.g.
``gross == net + tax`` or ``abs(total - sum_of('line_items', 'amount')) <= 0.01``) and
this module decides — with a paranoid, default-deny whitelist — whether it is safe to run
and, if so, evaluates it against a document's structured ``fields`` dict.

Design invariants (do not relax without re-reading the whole module):

* **Default-deny.** Every AST node is checked against :data:`_ALLOWED`; anything not
  explicitly listed (attribute access, subscripting, lambdas, comprehensions, f-strings,
  ``**``/bitwise/shift operators, statements, …) is rejected before interpretation.
* **No attribute lookup, ever.** Calls resolve through a closed Python dict of pure
  helper functions (:data:`_HELPERS`); there is no ``getattr`` path an expression can
  reach, so classic ``().__class__.__bases__`` sandbox escapes cannot be expressed.
* **Total, never-raise evaluation.** :func:`evaluate_expression` re-checks the tree
  independently (never trusting that validation ran) and wraps the whole interpretation
  in a final ``except Exception: return None`` net, so an evaluator bug can never
  propagate into ``build_ruleset()``. ``None`` is the single, unambiguous *skip*
  sentinel: the grammar never legitimately produces ``None``.
* **DoS caps.** Raw length, node count and nesting depth are all bounded *before* the
  tree is interpreted, and ``**`` (power) is rejected outright.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .base import as_date, as_number, fval, present


class ExpressionError(Exception):
    """Raised for any structural / safety violation while checking a formula.

    Inside :func:`evaluate_expression` this also doubles as the internal *skip* signal —
    it (and every other exception) is swallowed by the top-level net and turned into
    ``None`` so a broken or unsafe formula never blocks the surrounding rule set.
    """


# --- DoS caps (checked BEFORE any interpretation) -----------------------------

_MAX_EXPR_LEN = 400  # raw string length, before parse
_MAX_NODES = 150  # total AST nodes (via ast.walk)
_MAX_DEPTH = 16  # maximum nesting depth (recursive pass)


# --- helper table (the ONLY callables an expression may reach) ----------------


@dataclass(frozen=True)
class _HelperSpec:
    """Arity + literal-argument contract + implementation for one helper name."""

    fn: Callable[[dict, list], object | None]
    min_args: int
    max_args: int
    literal_str_args: frozenset[int]  # positions that MUST be literal string constants


def list_items(fields: dict, list_path: str) -> list | None:
    """Resolve a dotted path to a list field's raw JSON items, or ``None``.

    Returns ``None`` when the path is absent, traverses through a non-dict, or the final
    node is not a list. The raw item objects (FieldValue nodes / composite rows) are
    returned untouched — callers extract values via :func:`app.rules.base.as_number`.
    """
    node: object = fields
    for part in str(list_path).split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node if isinstance(node, list) else None


def aggregate_list(
    fields: dict, list_path: str, agg: str, sub_field: str | None = None
) -> float | int | None:
    """Aggregate the numeric row values of a list field.

    Handles BOTH row shapes transparently:

    * **list_scalar** rows where the item *is* the FieldValue node (``"value" in item``);
      ``sub_field`` is ignored (e.g. ``parties``/``key_dates`` — ``[{"value": ...}]``).
    * **list_composite** rows where ``item[sub_field]`` is the FieldValue node
      (e.g. ``line_items`` — ``[{"desc": {...}, "amount": {...}}]``).

    ``count`` → raw row count (``0`` for a present-but-empty list). ``sum`` → ``0.0`` over
    zero numeric values. ``min``/``max``/``avg`` → ``None`` over zero numeric values.
    ``None`` throughout when ``list_path`` is absent or is not a list.
    """
    items = list_items(fields, list_path)
    if items is None:
        return None
    if agg == "count":
        return len(items)
    numbers: list[float] = []
    for item in items:
        fv_node: object = None
        if isinstance(item, dict):
            if "value" in item:  # list_scalar: item is the FieldValue node
                fv_node = item
            elif sub_field is not None:  # list_composite: dig into the sub-field
                fv_node = item.get(sub_field)
        if isinstance(fv_node, dict) and "value" in fv_node:
            n = as_number(fv_node.get("value"))
            if n is not None:
                numbers.append(n)
    if agg == "sum":
        return float(sum(numbers))
    if not numbers:
        return None
    if agg == "min":
        return min(numbers)
    if agg == "max":
        return max(numbers)
    if agg == "avg":
        return sum(numbers) / len(numbers)
    return None


# --- helper implementations (each pure + TOTAL: return a value or None) --------


def _h_sum_of(fields: dict, args: list) -> object | None:
    return aggregate_list(fields, args[0], "sum", args[1] if len(args) > 1 else None)


def _h_min_of(fields: dict, args: list) -> object | None:
    return aggregate_list(fields, args[0], "min", args[1] if len(args) > 1 else None)


def _h_max_of(fields: dict, args: list) -> object | None:
    return aggregate_list(fields, args[0], "max", args[1] if len(args) > 1 else None)


def _h_avg_of(fields: dict, args: list) -> object | None:
    return aggregate_list(fields, args[0], "avg", args[1] if len(args) > 1 else None)


def _h_count(fields: dict, args: list) -> object | None:
    return aggregate_list(fields, args[0], "count")


def _h_abs(fields: dict, args: list) -> object | None:
    n = as_number(args[0])
    return None if n is None else abs(n)


def _h_round(fields: dict, args: list) -> object | None:
    n = as_number(args[0])
    if n is None:
        return None
    ndigits = 0
    if len(args) > 1:
        nd = as_number(args[1])
        ndigits = int(nd) if nd is not None else 0
    ndigits = max(0, min(6, ndigits))
    return round(n, ndigits)


def _h_len(fields: dict, args: list) -> object | None:
    x = args[0]
    return None if x is None else len(str(x))


def _h_lower(fields: dict, args: list) -> object | None:
    x = args[0]
    return None if x is None else str(x).lower()


def _h_upper(fields: dict, args: list) -> object | None:
    x = args[0]
    return None if x is None else str(x).upper()


def _h_trim(fields: dict, args: list) -> object | None:
    x = args[0]
    return None if x is None else str(x).strip()


def _h_matches(fields: dict, args: list) -> object | None:
    value, pattern = args[0], args[1]
    if value is None:
        return None
    try:
        return re.fullmatch(str(pattern), str(value)) is not None
    except re.error:
        return None


def _h_days_between(fields: dict, args: list) -> object | None:
    da, db = as_date(args[0]), as_date(args[1])
    if da is None or db is None:
        return None
    return abs((db - da).days)


def _h_today(fields: dict, args: list) -> object | None:
    return date.today().isoformat()


def _h_to_date(fields: dict, args: list) -> object | None:
    d = as_date(args[0])
    return None if d is None else d.isoformat()


def _h_is_present(fields: dict, args: list) -> object | None:
    # TOTAL — never None; safe as a short-circuit guard.
    return present(fields, args[0])


def _h_field(fields: dict, args: list) -> object | None:
    return fval(fields, args[0])


_HELPERS: dict[str, _HelperSpec] = {
    "sum_of": _HelperSpec(_h_sum_of, 1, 2, frozenset({0, 1})),
    "min_of": _HelperSpec(_h_min_of, 1, 2, frozenset({0, 1})),
    "max_of": _HelperSpec(_h_max_of, 1, 2, frozenset({0, 1})),
    "avg_of": _HelperSpec(_h_avg_of, 1, 2, frozenset({0, 1})),
    "count": _HelperSpec(_h_count, 1, 1, frozenset({0})),
    "abs": _HelperSpec(_h_abs, 1, 1, frozenset()),
    "round": _HelperSpec(_h_round, 1, 2, frozenset()),
    "len": _HelperSpec(_h_len, 1, 1, frozenset()),
    "lower": _HelperSpec(_h_lower, 1, 1, frozenset()),
    "upper": _HelperSpec(_h_upper, 1, 1, frozenset()),
    "trim": _HelperSpec(_h_trim, 1, 1, frozenset()),
    "matches": _HelperSpec(_h_matches, 2, 2, frozenset({1})),
    "days_between": _HelperSpec(_h_days_between, 2, 2, frozenset()),
    "today": _HelperSpec(_h_today, 0, 0, frozenset()),
    "to_date": _HelperSpec(_h_to_date, 1, 1, frozenset()),
    "is_present": _HelperSpec(_h_is_present, 1, 1, frozenset({0})),
    "field": _HelperSpec(_h_field, 1, 1, frozenset({0})),
}


# --- AST node whitelist (default-deny) ----------------------------------------

_ALLOWED: frozenset[type] = frozenset(
    {
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.USub,
        ast.UAdd,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Call,
        ast.List,
        ast.Tuple,
    }
)


def _max_depth(node: ast.AST, depth: int = 0) -> int:
    """Deepest nesting level in the tree (root at depth 0)."""
    children = list(ast.iter_child_nodes(node))
    if not children:
        return depth
    return max(_max_depth(child, depth + 1) for child in children)


def _check_call(node: ast.Call) -> None:
    """Enforce the closed-helper-table call contract."""
    if node.keywords:
        raise ExpressionError("keyword arguments are not allowed")
    if not isinstance(node.func, ast.Name):
        raise ExpressionError("only direct helper calls are allowed (no attribute calls)")
    for arg in node.args:
        if isinstance(arg, ast.Starred):
            raise ExpressionError("*args are not allowed")
    fname = node.func.id
    spec = _HELPERS.get(fname)
    if spec is None:
        raise ExpressionError(f"unknown function: {fname!r}")
    n = len(node.args)
    if n < spec.min_args or n > spec.max_args:
        raise ExpressionError(
            f"{fname}() takes {spec.min_args}..{spec.max_args} positional args, got {n}"
        )
    for pos in spec.literal_str_args:
        if pos < n:
            arg = node.args[pos]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                raise ExpressionError(
                    f"{fname}() argument {pos} must be a literal string"
                )


def _check_node(node: ast.AST) -> None:
    """Structural whitelist for a single node (default-deny)."""
    t = type(node)
    if t not in _ALLOWED:
        raise ExpressionError(f"disallowed syntax: {t.__name__}")

    if t is ast.Constant:
        v = node.value  # type: ignore[attr-defined]
        # bool ⊂ int, so test bool FIRST; reject None/bytes/complex/Ellipsis/…
        if isinstance(v, bool) or isinstance(v, (int, float, str)):
            return
        raise ExpressionError(f"disallowed constant of type {type(v).__name__}")

    if t is ast.Name:
        if not isinstance(node.ctx, ast.Load):  # type: ignore[attr-defined]
            raise ExpressionError("names are read-only")
        if node.id.startswith("_"):  # type: ignore[attr-defined]
            raise ExpressionError(f"disallowed name: {node.id!r}")  # type: ignore[attr-defined]
        return

    if t in (ast.List, ast.Tuple):
        if not isinstance(node.ctx, ast.Load):  # type: ignore[attr-defined]
            raise ExpressionError("collections are read-only")
        for elt in node.elts:  # type: ignore[attr-defined]
            if not isinstance(elt, ast.Constant):
                raise ExpressionError("list/tuple elements must be literal constants")
        return

    if t is ast.Call:
        _check_call(node)  # type: ignore[arg-type]
        return


def parse_and_check(expr: str) -> ast.Expression:
    """Parse ``expr`` and fully validate it against the safety whitelist.

    Pure (no ``fields``): performs ``ast.parse(mode='eval')`` plus the structural
    whitelist, helper arity / literal-argument checks, leading-underscore ``Name``
    rejection, and the length / node-count / depth caps. Raises :class:`ExpressionError`
    with a precise reason on the first violation. Returns the validated
    :class:`ast.Expression` tree.
    """
    if not isinstance(expr, str):
        raise ExpressionError("expression must be a string")
    if len(expr) > _MAX_EXPR_LEN:
        raise ExpressionError(
            f"expression too long ({len(expr)} chars > {_MAX_EXPR_LEN})"
        )
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"syntax error: {exc.msg}") from exc

    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_NODES:
        raise ExpressionError(
            f"expression too complex ({len(nodes)} nodes > {_MAX_NODES})"
        )
    depth = _max_depth(tree)
    if depth > _MAX_DEPTH:
        raise ExpressionError(
            f"expression nested too deeply ({depth} > {_MAX_DEPTH})"
        )

    if not isinstance(tree, ast.Expression):  # pragma: no cover — mode='eval' guarantees it
        raise ExpressionError("expected a single expression")
    for node in nodes:
        _check_node(node)
    return tree


def validate_expression(expr: str, declared_field_names: set[str]) -> list[str]:
    """Save-time gate: return human-readable errors (empty list = OK). NEVER raises.

    Runs :func:`parse_and_check`, then resolves references against
    ``declared_field_names``: every bare ``Name`` (EXCLUDING a ``Call``'s ``func`` name,
    which is checked against the helper table instead) and the base name (before the
    first ``'.'``) of every literal string-path argument must be a declared field.
    """
    try:
        tree = parse_and_check(expr)
    except ExpressionError as exc:
        return [str(exc)]
    except Exception as exc:  # noqa: BLE001 — validate never raises
        return [f"invalid expression: {exc}"]

    errors: list[str] = []

    # Names that are the callee of a Call are function names, not field references.
    func_name_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func_name_ids.add(id(node.func))
            spec = _HELPERS.get(node.func.id)
            if spec is None:
                errors.append(f"unknown function '{node.func.id}'")
                continue
            for pos in spec.literal_str_args:
                if pos < len(node.args):
                    arg = node.args[pos]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        base = arg.value.split(".")[0]
                        if base and base not in declared_field_names:
                            errors.append(f"unknown field '{base}'")

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in func_name_ids:
            if node.id not in declared_field_names:
                errors.append(f"unknown field '{node.id}'")

    # De-duplicate while preserving first-seen order.
    seen: set[str] = set()
    deduped: list[str] = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            deduped.append(e)
    return deduped


# --- interpreter --------------------------------------------------------------


def _eval_boolop(node: ast.BoolOp, fields: dict) -> object | None:
    """Short-circuit ``and``/``or``. ``None`` (skip) propagates; a genuine falsy operand
    is decisive (``and`` → ``False``, ``or`` → keep scanning / ``False`` if all falsy).
    """
    if isinstance(node.op, ast.And):
        result: object = True
        for value_node in node.values:
            v = _eval_node(value_node, fields)
            if v is None:
                return None  # skip propagates
            if not v:
                return False  # decisive false, short-circuit
            result = v
        return result
    # Or
    for value_node in node.values:
        v = _eval_node(value_node, fields)
        if v is None:
            return None  # skip propagates
        if v:
            return True  # decisive true, short-circuit
    return False


def _eval_unaryop(node: ast.UnaryOp, fields: dict) -> object | None:
    v = _eval_node(node.operand, fields)
    if isinstance(node.op, ast.Not):
        return None if v is None else (not v)
    n = as_number(v)
    if n is None:
        return None
    return -n if isinstance(node.op, ast.USub) else +n


_BINOPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}


def _eval_binop(node: ast.BinOp, fields: dict) -> object | None:
    la = as_number(_eval_node(node.left, fields))
    ra = as_number(_eval_node(node.right, fields))
    if la is None or ra is None:
        return None  # arithmetic is numeric-only; anything else is a skip
    return _BINOPS[type(node.op)](la, ra)  # ZeroDivisionError caught by the top net


_CMP: dict[type, Callable[[object, object], bool]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _eval_compare(node: ast.Compare, fields: dict) -> object | None:
    left = _eval_node(node.left, fields)
    if left is None:
        return None
    for op, comparator in zip(node.ops, node.comparators):
        right = _eval_node(comparator, fields)
        if right is None:
            return None
        if not _CMP[type(op)](left, right):
            return False
        left = right  # chained: a < b < c
    return True


def _eval_call(node: ast.Call, fields: dict) -> object | None:
    spec = _HELPERS[node.func.id]  # func is a known helper Name (parse_and_check)
    args = [_eval_node(a, fields) for a in node.args]
    return spec.fn(fields, args)


def _eval_node(node: ast.AST, fields: dict) -> object | None:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        # Bare name -> scalar field value. fval requires a "value" key on the final
        # node, so a top-level list/composite resolves to None (can never leak).
        return fval(fields, node.id)
    if isinstance(node, ast.BoolOp):
        return _eval_boolop(node, fields)
    if isinstance(node, ast.UnaryOp):
        return _eval_unaryop(node, fields)
    if isinstance(node, ast.BinOp):
        return _eval_binop(node, fields)
    if isinstance(node, ast.Compare):
        return _eval_compare(node, fields)
    if isinstance(node, ast.Call):
        return _eval_call(node, fields)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(e, fields) for e in node.elts]
    raise ExpressionError(f"cannot evaluate node {type(node).__name__}")  # pragma: no cover


def evaluate_expression(expr: str, fields: dict) -> object | None:
    """Run-time evaluation. INDEPENDENTLY re-runs :func:`parse_and_check` (never trusting
    that validation ran), then interprets the tree against ``fields`` with short-circuit
    ``BoolOp`` semantics. Returns the Python result on success, or ``None`` on ANY failure
    (unsafe/invalid formula, missing field, evaluator bug) — the entire body is wrapped in
    a final net so nothing can propagate into ``build_ruleset()``.
    """
    try:
        tree = parse_and_check(expr)
        return _eval_node(tree.body, fields)
    except Exception:  # noqa: BLE001 — total by contract
        return None


__all__ = [
    "ExpressionError",
    "parse_and_check",
    "validate_expression",
    "evaluate_expression",
    "list_items",
    "aggregate_list",
]
