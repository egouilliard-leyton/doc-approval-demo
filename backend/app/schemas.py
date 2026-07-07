"""API response models (decoupled from the ORM tables)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models import DocType, DocumentStatus, TemplateMode, TemplateStatus


class DocumentSummary(BaseModel):
    """Compact shape for the list view."""

    id: str
    filename: str
    doc_type: str | None
    mime: str
    page_count: int
    status: DocumentStatus
    created_at: datetime
    case_id: str | None = None  # the case this document belongs to, if any


class PageInfo(BaseModel):
    """One rasterized page + its preview, addressed via the /files static mount."""

    page: int
    image_url: str
    thumbnail_url: str


class DocumentDetail(DocumentSummary):
    """List fields plus per-page image/thumbnail URLs."""

    pages: list[PageInfo]


# --- Phase 0: template registry ----------------------------------------------


class TemplateSummary(BaseModel):
    """Compact shape for the template list view."""

    id: str
    name: str
    doc_type: DocType
    mode: TemplateMode
    status: TemplateStatus
    output_formats: list[str]
    created_at: datetime
    updated_at: datetime


class TemplateFormField(BaseModel):
    """One enumerated AcroForm field of a template's source PDF (Phase 1 form-fill)."""

    name: str
    kind: str  # "text" | "checkbox" | "radio" | "choice" | "signature"
    page: int
    rect: list[float] | None = None  # [x0, y0, x1, y1] in PDF user space
    options: list[str] | None = None
    nearby_label: str | None = None


class FieldCatalogueEntry(BaseModel):
    """One bindable leaf value a template can map onto (Phase 1 form-fill)."""

    path: str  # dotted path into a structured result, e.g. "line_items.0.amount"
    label: str
    kind: str  # "scalar" | "number" | "text"


class TemplateLint(BaseModel):
    """Advisory placeholder<->doc-type consistency check (Phase 5)."""

    orphaned_paths: list[str] = []  # referenced paths the doc type's catalogue no longer offers
    bound_count: int = 0  # placeholder/mapping occurrences resolving to a known path
    total_count: int = 0  # total occurrences referencing any path


class TemplateDetail(TemplateSummary):
    """List fields plus the template body, styles, and field/placeholder maps."""

    source_file_id: str | None
    source_url: str | None = None
    html_body: str | None
    css: str | None
    form_fields: list[TemplateFormField] = []
    form_field_map: dict
    placeholder_map: dict
    # Spreadsheet mode: the field->cell mapping + enumerated sheet metadata (both empty
    # for non-spreadsheet templates). Additive/default so existing responses are unchanged.
    cell_map: dict = {}
    spreadsheet_sheets: list = []
    lint: TemplateLint = TemplateLint()


class TemplateRevisionInfo(BaseModel):
    """A single pre-update snapshot of a template's html/css."""

    id: str
    html: str | None
    css: str | None
    note: str | None
    created_at: datetime


class TemplateCreate(BaseModel):
    """Request body to create a template."""

    name: str
    doc_type: DocType
    mode: TemplateMode = TemplateMode.rich_html


class TemplateUpdate(BaseModel):
    """Partial update; every field is optional (only provided fields are applied)."""

    name: str | None = None
    html_body: str | None = None
    css: str | None = None
    form_field_map: dict | None = None
    placeholder_map: dict | None = None
    cell_map: dict | None = None  # spreadsheet mode: field->cell mapping
    output_formats: list[str] | None = None
    status: TemplateStatus | None = None
    revision_note: str | None = None


# --- Phase 1 (form-fill): AI mapping + generation (Waves 3+4) -----------------


class MappingSuggestion(BaseModel):
    """A suggested binding for one PDF form field (Wave 3 AI/heuristic mapper)."""

    field_path: str | None = None  # catalogue path to bind, or None if unmatched
    confidence: float | None = None  # 0-1 (heuristic overlap score or LLM confidence)
    source: str = "heuristic"  # "ai" (LLM) | "heuristic" (offline token overlap)
    is_signature: bool = False  # this field is a signature target (stamp, not text)
    rationale: str | None = None


class MappingSuggestResponse(BaseModel):
    """Response of ``POST /templates/{id}/suggest-mapping`` (not persisted)."""

    suggestions: dict[str, MappingSuggestion]  # keyed by PDF field name
    provider_used: str  # "llm" | "mock" (reflects the actual, post-fallback provider)


class GenerateOutputFile(BaseModel):
    """One rendered output file of ``POST /templates/{id}/generate`` (Phase 2)."""

    format: str  # "pdf" | "docx"
    output_id: str
    output_url: str


