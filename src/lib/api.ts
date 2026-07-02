// Fetch client for the FastAPI backend.
// CORS on the backend already allows the Vite dev origin, so we call it directly.
import type {
  CaseCreate,
  CaseDecisionResult,
  CaseDetail,
  CaseReconciliation,
  CaseSummary,
  CaseTypeCreate,
  CaseTypeResponse,
  ClassifyResult,
  DocumentDetail,
  DocumentSummary,
  DecisionResult,
  DocType,
  EngineInfo,
  FieldCorrection,
  OcrEngine,
  OCRResult,
  OpenRouterModel,
  OverviewStats,
  QualityReport,
  Sheet,
  StructuredResult,
  VlmEngineRow,
} from "@/lib/types";
import type {
  AnnotatePollResponse,
  AnnotateStartResponse,
  AssistRequest,
  AssistResponse,
  DocTypeCreate,
  DocTypePreviewRequest,
  DocTypePreviewResponse,
  DocTypeResponse,
  DocTypeUpdate,
  IngestResponse,
} from "@/lib/doc-type-schema";

const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";

export interface HealthResponse {
  status: string;
}

/**
 * The backend returns server-relative asset URLs (e.g. `/files/<id>/pages/...`).
 * The frontend runs on a different origin with no proxy, so every rendered
 * asset must be absolutized through this helper.
 */
