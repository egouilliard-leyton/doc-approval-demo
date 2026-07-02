// TypeScript mirrors of the FastAPI backend schemas (backend/app/schemas.py).
// Kept hand-maintained and minimal to match the JSON the API returns.

export type DocType = string;
// An engine key: "docling" or any connected VLM engine key (data-driven).
export type OcrEngine = string;

/** A selectable OCR engine for the upload picker. */
export interface EngineInfo {
  key: string;
  label: string;
  kind: "layout" | "vlm";
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