class GenerateResult(BaseModel):
    """Response of ``POST /templates/{id}/generate``: the filled output(s) + trace.

    ``output_url``/``output_id`` remain the primary (first/PDF) output for the form-fill
    path; ``outputs`` lists every rendered file (Phase 2 rich-HTML may emit PDF + DOCX).
    """

    output_url: str
    output_id: str
    filled_fields: list[str]
    skipped_fields: list[str]
    signature_stamped: bool
    warnings: list[str] = []
    outputs: list[GenerateOutputFile] = []


# --- Spreadsheet templates (xlsx mode) ---------------------------------------

# A spreadsheet template is a plain .xlsx uploaded as the source; the author visually
# binds catalogue fields to cells (scalars) and list fields to a table anchor + column
# layout. openpyxl fills the workbook; LibreOffice headless recomputes formulas for the
# computed preview / PDF. These models mirror ``Template.cell_map`` (the mapping) and the
# grid/preview payloads the mapping + preview UIs render.


class SpreadsheetSheetMeta(BaseModel):
    """One worksheet's dimensions + layout, enumerated at source-upload time."""

    name: str  # ws.title
    max_row: int
    max_col: int
    merges: list[str] = []  # A1-style merged ranges, e.g. "A1:B2"
    col_widths: dict[str, float] = {}  # column letter -> width (only where set)


class SpreadsheetCell(BaseModel):
    """One rendered grid cell: its address, display value, and formatting hints.

    ``is_formula`` marks a cell whose stored value is a formula string; ``computed`` is
    ``False`` only in a preview fallback where the formula couldn't be evaluated (its
    ``value`` is then the raw formula string).
    """

    row: int  # 1-based
    col: int  # 1-based
    address: str  # A1
    value: str | None = None  # display string
    is_formula: bool = False
    number_format: str | None = None
    computed: bool = True


class SpreadsheetGrid(BaseModel):
    """A (capped) sheet grid for the mapping UI: non-empty cells + merged ranges."""

    sheet: str
    max_row: int
    max_col: int
    merges: list[str] = []
    cells: list[SpreadsheetCell]


class SpreadsheetScalarBinding(BaseModel):
    """One scalar binding: a catalogue ``field_path`` written into a single ``cell``."""

    sheet: str
    cell: str  # A1 address
    field_path: str
    suffix: str | None = None  # number_format unit (numeric) or literal concat (text)
    is_signature: bool = False  # reserved; always False this build


class SpreadsheetTableColumnBinding(BaseModel):
    """One column of a table binding: a record-relative field written to a column."""

    order: int  # write/display order (independent of extraction order)
    col: str  # target column letter, e.g. "A"
    field_path: str  # record-relative (sub-model field name; "" = the record's own value)
    suffix: str | None = None


class SpreadsheetTableBinding(BaseModel):
    """A table binding: a list field expanded down rows from an anchor cell."""

    sheet: str
    list_path: str  # top-level list field, e.g. "line_items"
    anchor_cell: str  # A1 address of the first data row's first column
    row_mode: Literal["fill_next_empty_row", "insert_row"] = "fill_next_empty_row"
    columns: list[SpreadsheetTableColumnBinding] = []


class SpreadsheetMapping(BaseModel):
    """The full field->cell mapping persisted in ``Template.cell_map``."""

    scalars: list[SpreadsheetScalarBinding] = []
    tables: list[SpreadsheetTableBinding] = []


class FieldListCatalogueEntry(BaseModel):
    """One bindable top-level list field + its record-relative columns.

    ``columns`` are the sub-model's leaf fields for a ``list_composite`` (their ``path`` is
    the record-relative field name); a ``list_scalar`` collection yields a single sentinel
    column with ``path=""`` (the record's own value).
    """

    list_path: str  # top-level list field, e.g. "line_items" or "parties"
    label: str
    columns: list[FieldCatalogueEntry] = []


class SpreadsheetPreviewSheet(BaseModel):
    """One sheet of a computed preview: its grid + whether formulas were computed."""

    name: str
    max_row: int
    max_col: int
    merges: list[str] = []
    cells: list[SpreadsheetCell]
    computed: bool = True  # False -> formula cells show their raw formula string


class SpreadsheetPreviewResponse(BaseModel):
    """Response of the spreadsheet preview: the computed sheets + a degraded flag."""

    sheets: list[SpreadsheetPreviewSheet]
    computed: bool  # False when LibreOffice recompute was unavailable (fallback shown)
    warnings: list[str] = []


# --- Phase 2: pre-flight / quality metrics -----------------------------------

