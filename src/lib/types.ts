// TypeScript mirrors of the FastAPI backend schemas (backend/app/schemas.py).
// Kept hand-maintained and minimal to match the JSON the API returns.

export type DocType = "invoice" | "contract";
export type OcrEngine = "qwen-vl" | "docling";
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
}

export interface PageInfo {
  page: number;
  image_url: string; // relative /files/... — wrap with fileUrl()
  thumbnail_url: string;
}

export interface DocumentDetail extends DocumentSummary {
  pages: PageInfo[];
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
}

// --- structuring -------------------------------------------------------------

export interface Grounding {
  page: number | null;
  char_start: number | null;
  char_end: number | null;
  snippet: string | null;
  alignment: Alignment | null;
}

export interface FieldValue {
  value: string | number | boolean | null;
  confidence: number;
  grounding: Grounding | null;
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

export interface TemplateDetail extends TemplateSummary {
  source_file_id: string | null;
  source_url: string | null;
  html_body: string | null;
  css: string | null;
  form_fields: TemplateFormField[];
  form_field_map: Record<string, FormFieldMapEntry>;
  placeholder_map: Record<string, unknown>;
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
