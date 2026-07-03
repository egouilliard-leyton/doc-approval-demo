"""Phase 1 (form-fill) generation package: catalogue, values, form enum + fill.

Waves 1+2 cover the offline foundation — the bindable field catalogue, flattening a
structured result to dotted-path values, and enumerating a fillable PDF's AcroForm.
Waves 3+4 add the AI/heuristic field mapper and the fill/signature-stamp/generate path.
"""

from __future__ import annotations

from .catalogue import FieldCatalogueEntry, field_catalogue
from .forms import FillOutcome, TemplateFormField, enumerate_form_fields, fill_form
from .generate import GenerateOutcome, generate_pdf
from .mapper import PROVIDERS, suggest_mapping
from .values import flatten_field_values, resolve_path

__all__ = [
    "FieldCatalogueEntry",
    "field_catalogue",
    "TemplateFormField",
    "enumerate_form_fields",
    "fill_form",
    "FillOutcome",
    "generate_pdf",
    "GenerateOutcome",
    "suggest_mapping",
    "PROVIDERS",
    "flatten_field_values",
    "resolve_path",
]