# Advisory only at this stage; the pipeline never hard-fails here.
Verdict = Literal["pass", "warn"]


class MetricResult(BaseModel):
    """One pre-flight metric: its measured value, verdict, and the threshold used."""

    value: float
    verdict: Verdict
    threshold: float | None = None


class PageQuality(BaseModel):
    """Pre-flight metrics + optional cleaned-image URLs for a single page."""

    page: int
    width_px: int
    height_px: int
    resolution: MetricResult  # value = effective DPI
    sharpness: MetricResult  # value = variance of Laplacian
    contrast: MetricResult  # value = pixel std
    brightness: MetricResult  # value = pixel mean
    skew_angle_deg: float
    verdict: Verdict  # worst metric on this page
    reasons: list[str]  # human-readable notes for non-pass metrics
    deskewed: bool = False
    image_url: str  # raw rasterized page
    deskewed_url: str | None = None
    gray_url: str | None = None
    thresh_url: str | None = None


class QualityReport(BaseModel):
    """Document-level pre-flight result, persisted on the pipeline run."""

    document_id: str
    status: DocumentStatus  # always `prescanned` at this stage
    verdict: Verdict  # worst page verdict
    reasons: list[str]  # aggregated, page-prefixed, deduped
    preprocess_applied: bool
    pages: list[PageQuality]


# --- Phase 3: OCR engine layer ------------------------------------------------

# Pixel-space box on the source page, [x0, y0, x1, y1] (top-left origin).
BBox = tuple[float, float, float, float]


class OCRBlock(BaseModel):
    """One recognized region: text + its location + (optional) confidence."""

    page: int
    text: str
    bbox: BBox
    confidence: float | None = None  # 0-1; None when the engine doesn't expose it
    label: str = "text"  # text | table | title | figure | formula | seal | ...


class OCRTable(BaseModel):
    """A detected table, captured as markdown (engines that expose structure)."""

    page: int
    bbox: BBox | None = None
    n_rows: int = 0
    n_cols: int = 0
    markdown: str = ""
    confidence: float | None = None


class OCRPage(BaseModel):
    """Per-page OCR output, normalized across engines."""

    page: int
    text: str
    blocks: list[OCRBlock]
    tables: list[OCRTable]
    avg_confidence: float | None = None  # mean over blocks that report confidence
    char_count: int = 0
    markdown_url: str | None = None  # /files URL for the saved page markdown, if any


class OCRResult(BaseModel):
    """Document-level OCR result, persisted on the run keyed by engine name."""

    document_id: str
    status: DocumentStatus  # `ocr_done` at this stage
    engine_name: str
    engine_version: str
    device: str
    full_text: str
    pages: list[OCRPage]
    avg_confidence: float | None = None  # document-wide mean of per-block confidence
    table_count: int = 0
    latency_ms: int = 0
    warnings: list[str] = []  # seals noted, low confidence, no-table-support, etc.
    # Multi-engine routing trail: the engines tried (in order) before one produced
    # this result. Additive/default-empty so previously persisted OCR JSON still loads.
    attempted_engines: list[str] = []


# --- Phase 4: structuring / extraction ----------------------------------------

# Where a field came from. Char offsets index into OCRResult.full_text (the text
# handed to the extractor); `page` is the 1-based page that offset falls on.
Alignment = Literal["exact", "partial", "ungrounded"]


class Grounding(BaseModel):
    """Source location for one extracted field, for the hover-to-highlight UI."""

    page: int | None = None  # None when the span couldn't be located in the source
    char_start: int | None = None
    char_end: int | None = None
    snippet: str | None = None  # the matched source substring (the verbatim span)
    alignment: Alignment | None = None
    # Spatial grounding (signature post-pass): a pixel bbox on the page and the saved
    # crop URL. Both optional/None so text-grounded fields are unaffected.
    bbox: BBox | None = None
    image_url: str | None = None  # /files URL for a saved crop of the grounded region
    # Case reconciliation (Phase 2): which member document this span came from, so a
    # reconciled canonical value can cite its source document. None for single-doc use.
    document_id: str | None = None


class FieldValue(BaseModel):
    """A single extracted field: its value, confidence, and source grounding.

    A missing field is an explicit ``value=None`` with low confidence — never a
    hallucinated value (cross-cutting checklist).
    """

    value: str | float | int | bool | None = None
    confidence: float = 0.0  # 0-1; alignment quality x propagated OCR confidence
    grounding: Grounding | None = None
    # Human-in-the-loop correction: set when a reviewer edits the extracted value.
    # ``original_value`` preserves the model's first extraction for the audit trail.
    edited: bool = False
    original_value: str | float | int | bool | None = None


