// TypeScript mirrors of the FastAPI backend schemas (backend/app/schemas.py).
// Kept hand-maintained and minimal to match the JSON the API returns.

export type DocType = string;
// An engine key: "docling" or any connected VLM engine key (data-driven).
export type OcrEngine = string;

/** A selectable OCR engine for the upload picker. */
export interface EngineInfo {
  key: string;
  label: string;
  kind: "layout" | "vlm" | "external";
}

/** A connected VLM engine row (settings/catalog view). */
export interface VlmEngineRow {
  key: string;
  label: string;
  model: string;
  enabled: boolean;
}

/** An image-capable model offered by OpenRouter (add-model dropdown). */
export interface OpenRouterModel {
  id: string;
  name: string;
}

/** A logged field correction (reviewer edit), for the admin corrections log. */
export interface FieldCorrection {
  document_id: string;
  doc_type: string;
  field_path: string;
  original_value: string | number | boolean | null;
  new_value: string | number | boolean | null;
  created_at: string;
  updated_at: string;
}

/** One day's document count in a time series ("YYYY-MM-DD"). */
export interface DayBucket {
  date: string;
  count: number;
}

/** A zero-filled, ascending daily time series over a fixed window. */
export interface TimeSeries {
  window_days: number;
  buckets: DayBucket[];
}

/** Latest accuracy-eval headline numbers across the system. */
export interface AccuracySummary {
  latest_overall_score: number | null;
  latest_line_item_score: number | null;
  eval_runs_total: number;
  doc_types_evaluated: number;
}

/** Per-doc-type KPI rollup for the overview table. */
export interface DocTypeKpi {
  doc_type: string;
  documents: number;
  pct_of_total: number;
  avg_extraction_confidence: number | null;
  decisions: Record<string, number>;
  corrections_total: number;
  corrected_documents: number;
  latest_accuracy: number | null;
  latest_accuracy_engine: string | null;
  latest_line_item_score: number | null;
  eval_runs: number;
}

/** Consolidated system counts for the admin overview. */
export interface OverviewStats {
  documents_total: number;
  documents_by_status: Record<string, number>;
  decisions: Record<string, number>;
  corrections_total: number;
  corrected_documents: number;
  doc_types: number;
  engines_enabled: number;
  avg_extraction_confidence: number | null;
  doc_types_used: number;
  accuracy: AccuracySummary;
  throughput: TimeSeries;
  maintenance: TimeSeries;
  by_doc_type: DocTypeKpi[];
}
export type DocumentStatus =
  | "uploaded"
  | "prescanned"
  | "ocr_done"
  | "structured"
  | "decided"
  | "needs_review"
  | "signed";

export type Verdict = "pass" | "warn";
export type Alignment = "exact" | "partial" | "ungrounded";
export type Decision = "approve" | "flag" | "needs_review";
export type Severity = "hard" | "review" | "advisory";

/** [x0, y0, x1, y1] in page pixel space, top-left origin. */
export type BBox = [number, number, number, number];

// --- documents ---------------------------------------------------------------

export interface DocumentSummary {
  id: string;
  filename: string;
  doc_type: DocType | null;
  mime: string;
  page_count: number;
  status: DocumentStatus;
  created_at: string;
  case_id?: string | null; // the case this document belongs to, if any
}

export interface PageInfo {
  page: number;
  image_url: string; // relative /files/... — wrap with fileUrl()
  thumbnail_url: string;
}

export interface DocumentDetail extends DocumentSummary {
  pages: PageInfo[];
}

/** One parsed worksheet, written to /files/<id>/sheets.json at ingest. */
export interface Sheet {
  name: string;
  rows: string[][];
  truncated_rows?: boolean;
  truncated_cols?: boolean;
}

// --- prescan / quality -------------------------------------------------------

export interface MetricResult {
  value: number;
  verdict: Verdict;
  threshold: number | null;
}

export interface PageQuality {
  page: number;
  width_px: number;
  height_px: number;
  resolution: MetricResult;
  sharpness: MetricResult;
  contrast: MetricResult;
  brightness: MetricResult;
  skew_angle_deg: number;
  verdict: Verdict;
  reasons: string[];
  deskewed: boolean;
  image_url: string;
  deskewed_url: string | null;
  gray_url: string | null;
  thresh_url: string | null;
}

export interface QualityReport {
  document_id: string;
  status: DocumentStatus;
  verdict: Verdict;
  reasons: string[];
  preprocess_applied: boolean;
  pages: PageQuality[];
}

// --- OCR ---------------------------------------------------------------------

export interface OCRBlock {
  page: number;
  text: string;
  bbox: BBox;
  confidence: number | null;
  label: string;
}