export function fileUrl(path?: string | null): string | undefined {
  if (!path) return undefined;
  if (/^https?:\/\//.test(path)) return path;
  return `${API_BASE_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}

/** Raised on a non-2xx response; carries the HTTP status for UI handling. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface RequestOpts {
  method?: string;
  query?: Record<string, string | number | boolean | undefined>;
  body?: BodyInit;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const { method = "GET", query, body, signal, headers } = opts;
  const qs = query
    ? "?" +
      Object.entries(query)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}${qs}`, {
      method,
      body,
      signal,
      headers,
    });
  } catch {
    throw new ApiError(0, `Cannot reach the backend at ${API_BASE_URL}. Is it running?`);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = (await res.json()) as { detail?: string };
      if (data?.detail) detail = data.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  // 204 No Content (e.g. DELETE) and any non-JSON/empty body have nothing to
  // parse. Guarding on content-type (not just Content-Length, which proxies may
  // omit on chunked responses) keeps res.json() from throwing on an empty body.
  if (
    res.status === 204 ||
    res.headers.get("content-length") === "0" ||
    !res.headers.get("content-type")?.includes("application/json")
  ) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

// --- documents ---------------------------------------------------------------

export async function uploadDocument(
  file: File,
  docType?: DocType,
  caseId?: string,
): Promise<DocumentDetail> {
  const form = new FormData();
  form.append("file", file);
  if (docType) form.append("doc_type", docType);
  if (caseId) form.append("case_id", caseId);
  return request<DocumentDetail>("/documents", { method: "POST", body: form });
}

/** Classify a document into its most-likely doc type (heuristic or LLM). */
export async function classifyDocument(
  id: string,
  opts: { ocrEngine?: string; provider?: string } = {},
): Promise<ClassifyResult> {
  return request<ClassifyResult>(`/documents/${id}/classify`, {
    method: "POST",
    query: { ocr_engine: opts.ocrEngine, provider: opts.provider },
  });
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${id}`);
}

/** Parsed spreadsheet grid (one entry per sheet), written at ingest for CSV/XLSX. */
export async function getSheets(id: string): Promise<Sheet[]> {
  return request<Sheet[]>(`/files/${id}/sheets.json`);
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>("/documents");
}

export async function deleteDocument(id: string): Promise<void> {
  await request<void>(`/documents/${id}`, { method: "DELETE" });
}

export async function deleteAllDocuments(): Promise<void> {
  await request<void>("/documents", { method: "DELETE" });
}

// --- persisted stage results (GET; 404 when a stage hasn't run) ---------------

export async function getPrescan(id: string): Promise<QualityReport> {
  return request<QualityReport>(`/documents/${id}/prescan`);
}

export async function getOcr(
  id: string,
  engine: OcrEngine,
): Promise<OCRResult> {
  return request<OCRResult>(`/documents/${id}/ocr`, { query: { engine } });
}

export async function getStructure(id: string): Promise<StructuredResult> {
  return request<StructuredResult>(`/documents/${id}/structure`);
}

export async function getDecision(id: string): Promise<DecisionResult> {
  return request<DecisionResult>(`/documents/${id}/decide`);
}

// --- pipeline stages (live engines) ------------------------------------------

export async function runPrescan(
  id: string,
  opts: { deskew?: boolean; clean?: boolean } = {},
): Promise<QualityReport> {
  return request<QualityReport>(`/documents/${id}/prescan`, {
    method: "POST",
    query: { deskew: opts.deskew ?? true, clean: opts.clean ?? true },
  });
}

export async function runOcr(
  id: string,
  engine: OcrEngine,
): Promise<OCRResult> {
  return request<OCRResult>(`/documents/${id}/ocr`, {
    method: "POST",
    query: { engine },
  });
}

export async function runStructure(
  id: string,
  p: { docType: DocType; ocrEngine: OcrEngine },
): Promise<StructuredResult> {
  return request<StructuredResult>(`/documents/${id}/structure`, {
    method: "POST",
    query: { doc_type: p.docType, ocr_engine: p.ocrEngine },
  });
}

export async function runDecide(id: string): Promise<DecisionResult> {
  return request<DecisionResult>(`/documents/${id}/decide`, { method: "POST" });
}

/** Apply a reviewer edit to one structured field; returns the updated result. */
export async function editStructureField(
  id: string,
  body: { path: string; value: string | number | boolean | null },
): Promise<StructuredResult> {
  return request<StructuredResult>(`/documents/${id}/structure/field`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

// --- configurable doc types (CRUD + preview) ---------------------------------

const JSON_HEADERS = { "Content-Type": "application/json" };

export async function listDocTypes(): Promise<DocTypeResponse[]> {
  return request<DocTypeResponse[]>("/doc-types");
}

export async function getDocType(name: string): Promise<DocTypeResponse> {
  return request<DocTypeResponse>(`/doc-types/${name}`);
}

export async function createDocType(
  body: DocTypeCreate,
): Promise<DocTypeResponse> {
  return request<DocTypeResponse>("/doc-types", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export async function updateDocType(
  name: string,
  body: DocTypeUpdate,
): Promise<DocTypeResponse> {
  return request<DocTypeResponse>(`/doc-types/${name}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export async function deleteDocType(name: string): Promise<void> {
  await request<void>(`/doc-types/${name}`, { method: "DELETE" });
}

export async function previewDocType(
  name: string,
  body: DocTypePreviewRequest,
): Promise<DocTypePreviewResponse> {
  return request<DocTypePreviewResponse>(`/doc-types/${name}/preview`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

// --- OCR engines -------------------------------------------------------------

/** Engines selectable at upload time (docling + enabled VLMs). */
export async function listEngines(): Promise<EngineInfo[]> {
  return request<EngineInfo[]>("/engines");
}

/** All connected VLM engines (enabled + disabled), for the settings dialog. */
export async function listEngineCatalog(): Promise<VlmEngineRow[]> {
  return request<VlmEngineRow[]>("/engines/catalog");
}

/** Image-capable models offered by OpenRouter, for the add-model dropdown. */
export async function listOpenRouterModels(): Promise<OpenRouterModel[]> {
  return request<OpenRouterModel[]>("/engines/openrouter-models");
}

export async function createEngine(body: {
  label: string;
  model: string;
  key?: string;
  enabled?: boolean;
}): Promise<VlmEngineRow> {
  return request<VlmEngineRow>("/engines", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export async function updateEngine(
  key: string,
  body: { label?: string; enabled?: boolean },
): Promise<VlmEngineRow> {
  return request<VlmEngineRow>(`/engines/${key}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export async function deleteEngine(key: string): Promise<void> {
  await request<void>(`/engines/${key}`, { method: "DELETE" });
}

// --- admin ------------------------------------------------------------------

export async function getOverview(): Promise<OverviewStats> {
  return request<OverviewStats>("/overview");
}

export async function listCorrections(
  documentId?: string,
): Promise<FieldCorrection[]> {
  return request<FieldCorrection[]>("/corrections", {
    query: { document_id: documentId },
  });
}

// --- AI doc-type wizard ------------------------------------------------------

export async function assistTurn(req: AssistRequest): Promise<AssistResponse> {
  return request<AssistResponse>("/doc-types/assist", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(req),
  });
}

/** Extract plain text from an uploaded process/example doc (text passthrough or OCR). */
export async function ingestDocForAssist(
  file: File,
  kind: "process" | "example",
): Promise<IngestResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  // No explicit content-type: the browser sets the multipart boundary.
  return request<IngestResponse>("/doc-types/assist/ingest", {
    method: "POST",
    body: form,
  });
}

/** Launch a Plannotator annotation session over the spec markdown. */
export async function startAnnotation(
  specMarkdown: string,
): Promise<AnnotateStartResponse> {
  return request<AnnotateStartResponse>("/doc-types/assist/annotate", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ spec_markdown: specMarkdown }),
  });
}

/** Poll an annotation session's status (404 ApiError when the id is unknown). */
export async function pollAnnotation(
  sessionId: string,
): Promise<AnnotatePollResponse> {
  return request<AnnotatePollResponse>(
    `/doc-types/assist/annotate/${sessionId}`,
  );
}

/** Cancel an annotation session (idempotent 204). */
export async function cancelAnnotation(sessionId: string): Promise<void> {
  await request<void>(`/doc-types/assist/annotate/${sessionId}`, {
    method: "DELETE",
  });
}

// --- multi-document cases ----------------------------------------------------

export async function createCase(body: CaseCreate): Promise<CaseDetail> {
  return request<CaseDetail>("/cases", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export async function listCases(): Promise<CaseSummary[]> {
  return request<CaseSummary[]>("/cases");
}

export async function getCase(id: string): Promise<CaseDetail> {
  return request<CaseDetail>(`/cases/${id}`);
}

export async function deleteCase(id: string): Promise<void> {
  await request<void>(`/cases/${id}`, { method: "DELETE" });
}

/** Associate a document with a case; returns the updated case. */
export async function addDocumentToCase(
  caseId: string,
  docId: string,
): Promise<CaseDetail> {
  return request<CaseDetail>(`/cases/${caseId}/documents/${docId}`, {
    method: "POST",
  });
}

export async function removeDocumentFromCase(
  caseId: string,
  docId: string,
): Promise<void> {
  await request<void>(`/cases/${caseId}/documents/${docId}`, {
    method: "DELETE",
  });
}

// --- case types (CRUD) -------------------------------------------------------

export async function listCaseTypes(): Promise<CaseTypeResponse[]> {
  return request<CaseTypeResponse[]>("/case-types");
}

export async function getCaseType(name: string): Promise<CaseTypeResponse> {
  return request<CaseTypeResponse>(`/case-types/${name}`);
}

export async function createCaseType(
  body: CaseTypeCreate,
): Promise<CaseTypeResponse> {
  return request<CaseTypeResponse>("/case-types", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export async function deleteCaseType(name: string): Promise<void> {
  await request<void>(`/case-types/${name}`, { method: "DELETE" });
}

// --- case pipeline (reconcile + decide) --------------------------------------

export async function reconcileCase(id: string): Promise<CaseReconciliation> {
  return request<CaseReconciliation>(`/cases/${id}/reconcile`, {
    method: "POST",
  });
}

export async function getCaseReconciliation(
  id: string,
): Promise<CaseReconciliation> {
  return request<CaseReconciliation>(`/cases/${id}/reconcile`);
}

export async function decideCase(
  id: string,
  provider?: string,
): Promise<CaseDecisionResult> {
  return request<CaseDecisionResult>(`/cases/${id}/decide`, {
    method: "POST",
    query: { provider },
  });
}

export async function getCaseDecision(id: string): Promise<CaseDecisionResult> {
  return request<CaseDecisionResult>(`/cases/${id}/decide`);
}

export { API_BASE_URL };