class StructuredResult(BaseModel):
    """Document-level structuring result, persisted under stage_results["structure"]."""

    document_id: str
    status: DocumentStatus  # `structured` at this stage
    doc_type: str
    provider: str  # "langextract" | "mock"
    model: str  # extractor model slug (or "mock")
    ocr_engine: str  # which OCR result this was built from
    fields: dict  # validated InvoiceFields/ContractFields, dumped to JSON
    extraction_confidence: float  # overall 0-1 (mean over the doc type's core fields)
    grounding_map: dict[str, Grounding] = {}  # flat field path -> grounding, for the UI
    warnings: list[str] = []
    latency_ms: int = 0
    fallback_used: bool = False  # True if the Docling table backfill filled a field
    raw_artifact_url: str | None = None  # /files URL to the saved extractor output


# --- Phase 5: agent decision -------------------------------------------------

# The agent verdict. `flag` = a rule definitively failed; `needs_review` = can't
# confidently auto-approve (low confidence / poor scan / over threshold).
Decision = Literal["approve", "flag", "needs_review"]
# How a failed check steers the decision (see app/rules + the reconcile step):
# hard -> forces `flag`; review -> caps at `needs_review`; advisory -> note only.
Severity = Literal["hard", "review", "advisory"]


class Check(BaseModel):
    """One deterministic business-rule outcome, surfaced as the decision trace."""

    name: str
    passed: bool
    detail: str  # human-readable, e.g. "total 135.00 = subtotal 125.00 + tax 10.00"
    severity: Severity


class Citation(BaseModel):
    """Ties a decision-relevant field back to its source location."""

    field: str  # dotted field path, e.g. "total"
    source: str  # e.g. "page 1"
    # Case reconciliation (Phase 2): which member document this citation points at, so a
    # reconciled canonical value can cite its source document. None for single-doc use.
    document_id: str | None = None


class DecisionResult(BaseModel):
    """Document-level decision, persisted under stage_results["decide"]."""

    document_id: str
    status: DocumentStatus  # `decided` (approve/flag) | `needs_review`
    doc_type: str
    provider: str  # "llm" | "mock"
    model: str  # decision model slug (or "mock")
    decision: Decision
    confidence: float  # 0-1
    reasons: list[str]  # human-readable bullets (LLM judgment + any code-forced reason)
    checks: list[Check]  # authoritative, code-computed rule-by-rule trace
    citations: list[Citation] = []  # built from the structured grounding_map
    llm_decision: Decision | None = None  # what the LLM proposed before reconciliation
    warnings: list[str] = []
    latency_ms: int = 0


# --- Phase 3 Wave 2: configurable doc-type CRUD ------------------------------


class DocTypeResponse(BaseModel):
    """A document type's full definition as returned by the CRUD endpoints."""

    name: str
    label: str
    icon: str
    extraction_definition: dict
    rule_definition: dict
    citation_paths: list[str]
    preferred_ocr_engine: str | None = None
    ocr_fallback_engines: list[str] = []
    builtin: bool
    version: int
    created_at: datetime
    updated_at: datetime


class DocTypeCreate(BaseModel):
    """Payload to create a custom document type (always non-built-in, version 1)."""

    name: str
    label: str
    icon: str = ""
    extraction_definition: dict
    rule_definition: dict
    citation_paths: list[str] = []
    preferred_ocr_engine: str | None = None
    ocr_fallback_engines: list[str] = []


class DocTypeUpdate(BaseModel):
    """Full-replace payload for a custom document type (everything but ``name``).

    A PUT replaces the editable definition wholesale rather than patching individual
    keys: the editor always holds the complete definition, so a full replace keeps the
    stored row consistent and avoids partial-update ambiguity. The immutable ``name`` is
    taken from the URL path.
    """

    label: str
    icon: str = ""
    extraction_definition: dict
    rule_definition: dict
    citation_paths: list[str] = []
    preferred_ocr_engine: str | None = None
    ocr_fallback_engines: list[str] = []


class DocTypeRoutingUpdate(BaseModel):
    """Narrow OCR-routing patch for a doc type (built-in OR custom).

    Touches ONLY the multi-engine routing columns — never the extraction/rule
    definition — so it stays allowed for built-in types whose *definition* is
    read-only. Both names are permissive (not validated against the live engine
    registry; unknown/disabled names are skipped gracefully at resolution time).
    """

    preferred_ocr_engine: str | None = None
    ocr_fallback_engines: list[str] = []