export interface OCRTable {
  page: number;
  bbox: BBox | null;
  n_rows: number;
  n_cols: number;
  markdown: string;
  confidence: number | null;
}

export interface OCRPage {
  page: number;
  text: string;
  blocks: OCRBlock[];
  tables: OCRTable[];
  avg_confidence: number | null;
  char_count: number;
  markdown_url: string | null;
}

export interface OCRResult {
  document_id: string;
  status: DocumentStatus;
  engine_name: string;
  engine_version: string;
  device: string;
  full_text: string;
  pages: OCRPage[];
  avg_confidence: number | null;
  table_count: number;
  latency_ms: number;
  warnings: string[];
  // Ordered list of engines actually tried; length > 1 means a fallback fired,
  // and the last entry is the engine that produced this result. Old results may
  // omit it — treat undefined as [].
  attempted_engines?: string[];
}

// --- structuring -------------------------------------------------------------

export interface Grounding {
  page: number | null;
  char_start: number | null;
  char_end: number | null;
  snippet: string | null;
  alignment: Alignment | null;
  // Spatial grounding (signature post-pass): a pixel bbox on the page + the crop URL.
  bbox?: BBox | null;
  image_url?: string | null; // relative /files/... — wrap with fileUrl()
  // Case reconciliation: which member document this span came from, so a reconciled
  // canonical value can cite its source document. None for single-doc use.
  document_id?: string | null;
}

export interface FieldValue {
  value: string | number | boolean | null;
  confidence: number;
  grounding: Grounding | null;
  edited?: boolean;
  original_value?: string | number | boolean | null;
}

export interface StructuredResult {
  document_id: string;
  status: DocumentStatus;
  doc_type: DocType;
  provider: string;
  model: string;
  ocr_engine: string;
  fields: Record<string, unknown>; // InvoiceFields | ContractFields, dumped to JSON
  extraction_confidence: number;
  grounding_map: Record<string, Grounding>;
  warnings: string[];
  latency_ms: number;
  fallback_used: boolean;
  raw_artifact_url: string | null;
}

// --- templates ---------------------------------------------------------------

export type TemplateMode = "form_fill" | "rich_html";
export type TemplateStatus = "draft" | "ready";

export interface TemplateSummary {
  id: string;
  name: string;
  doc_type: DocType;
  mode: TemplateMode;
  status: TemplateStatus;
  output_formats: string[];
  created_at: string;
  updated_at: string;
}

/** One fillable field discovered in a source PDF's AcroForm. */
export interface TemplateFormField {
  name: string;
  kind: "text" | "checkbox" | "radio" | "choice" | "signature";
  page: number;
  rect: number[] | null;
  options: string[] | null;
  nearby_label: string | null;
}

/**
 * A persisted mapping from a PDF form field to an extracted document field.
 * `is_signature` short-circuits `field_path` (the field is stamped at generate).
 */
export interface FormFieldMapEntry {
  field_path: string | null;
  is_signature: boolean;
  source?: string;
  confidence?: number | null;
}

/** Advisory placeholder health: how many bound tokens still point at live fields. */
export interface TemplateLint {
  orphaned_paths: string[];
  bound_count: number;
  total_count: number;
}

export interface TemplateDetail extends TemplateSummary {
  source_file_id: string | null;
  source_url: string | null;
  html_body: string | null;
  css: string | null;
  form_fields: TemplateFormField[];
  form_field_map: Record<string, FormFieldMapEntry>;
  placeholder_map: Record<string, unknown>;
  lint: TemplateLint;
}

// --- template form-fill mapping / generation ---------------------------------

/** One selectable extracted field a PDF form field can map to. */
export interface FieldCatalogueEntry {
  path: string;
  label: string;
  kind: string;
}

/** An AI-proposed mapping for a single PDF form field. */
export interface MappingSuggestion {
  field_path: string | null;
  confidence: number | null;
  source: string;
  is_signature: boolean;
  rationale: string | null;
}

export interface MappingSuggestResponse {
  suggestions: Record<string, MappingSuggestion>;
  provider_used: string;
}

/** One generated artifact (a template can now emit several formats at once). */
export interface GenerateOutputFile {
  format: string;
  output_id: string;
  output_url: string;
}

export interface GenerateResult {
  output_url: string;
  output_id: string;
  outputs: GenerateOutputFile[];
  filled_fields: string[];
  skipped_fields: string[];
  signature_stamped: boolean;
  warnings: string[];
}

export interface TemplateRevisionInfo {
  id: string;
  html: string | null;
  css: string | null;
  note: string | null;
  created_at: string;
}

// --- authoring agent (SSE chat) ----------------------------------------------

