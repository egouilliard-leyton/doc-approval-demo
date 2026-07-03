"""Generation package: form-fill (Phase 1) + rich-HTML (Phase 2) template output.

Phase 1 (form-fill) waves cover the bindable field catalogue, flattening a structured
result to dotted-path values, enumerating a fillable PDF's AcroForm, and the AI/heuristic
mapper + fill/signature-stamp/generate path. Phase 2 Wave 1 adds the rich-HTML foundation:
source->HTML conversion (:mod:`convert`), placeholder binding (:mod:`binder`), and
HTML->PDF/DOCX rendering (:mod:`render`).
"""

from __future__ import annotations

from .authoring_agent import PROVIDERS as AUTHORING_PROVIDERS
from .authoring_agent import TOOL_SCHEMAS, run_authoring_agent
from .binder import BindOutcome, bind_html, render_field_placeholder
from .catalogue import FieldCatalogueEntry, field_catalogue
from .convert import ConvertResult, convert_docx, convert_pdf
from .forms import FillOutcome, TemplateFormField, enumerate_form_fields, fill_form
from .generate import (
    GenerateOutcome,
    GenerateRichOutcome,
    RenderedFile,
    generate_pdf,
    generate_rich,
)
from .mapper import PROVIDERS, suggest_mapping
from .render import RenderUnavailableError, render_docx, render_pdf
from .template_edits import apply_template_update, sanitize_template_html
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
    "generate_rich",
    "GenerateRichOutcome",
    "RenderedFile",
    "suggest_mapping",
    "PROVIDERS",
    "flatten_field_values",
    "resolve_path",
    "convert_docx",
    "convert_pdf",
    "ConvertResult",
    "bind_html",
    "BindOutcome",
    "render_field_placeholder",
    "render_pdf",
    "render_docx",
    "RenderUnavailableError",
    "apply_template_update",
    "sanitize_template_html",
    "run_authoring_agent",
    "AUTHORING_PROVIDERS",
    "TOOL_SCHEMAS",
]