class DocTypePreviewRequest(BaseModel):
    """Run the structuring + rules pipeline over ad-hoc sample text for a doc type."""

    sample_text: str
    provider: str = "mock"


class DocTypePreviewResponse(BaseModel):
    """Preview output: the extracted fields plus the rule checks they trigger."""

    doc_type: str
    fields: dict
    extraction_confidence: float
    checks: list[Check]
    warnings: list[str] = []


# --- Phase 3 Wave 1: AI doc-type wizard --------------------------------------


class AssistMessage(BaseModel):
    """One turn in the wizard transcript exchanged with the assistant agent."""

    role: Literal["user", "assistant"]
    content: str


class AssistRequest(BaseModel):
    """Everything the wizard knows when asking the assistant for its next turn.

    The transcript (``messages``) plus the ingested document texts, the spec drafted so
    far, and any annotations collected from the last Plannotator review round.
    """

    messages: list[AssistMessage] = []
    process_docs: list[str] = []
    example_docs: list[str] = []
    spec_markdown: str = ""
    annotations: list[dict] = []


class AssistResponse(BaseModel):
    """The assistant's next turn: clarifying questions, the updated spec, and — when the
    design is complete — the validated ``draft_doctype`` ready to create."""

    questions: list[str]
    updated_spec_markdown: str
    done: bool
    draft_doctype: DocTypeCreate | None
    warnings: list[str]


class IngestResponse(BaseModel):
    """Plain text extracted from one uploaded process/example document."""

    text: str
    filename: str
    kind: Literal["process", "example"]


class AnnotateStartResponse(BaseModel):
    """A launched Plannotator annotation session: its id and the URL to open."""

    session_id: str
    url: str


class AnnotatePollResponse(BaseModel):
    """Annotation session status; ``decision``/``feedback``/``raw`` are set once done."""

    status: Literal["pending", "done"]
    decision: str | None = None
    feedback: str | None = None
    raw: dict | None = None


# --- OCR engines -------------------------------------------------------------


class EngineInfo(BaseModel):
    """One selectable OCR engine for the upload picker (docling + enabled VLMs)."""

    key: str
    label: str
    kind: Literal["layout", "vlm", "external"]


class VlmEngineResponse(BaseModel):
    """A connected VLM engine row, for the settings/catalog view."""

    key: str
    label: str
    model: str
    enabled: bool


class EngineCreate(BaseModel):
    """Connect a new VLM engine. ``key`` is derived from the model slug if omitted."""

    label: str
    model: str
    key: str | None = None
    enabled: bool = True


class EngineUpdate(BaseModel):
    """Patch an existing VLM engine (enable/disable or relabel)."""

    label: str | None = None
    enabled: bool | None = None


class OpenRouterModel(BaseModel):
    """An image-capable model offered by OpenRouter, for the add-model dropdown."""

    id: str
    name: str


# --- field edits / corrections -----------------------------------------------


class FieldEditRequest(BaseModel):
    """Reviewer edit to one structured field, addressed by its dotted path."""

    path: str  # e.g. "invoice_no" or "line_items.0.amount"
    value: str | float | int | bool | None


class FieldCorrection(BaseModel):
    """A logged correction: what the model extracted vs. what the reviewer set."""

    document_id: str
    doc_type: str
    field_path: str
    original_value: str | float | int | bool | None
    new_value: str | float | int | bool | None
    created_at: datetime
    updated_at: datetime


class CorrectionExample(BaseModel):
    """One document's corrections rolled up as a training-style example row.

    Emitted by the ``examples``-shaped corrections export: the reviewer-approved
    ``fields`` for a document, optionally paired with the OCR text they were read from.
    """

    document_id: str
    doc_type: str
    fields: dict
    corrected_at: datetime
    ocr_text: str | None = None


# --- admin overview ----------------------------------------------------------


class DayBucket(BaseModel):
    """One calendar day's count in a time series."""

    date: str  # "YYYY-MM-DD"
    count: int


class TimeSeries(BaseModel):
    """A zero-filled daily time series over a fixed window (oldest -> newest)."""

    window_days: int
    buckets: list[DayBucket]


class AccuracySummary(BaseModel):
    """Headline evaluation-accuracy numbers rolled up across all eval runs."""

    latest_overall_score: float | None
    latest_line_item_score: float | None
    eval_runs_total: int
    doc_types_evaluated: int


