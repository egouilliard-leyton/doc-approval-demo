"""Database models (SQLModel tables) for documents and pipeline runs."""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _new_id() -> str:
    """A short, filesystem-friendly unique id (also used as the data/<id>/ dir name)."""
    return uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentStatus(str, Enum):
    """Lifecycle of a document through the 4-stage pipeline."""

    uploaded = "uploaded"
    prescanned = "prescanned"
    ocr_done = "ocr_done"
    structured = "structured"
    decided = "decided"
    needs_review = "needs_review"


class DocType(str, Enum):
    """The two document kinds this POC handles."""

    contract = "contract"
    invoice = "invoice"


class Document(SQLModel, table=True):
    """An uploaded document plus its ingestion metadata."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    filename: str
    doc_type: DocType | None = None
    mime: str
    page_count: int = 0
    status: DocumentStatus = Field(default=DocumentStatus.uploaded)
    created_at: datetime = Field(default_factory=_utcnow)


class PipelineRun(SQLModel, table=True):
    """A run of the pipeline against a document. Stage results accumulate as JSON.

    Defined now (Phase 1); the prescan/OCR/structure/decide stages populate
    ``stage_results`` in Phases 2-5.
    """

    id: str = Field(default_factory=_new_id, primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    status: str = "pending"
    stage_results: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class TemplateMode(str, Enum):
    """How a template renders its output."""

    form_fill = "form_fill"
    rich_html = "rich_html"


class TemplateStatus(str, Enum):
    """Lifecycle of a template through the authoring flow."""

    draft = "draft"
    ready = "ready"


class Template(SQLModel, table=True):
    """A reusable output template for a document type (Phase 0 registry)."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    name: str
    doc_type: DocType
    mode: TemplateMode = Field(default=TemplateMode.rich_html)
    source_file_id: str | None = None  # Phase 1 (source upload) will populate this
    html_body: str | None = None
    css: str | None = None
    form_field_map: dict = Field(default_factory=dict, sa_column=Column(JSON))
    placeholder_map: dict = Field(default_factory=dict, sa_column=Column(JSON))
    output_formats: list = Field(default_factory=lambda: ["pdf"], sa_column=Column(JSON))
    status: TemplateStatus = Field(default=TemplateStatus.draft)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class TemplateRevision(SQLModel, table=True):
    """A pre-update snapshot of a template's html/css, for edit history."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    template_id: str = Field(foreign_key="template.id", index=True)
    html: str | None = None
    css: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