/** One turn in the authoring-agent chat transcript. */
export interface AgentChatMessage {
  role: "user" | "assistant";
  content: string;
}

/**
 * A single SSE frame streamed by `POST /templates/{id}/agent`. `type` is the
 * discriminant; the other fields are populated per event (see the backend
 * contract). Sequence: `token`* → `tool_call` → `tool_result` → optional
 * `html`/`css` → … → `done`. `error` carries `message`.
 */
export interface AgentEvent {
  type:
    | "token"
    | "tool_call"
    | "tool_result"
    | "html"
    | "css"
    | "error"
    | "done";
  text?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  ok?: boolean;
  detail?: string;
  html?: string;
  css?: string;
  revision_id?: string;
  message?: string;
}

export interface TemplateCreate {
  name: string;
  doc_type: DocType;
  mode?: TemplateMode;
}

export interface TemplateUpdate {
  name?: string;
  html_body?: string;
  css?: string;
  form_field_map?: Record<string, unknown>;
  placeholder_map?: Record<string, unknown>;
  output_formats?: string[];
  status?: TemplateStatus;
  revision_note?: string;
}

// --- vision QA / fidelity ----------------------------------------------------

/** One fidelity issue the vision model flagged between reference and render. */
export interface QaFinding {
  severity: "low" | "medium" | "high";
  category: "layout" | "color" | "table" | "spacing" | "text" | "missing";
  description: string;
  suggested_fix: string | null;
  page: number | null;
}

export interface QaRequest {
  document_id?: string | null;
  provider?: string;
  instructions?: string | null;
}

export interface QaReport {
  template_id: string;
  document_id: string | null;
  mode: "source_pdf" | "self_review";
  ok: boolean;
  summary: string;
  findings: QaFinding[];
  rendered_image_urls: string[];
  reference_image_urls: string[];
  provider_used: string;
  model: string;
  warnings: string[];
}

// --- decision ----------------------------------------------------------------

export interface Check {
  name: string;
  passed: boolean;
  detail: string;
  severity: Severity;
}

export interface Citation {
  field: string;
  source: string;
  // Case reconciliation: which member document this citation points at, so a
  // reconciled canonical value can cite its source document. None for single-doc use.
  document_id?: string | null;
}

export interface DecisionResult {
  document_id: string;
  status: DocumentStatus;
  doc_type: DocType;
  provider: string;
  model: string;
  decision: Decision;
  confidence: number;
  reasons: string[];
  checks: Check[];
  citations: Citation[];
  llm_decision: Decision | null;
  warnings: string[];
  latency_ms: number;
}

// --- multi-document cases ----------------------------------------------------

/** One expected member doc-type of a case type, with its cardinality. */
export interface CaseTypeMember {
  doc_type: DocType;
  min_count: number;
  max_count: number | null;
  label: string;
}