class DocTypeKpi(BaseModel):
    """Per-doc-type KPI slice for the overview dashboard breakdown."""

    doc_type: str
    documents: int
    pct_of_total: float
    avg_extraction_confidence: float | None
    decisions: dict[str, int]
    corrections_total: int
    corrected_documents: int
    latest_accuracy: float | None
    latest_accuracy_engine: str | None
    latest_line_item_score: float | None
    eval_runs: int


class OverviewStats(BaseModel):
    """Consolidated counts for the admin overview dashboard."""

    documents_total: int
    documents_by_status: dict[str, int]
    decisions: dict[str, int]  # approve / flag / needs_review counts
    corrections_total: int
    corrected_documents: int
    doc_types: int
    engines_enabled: int
    avg_extraction_confidence: float | None
    # --- KPI dashboard extension (additive) ---
    doc_types_used: int
    accuracy: AccuracySummary
    throughput: TimeSeries
    maintenance: TimeSeries
    by_doc_type: list[DocTypeKpi]


# --- review queue ------------------------------------------------------------


class ReviewQueueField(BaseModel):
    """One at-risk extracted field: below the confidence threshold, not yet edited."""

    path: str  # dotted path matching the PATCH /structure/field grammar
    value: str | float | int | bool | None
    confidence: float
    grounding: Grounding | None = None


class ReviewQueueDocument(BaseModel):
    """A document with one or more at-risk fields, plus its review context."""

    document_id: str
    filename: str
    doc_type: str
    status: DocumentStatus
    last_decision: Decision | None = None  # annotation only; never filters the queue
    at_risk_count: int
    lowest_confidence: float
    fields: list[ReviewQueueField]  # worst-first (confidence ascending)


class ReviewQueueResponse(BaseModel):
    """The review queue: documents with low-confidence fields needing attention."""

    threshold: float
    total_at_risk_fields: int
    documents: list[ReviewQueueDocument]


# --- Phase 1: multi-document cases -------------------------------------------


class CaseTypeMember(BaseModel):
    """One expected member doc-type of a case type, with its cardinality.

    ``min_count`` / ``max_count`` are carried-but-not-enforced in Phase 1 (the
    reconciler that consumes them lands in Phase 2).
    """

    doc_type: str
    min_count: int = 1
    max_count: int | None = 1
    label: str = ""


class CaseTypeResponse(BaseModel):
    """A case type's full definition as returned by the CRUD endpoints."""

    name: str
    label: str
    icon: str
    members: list[CaseTypeMember]
    canonical_fields: dict
    builtin: bool
    version: int
    created_at: datetime
    updated_at: datetime


class CaseTypeCreate(BaseModel):
    """Payload to create a custom case type (always non-built-in, version 1)."""

    name: str
    label: str
    icon: str = ""
    members: list[CaseTypeMember] = []
    canonical_fields: dict = {}


class CaseCreate(BaseModel):
    """Payload to create a case: an open pile, or one bound to a case type."""

    case_type: str | None = None
    label: str = ""


class CaseSummary(BaseModel):
    """Compact shape for the case list view."""

    id: str
    case_type: str | None
    label: str
    created_at: datetime


class CaseMemberAssembly(BaseModel):
    """One member document of a case plus its persisted structured result (if any)."""

    document_id: str
    filename: str
    doc_type: str | None
    status: DocumentStatus
    structured: StructuredResult | None = None


class CaseDetail(BaseModel):
    """A case with each member document's status + grouped structured result."""

    id: str
    case_type: str | None
    label: str
    created_at: datetime
    members: list[CaseMemberAssembly]


# --- Phase 2: classifier + reconciler ----------------------------------------


class ClassifyCandidate(BaseModel):
    """One doc-type guess for a document, with its normalized confidence score."""

    doc_type: str
    score: float


class ClassifyResult(BaseModel):
    """A document's classification: the winning doc-type + the full candidate ranking."""

    document_id: str
    provider: str  # "heuristic" | "llm"
    doc_type: str | None  # None when nothing scored above zero
    confidence: float  # 0-1; the normalized top score (0.0 when all scores were zero)
    candidates: list[ClassifyCandidate]


class CandidateInfo(BaseModel):
    """One grounded value drawn from a member document for a canonical field."""

    document_id: str
    doc_type: str
    field_path: str  # dotted path this value was read from, e.g. "total" or "parties.0"
    value: str | float | int | bool | None
    confidence: float
    page: int | None = None  # from the candidate's grounding, if any


class CanonicalFieldResult(BaseModel):
    """One reconciled canonical field: its value, whether its sources agree, and why."""

    name: str
    value: str | float | int | bool | None
    agreement: bool
    kind: str  # "money" | "date" | "string" (the tolerance rule applied)
    candidates: list[CandidateInfo]
    conflict_detail: str | None = None  # set when agreement is False
    citations: list[Citation] = []  # one per contributing document (document_id set)


