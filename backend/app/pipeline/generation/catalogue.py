"""Field catalogue: the flat, dotted-path menu of values a template may bind to.

Walks a doc type's Pydantic field model (the same ``InvoiceFields``/``ContractFields``
the structuring stage produces) into a list of leaf entries — one per bindable value.
Nested models recurse with a dotted-path prefix; list fields are expanded to a fixed
number of synthetic indices (``line_items.0.amount``, ``line_items.1.amount``, ...) so
the form-fill UI can offer concrete slots without a live document. Pure and offline —
it reads the class annotations only, never any extracted data.
"""

from __future__ import annotations

from typing import get_args, get_origin

from pydantic import BaseModel

from app.extraction import get_spec
from app.models import DocType
from app.schemas import FieldCatalogueEntry, FieldValue

# Leaf field names whose extracted value is numeric (see the ``to_number`` coercions
# in ``app/extraction``); everything else is treated as free text.
_NUMBER_LEAVES = {
    "qty",
    "unit_price",
    "amount",
    "subtotal",
    "tax",
    "total",
    "total_value",
    "liability_cap",
}


def _label_for(path: str) -> str:
    """Human label from a dotted path: title-case the last non-numeric segment."""
    segments = [seg for seg in path.split(".") if not seg.isdigit()]
    last = segments[-1] if segments else path
    return last.replace("_", " ").title()


def _kind_for(path: str) -> str:
    """Coarse value kind for a leaf, derived from its final path segment."""
    leaf = path.rsplit(".", 1)[-1]
    if leaf in _NUMBER_LEAVES:
        return "number"
    return "text"


def _walk(model: type[BaseModel], prefix: str, list_repeat: int, out: list[FieldCatalogueEntry]) -> None:
    """Recurse a Pydantic model's fields, appending a leaf entry per bindable value."""
    for name, info in model.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        annotation = info.annotation
        origin = get_origin(annotation)

        if origin is list:
            (inner,) = get_args(annotation) or (None,)
            for index in range(list_repeat):
                item_path = f"{path}.{index}"
                if isinstance(inner, type) and issubclass(inner, BaseModel) and inner is not FieldValue:
                    _walk(inner, item_path, list_repeat, out)
                else:
                    out.append(
                        FieldCatalogueEntry(
                            path=item_path, label=_label_for(item_path), kind=_kind_for(item_path)
                        )
                    )
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel) and annotation is not FieldValue:
            _walk(annotation, path, list_repeat, out)
        else:
            out.append(
                FieldCatalogueEntry(path=path, label=_label_for(path), kind=_kind_for(path))
            )


def field_catalogue(doc_type: DocType, list_repeat: int = 3) -> list[FieldCatalogueEntry]:
    """Flat, dotted-path menu of every bindable value for a document type.

    ``list_repeat`` fixes how many synthetic indices each list field expands to
    (``line_items.0..N-1``), so a template can bind repeated rows offline.
    """
    out: list[FieldCatalogueEntry] = []
    _walk(get_spec(doc_type).field_model, "", list_repeat, out)
    return out