/** A case type's full definition as returned by the CRUD endpoints. */
export interface CaseTypeResponse {
  name: string;
  label: string;
  icon: string;
  members: CaseTypeMember[];
  canonical_fields: Record<string, unknown>;
  builtin: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Payload to create a custom case type (always non-built-in, version 1). */
export interface CaseTypeCreate {
  name: string;
  label: string;
  icon?: string;
  members?: CaseTypeMember[];
  canonical_fields?: Record<string, unknown>;
}

/** Payload to create a case: an open pile, or one bound to a case type. */
export interface CaseCreate {
  case_type?: string | null;
  label?: string;
}

/** Compact shape for the case list view. */
export interface CaseSummary {
  id: string;
  case_type: string | null;
  label: string;
  created_at: string;
}

/** One member document of a case plus its persisted structured result (if any). */
export interface CaseMemberAssembly {
  document_id: string;
  filename: string;
  doc_type: DocType | null;
  status: DocumentStatus;
  structured: StructuredResult | null;
}

/** A case with each member document's status + grouped structured result. */
export interface CaseDetail {
  id: string;
  case_type: string | null;
  label: string;
  created_at: string;
  members: CaseMemberAssembly[];
}

// --- classifier --------------------------------------------------------------

/** One doc-type guess for a document, with its normalized confidence score. */
export interface ClassifyCandidate {
  doc_type: DocType;
  score: number;
}

/** A document's classification: the winning doc-type + the full candidate ranking. */
export interface ClassifyResult {
  document_id: string;
  provider: string; // "heuristic" | "llm"
  doc_type: DocType | null; // null when nothing scored above zero
  confidence: number; // 0-1; the normalized top score
  candidates: ClassifyCandidate[];
}

// --- reconciliation ----------------------------------------------------------

/** One grounded value drawn from a member document for a canonical field. */
export interface CandidateInfo {
  document_id: string;
  doc_type: DocType;
  field_path: string;
  value: string | number | boolean | null;
  confidence: number;
  page: number | null;
}

/** One reconciled canonical field: its value, whether its sources agree, and why. */
export interface CanonicalFieldResult {
  name: string;
  value: string | number | boolean | null;
  agreement: boolean;
  kind: string; // "money" | "date" | "string" (the tolerance rule applied)
  candidates: CandidateInfo[];
  conflict_detail: string | null; // set when agreement is false
  citations: Citation[]; // one per contributing document (document_id set)
}

/** Cross-document reconciliation of a case into its canonical fields. */
export interface CaseReconciliation {
  case_id: string;
  case_type: string | null;
  status: string; // "reconciled" at this stage
  canonical_fields: CanonicalFieldResult[];
  member_count: number;
  structured_count: number;
  warnings: string[];
}

/** Case-level decision (parallel to DecisionResult, but case-shaped). */
export interface CaseDecisionResult {
  case_id: string;
  case_type: string | null;
  status: string; // "decided" (approve/flag) | "needs_review"
  decision: Decision;
  confidence: number;
  reasons: string[];
  checks: Check[];
  citations: Citation[];
  llm_decision: Decision | null;
}

// --- review queue (per-field risk) -------------------------------------------

/** One at-risk field surfaced in the review queue, with its confidence + grounding. */
export interface ReviewQueueField {
  path: string;
  value: string | number | boolean | null;
  confidence: number;
  grounding: Grounding | null;
}

/** A document with at-risk fields, sorted worst-first by the backend. */
export interface ReviewQueueDocument {
  document_id: string;
  filename: string;
  doc_type: string;
  status: DocumentStatus;
  last_decision: Decision | null;
  at_risk_count: number;
  lowest_confidence: number;
  fields: ReviewQueueField[];
}

/** The full review queue: documents worst-first, fields worst-confidence-first. */
export interface ReviewQueueResponse {
  threshold: number;
  total_at_risk_fields: number;
  documents: ReviewQueueDocument[];
}

// --- accuracy-evaluation harness ---------------------------------------------

/** One scored field: expected vs actual, with exact/normalized match verdicts. */
export interface EvalFieldScore {
  path: string;
  expected: string | number | boolean | null;
  actual: string | number | boolean | null;
  kind: string;
  exact_match: boolean;
  normalized_match: boolean;
}

/** Scoring for one collection (line-item table): row P/R/F1 + cell accuracy. */
export interface EvalCollectionScore {
  row_precision: number;
  row_recall: number;
  row_f1: number;
  cell_accuracy: number;
  line_item_score: number;
  matched: number;
  n_expected: number;
  n_actual: number;
  detail: Array<{ expected: unknown; actual: unknown; cell_score: number }>;
}

/** Full result of scoring one run against a golden. */
export interface EvalRunResult {
  id: string;
  golden_id: string;
  doc_type: string;
  engine: string;
  provider: string;
  document_id: string;
  overall_score: number;
  field_accuracy_exact: number;
  field_accuracy_normalized: number;
  field_scores: EvalFieldScore[];
  collection_scores: Record<string, EvalCollectionScore>;
  created_at: string;
}

/** Lightweight run row for the results list (newest-first). */
export interface EvalRunSummary {
  id: string;
  golden_id: string;
  doc_type: string;
  engine: string;
  provider: string;
  document_id: string;
  overall_score: number;
  field_accuracy_exact: number;
  field_accuracy_normalized: number;
  created_at: string;
}

/** A golden sample in the catalogue. */
export interface EvalGoldenSummary {
  id: string;
  sample_file: string;
  doc_type: string;
  field_count: number;
  collection_count: number;
}

/** A golden with its expected values expanded. */
export interface EvalGoldenDetail extends EvalGoldenSummary {
  expected_fields: Record<string, unknown>;
  expected_collections: Record<string, unknown>;
}

// --- outbound digital signing (PAdES) ----------------------------------------

export interface SignerInfo {
  common_name: string;
  issuer: string;
  serial: string;
  valid_from: string | null;
  valid_to: string | null;
}

export interface SignatureValidation {
  valid: boolean;
  intact: boolean;
  trusted: boolean;
  level: string;
  signer: SignerInfo | null;
  signed_at: string | null;
  trust_anchor: string | null;
  summary: string;
  warnings: string[];
}

export interface SignResult {
  document_id: string;
  status: DocumentStatus;
  provider: string;
  engine_version: string;
  level: string;
  field_name: string;
  signed_pdf_url: string;
  validation: SignatureValidation;
  latency_ms: number;
  warnings: string[];
}