class CaseReconciliation(BaseModel):
    """Cross-document reconciliation of a case into its canonical fields."""

    case_id: str
    case_type: str | None
    status: str  # "reconciled" at this stage
    canonical_fields: list[CanonicalFieldResult]
    member_count: int
    structured_count: int
    warnings: list[str] = []


class CaseDecisionResult(BaseModel):
    """Case-level decision (parallel to :class:`DecisionResult`, but case-shaped)."""

    case_id: str
    case_type: str | None
    status: str  # "decided" (approve/flag) | "needs_review"
    decision: str  # approve | flag | needs_review
    confidence: float  # 0-1
    reasons: list[str]  # human-readable bullets (LLM judgment + any code-forced reason)
    checks: list[Check]  # authoritative, code-computed rule-by-rule trace
    citations: list[Citation] = []  # built from the reconciled canonical fields
    llm_decision: str | None = None  # what the LLM proposed before reconciliation


# --- accuracy-evaluation harness ---------------------------------------------


class EvalFieldScore(BaseModel):
    """One scored scalar/dotted field: expected vs. actual under its comparison kind."""

    path: str
    expected: str | float | int | bool | None
    actual: str | float | int | bool | None
    kind: str  # "money" | "date" | "string"
    exact_match: bool
    normalized_match: bool


class EvalCollectionScore(BaseModel):
    """Row + cell agreement for one aligned collection field (line_items, parties, …)."""

    row_precision: float
    row_recall: float
    row_f1: float
    cell_accuracy: float
    line_item_score: float  # row_f1 * cell_accuracy
    matched: int
    n_expected: int
    n_actual: int
    detail: list[dict] = []  # per-matched-pair {expected, actual, cell_score}


class EvalRunRequest(BaseModel):
    """Run a golden case. Defaults to the offline mock engine + provider.

    ``document_id`` re-scores an EXISTING document's persisted structure stage instead of
    running the pipeline afresh (the engine/provider are then taken from that result).
    """

    golden_id: str
    engine: str = "mock"
    provider: str = "mock"
    document_id: str | None = None


class EvalRunResult(BaseModel):
    """Full detail of one scored evaluation run."""

    id: str
    golden_id: str
    doc_type: str
    engine: str
    provider: str
    document_id: str
    overall_score: float
    field_accuracy_exact: float
    field_accuracy_normalized: float
    field_scores: list[EvalFieldScore]
    collection_scores: dict[str, EvalCollectionScore]
    created_at: datetime


class EvalRunSummary(BaseModel):
    """Compact shape for the runs list view."""

    id: str
    golden_id: str
    doc_type: str
    engine: str
    provider: str
    document_id: str
    overall_score: float
    field_accuracy_exact: float
    field_accuracy_normalized: float
    created_at: datetime


class EvalGoldenSummary(BaseModel):
    """Compact shape for the golden-catalogue list view."""

    id: str
    sample_file: str
    doc_type: str
    field_count: int
    collection_count: int


class EvalGoldenDetail(EvalGoldenSummary):
    """A golden's full expected values."""

    expected_fields: dict
    expected_collections: dict


# --- black-box extraction (Track 1) ------------------------------------------


class ExtractionResult(BaseModel):
    """Whole-pipeline result for one document run synchronously via /extract.

    Bundles the stage outputs that make up a single black-box extraction call:
    the (optional) pre-flight report, the (optional, only when auto-classified)
    classification, the structured fields, and the final decision.
    """

    document_id: str
    doc_type: str  # the resolved type structuring/decision ran against
    classify: ClassifyResult | None = None  # set only when doc_type was auto-classified
    prescan: QualityReport | None = None  # set only when run_prescan was requested
    structured: StructuredResult
    decision: DecisionResult
    warnings: list[str] = []


class BatchExtractionItem(BaseModel):
    """One file's outcome within a /extract/batch call.

    Exactly one of ``result`` (success) / ``error`` (failure) is populated. The
    ``document_id`` is captured whenever the upload succeeded, so a mid-pipeline
    failure still yields an inspectable document.
    """

    filename: str
    document_id: str | None = None
    result: ExtractionResult | None = None
    error: str | None = None
    error_status: int | None = None  # the HTTP status a staged route would have returned


class BatchExtractionResult(BaseModel):
    """Aggregate result of a /extract/batch call (always HTTP 200)."""

    items: list[BatchExtractionItem]
    succeeded: int
    failed: int


