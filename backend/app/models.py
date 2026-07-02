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
    doc_type: str | None = None
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


class CaseRun(SQLModel, table=True):
    """A run of the cross-document reasoning against a case (Phase 2).

    Mirrors :class:`PipelineRun` field-for-field but keyed by case rather than document:
    the classify / reconcile / decide stage results accumulate as JSON under
    ``stage_results``. Lands via ``create_all`` like every other table here.
    """

    id: str = Field(default_factory=_new_id, primary_key=True)
    case_id: str = Field(foreign_key="case.id", index=True)
    status: str = "pending"
    stage_results: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class DocTypeDefinitionRow(SQLModel, table=True):
    """Persisted definition of a document type (built-in or custom).

    Built-in types (invoice, contract) are mirrored here for the future UI/CRUD layer but
    always resolve from code at runtime; custom types are rebuilt from these stored JSON
    definitions by :func:`app.doc_types.register_from_row`.
    """

    name: str = Field(primary_key=True)
    label: str
    icon: str = ""
    extraction_definition: dict = Field(default_factory=dict, sa_column=Column(JSON))
    rule_definition: dict = Field(default_factory=dict, sa_column=Column(JSON))
    citation_paths: list = Field(default_factory=list, sa_column=Column(JSON))
    builtin: bool = False
    version: int = 1
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class FieldCorrectionRow(SQLModel, table=True):
    """A reviewer's correction to an extracted field, kept for the audit trail.

    One row per (document, field_path) — re-editing the same field updates ``new_value``
    while ``original_value`` stays pinned to the model's first extraction. This log
    powers the future "corrections" review (edited fields signal extraction errors).
    """

    id: str = Field(default_factory=_new_id, primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    doc_type: str = ""
    field_path: str
    original_value: object | None = Field(default=None, sa_column=Column(JSON))
    new_value: object | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Case(SQLModel, table=True):
    """A case grouping N documents for cross-document reasoning (Phase 1).

    A case is either an OPEN pile (``case_type is None``) or bound to a registered
    case type (e.g. ``ap_match``). The cross-document reconciliation result lands here
    in Phase 2; Phase 1 only groups its member documents' existing structured results.
    """

    id: str = Field(default_factory=_new_id, primary_key=True)
    case_type: str | None = None
    label: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class CaseMembership(SQLModel, table=True):
    """Links a document to a case (a document belongs to at most one case).

    ``document_id`` is the primary key, so a document can appear in at most one case;
    associating a document already in another case silently reassigns it (upsert by
    document). Documents survive a case deletion — only the membership rows are removed.
    """

    document_id: str = Field(foreign_key="document.id", primary_key=True)
    case_id: str = Field(foreign_key="case.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class CaseTypeDefinitionRow(SQLModel, table=True):
    """Persisted definition of a case type (built-in or custom).

    Mirrors :class:`DocTypeDefinitionRow`. Case-type definitions are fully
    JSON-serializable (no callables), so custom types are rebuilt directly from these
    stored rows by :func:`app.case_types.register_from_row` with no code-vs-DB split.
    """

    name: str = Field(primary_key=True)
    label: str
    icon: str = ""
    members: list = Field(default_factory=list, sa_column=Column(JSON))
    canonical_fields: dict = Field(default_factory=dict, sa_column=Column(JSON))
    builtin: bool = False
    version: int = 1
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class VlmEngineRow(SQLModel, table=True):
    """A vision-language OCR engine the user has connected (one OpenRouter model each).

    Every VLM engine is just a different OpenRouter model slug behind the same
    OpenAI-compatible API, so connecting a new model is a row here — no code change.
    ``key`` is the url-safe id used in ``?engine=``, the ``stage_results["ocr"][key]``
    store, and the frontend selector; ``model`` is the OpenRouter slug. Docling and
    mock stay code-defined (they aren't VLMs); only these rows are data-driven.
    """

    key: str = Field(primary_key=True)
    label: str
    model: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
