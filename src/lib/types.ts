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
}
export type DocumentStatus =
  | "uploaded"
  | "prescanned"
  | "ocr_done"
  | "structured"
  | "decided"
  | "needs_review";

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