# --- Phase 3: authoring agent (Waves 2+3) ------------------------------------


class AgentChatMessage(BaseModel):
    """One turn of the authoring-agent conversation, replayed into the LLM."""

    role: str  # "user" | "assistant"
    content: str


class AgentRequest(BaseModel):
    """Request body for ``POST /templates/{id}/agent``: a message + prior turns."""

    message: str
    history: list[AgentChatMessage] = []
    provider: str = ""  # "" -> settings default; "llm" | "mock"


class AgentEvent(BaseModel):
    """One server-sent event emitted by the authoring agent's stream.

    ``type`` selects which of the all-optional payload fields carry meaning:
    ``token`` (text), ``tool_call`` (tool_name/tool_args), ``tool_result``
    (tool_name/ok/detail), ``html``/``css`` (the new document + revision_id),
    ``error`` (message), ``done`` (terminal, no payload).
    """

    type: str  # "token"|"tool_call"|"tool_result"|"html"|"css"|"error"|"done"
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    ok: bool | None = None
    detail: str | None = None
    html: str | None = None
    css: str | None = None
    revision_id: str | None = None
    message: str | None = None


# --- Phase 4 (Vision QA): render + judge a rich-HTML template -----------------


class QaFinding(BaseModel):
    """One visual-fidelity issue the vision judge reported on a rendered template."""

    severity: str  # "low" | "medium" | "high"
    category: str  # "layout" | "color" | "table" | "spacing" | "text" | "missing"
    description: str
    suggested_fix: str | None = None
    page: int | None = None


class QaRequest(BaseModel):
    """Request body for ``POST /templates/{id}/qa``: optionally fill from a document."""

    document_id: str | None = None  # fill the preview from this document's structure
    provider: str = ""  # "" -> settings default; "llm" | "mock"
    instructions: str | None = None  # extra guidance passed to the judge


class QaReport(BaseModel):
    """Response of ``POST /templates/{id}/qa``: the fidelity critique + page images."""

    template_id: str
    document_id: str | None
    mode: str  # "source_pdf" (compared to the source) | "self_review" (no reference)
    ok: bool
    summary: str
    findings: list[QaFinding]
    rendered_image_urls: list[str]
    reference_image_urls: list[str]
    provider_used: str  # "llm" | "mock" (reflects the actual, post-fallback provider)
    model: str
    warnings: list[str]


# --- Phase 6: outbound digital signing ---------------------------------------

# An APPROVED document can be sealed with a real X.509 signature whose embedded
# CMS validates against a trust chain (a stamped image is legally worthless; a
# real signature validates). Off the inbound pipeline — a manual post-decision
# action. "pyhanko" = real PAdES (optional dep); "mock" = offline default.


class SignerInfo(BaseModel):
    """The certificate identity that produced a signature."""

    common_name: str
    issuer: str
    serial: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class SignatureValidation(BaseModel):
    """Outcome of validating an embedded signature against a trust chain."""

    valid: bool  # intact AND trusted
    intact: bool  # covered bytes untouched
    trusted: bool  # signer chains to a trust root
    level: str  # "PAdES-B-B" | "PAdES-B-T" | "mock"
    signer: SignerInfo | None = None
    signed_at: datetime | None = None
    trust_anchor: str | None = None  # CN of the root chained to
    summary: str = ""
    warnings: list[str] = []


class SignResult(BaseModel):
    """Document-level signing result, persisted under stage_results["sign"]."""

    document_id: str
    status: DocumentStatus  # `signed`
    provider: str  # "pyhanko" | "mock"
    engine_version: str
    level: str
    field_name: str
    signed_pdf_url: str  # /files/<id>/signed/signed.pdf
    validation: SignatureValidation
    latency_ms: int = 0
    warnings: list[str] = []


class GeneratedSignResult(BaseModel):
    """Result of sealing a GENERATED template output PDF with a real PAdES signature.

    The outbound counterpart to :class:`SignResult`: instead of an inbound document's
    original, this signs a document produced by the generation stage (the Solicitud /
    Anexo you transmit). Not persisted on a pipeline run — the signed file is written
    beside the generated output as ``<output_id>-signed.pdf``.
    """

    template_id: str
    output_id: str  # the generated PDF output that was signed
    signed_output_id: str  # the signed variant (``<output_id>-signed``)
    provider: str  # "pyhanko" | "mock"
    engine_version: str
    level: str
    field_name: str
    signed_output_url: str  # /files/templates/<id>/outputs/<output_id>-signed.pdf
    validation: SignatureValidation
    latency_ms: int = 0
    warnings: list[str] = []
