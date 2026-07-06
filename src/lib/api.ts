// Fetch client for the FastAPI backend.
// CORS on the backend already allows the Vite dev origin, so we call it directly.
import type {
  AgentChatMessage,
  AgentEvent,
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
  EvalGoldenDetail,
  EvalGoldenSummary,
  EvalRunResult,
  EvalRunSummary,
  FieldCatalogueEntry,
  FieldCorrection,
  GeneratedSignResult,
  GenerateResult,
  MappingSuggestResponse,
  OcrEngine,
  OCRResult,
  OpenRouterModel,
  OverviewStats,
  QaReport,
  QualityReport,
  ReviewQueueResponse,
  Sheet,
  SignatureValidation,
  SignResult,
  StructuredResult,
  TemplateCreate,
  TemplateDetail,
  TemplateRevisionInfo,
  TemplateSummary,
  TemplateUpdate,
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
import { readSSE } from "@/lib/sse";

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

/**
 * Save a served file to disk. The backend runs on a different origin than the
 * dev frontend, and a cross-origin `<a download>` is ignored by the browser while
 * `target="_blank"` new-tab opens can be popup-blocked — so both silently fail.
 * Fetching the bytes (the `/files` mount is CORS-enabled) and clicking a
 * same-origin blob URL downloads reliably without opening a tab.
 */
export async function downloadFile(
  path: string | null | undefined,
  filename: string,
): Promise<void> {
  const url = fileUrl(path);
  if (!url) throw new ApiError(0, "No file to download.");
  const res = await fetch(url);
  if (!res.ok) throw new ApiError(res.status, `Could not fetch file (${res.status}).`);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

interface RequestOpts {
  method?: string;
  query?: Record<string, string | number | boolean | undefined>;
  body?: BodyInit;
  headers?: Record<string, string>;
  signal?: AbortSignal;
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

// --- templates ---------------------------------------------------------------

const JSON_HEADERS = { "Content-Type": "application/json" };

export async function listTemplates(
  docType?: DocType,
): Promise<TemplateSummary[]> {
  return request<TemplateSummary[]>("/templates", {
    query: { doc_type: docType },
  });
}

export async function getTemplate(id: string): Promise<TemplateDetail> {
  return request<TemplateDetail>(`/templates/${id}`);
}

export async function createTemplate(
  body: TemplateCreate,
): Promise<TemplateDetail> {
  return request<TemplateDetail>("/templates", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export async function updateTemplate(
  id: string,
  body: TemplateUpdate,
): Promise<TemplateDetail> {
  return request<TemplateDetail>(`/templates/${id}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export async function deleteTemplate(id: string): Promise<void> {
  await request<void>(`/templates/${id}`, { method: "DELETE" });
}

// --- template form-fill: source, catalogue, mapping, generate ----------------

export async function uploadTemplateSource(
  id: string,
  file: File,
): Promise<TemplateDetail> {
  const form = new FormData();
  form.append("file", file);
  return request<TemplateDetail>(`/templates/${id}/source`, {
    method: "POST",
    body: form,
  });
}

export async function getTemplateCatalogue(
  id: string,
): Promise<FieldCatalogueEntry[]> {
  return request<FieldCatalogueEntry[]>(`/templates/${id}/catalogue`);
}

export async function suggestTemplateMapping(
  id: string,
  provider?: string,
): Promise<MappingSuggestResponse> {
  return request<MappingSuggestResponse>(`/templates/${id}/suggest-mapping`, {
    method: "POST",
    query: { provider },
  });
}

export async function generateTemplateOutput(
  id: string,
  p: { documentId: string; flatten?: boolean; signatureImage?: File },
): Promise<GenerateResult> {
  const form = new FormData();
  if (p.signatureImage) form.append("signature_image", p.signatureImage);
  return request<GenerateResult>(`/templates/${id}/generate`, {
    method: "POST",
    query: { document_id: p.documentId, flatten: p.flatten ?? true },
    body: form,
  });
}

// --- vision QA / fidelity ----------------------------------------------------

export async function runTemplateQa(
  id: string,
  body: { document_id?: string | null; provider?: string; instructions?: string | null },
): Promise<QaReport> {
  return request<QaReport>(`/templates/${id}/qa`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

// --- authoring agent (SSE chat) + revisions ----------------------------------

/**
 * Stream a turn of the authoring-agent conversation. Unlike `request`, this
 * keeps the raw response body so we can parse the `text/event-stream` frames as
 * they arrive; each yielded value is one `AgentEvent`.
 */
export async function* streamAgent(
  id: string,
  body: { message: string; history: AgentChatMessage[]; provider?: string },
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/templates/${id}/agent`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the backend — is it running on :8000?");
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
  for await (const ev of readSSE(res)) {
    yield ev as AgentEvent;
  }
}

export async function listTemplateRevisions(
  id: string,
): Promise<TemplateRevisionInfo[]> {
  return request<TemplateRevisionInfo[]>(`/templates/${id}/revisions`);
}

/**
 * Roll the template's html/css back to a prior snapshot. The backend snapshots
 * the current state first, so a restore is itself undoable. Returns the updated
 * template.
 */
export async function restoreTemplateRevision(
  templateId: string,
  revisionId: string,
): Promise<TemplateDetail> {
  return request<TemplateDetail>(
    `/templates/${templateId}/revisions/${revisionId}/restore`,
    { method: "POST" },
  );
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

export async function getSign(id: string): Promise<SignResult> {
  return request<SignResult>(`/documents/${id}/sign`);
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
  engine?: OcrEngine,
): Promise<OCRResult> {
  // Omitting `engine` (undefined is filtered out of the query string) tells the
  // backend to route by the document's doc-type preferred engine + fallback chain.
  return request<OCRResult>(`/documents/${id}/ocr`, {
    method: "POST",
    query: { engine },
  });
}

export async function runStructure(
  id: string,
  p: { docType: DocType; ocrEngine?: OcrEngine },
): Promise<StructuredResult> {
  // A missing `ocr_engine` (filtered from the query) lets the backend fall back to
  // its own routing; callers normally pass the engine that produced the stored OCR.
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

/**
 * Build a download URL for the corrections export endpoint. Like `fileUrl`, this
 * returns a plain absolute URL string rather than going through `request()`:
 * the endpoint streams a file (application/x-ndjson attachment) meant to be
 * fetched by the browser via an `<a download>`, not parsed as JSON by the app.
 * Only the provided params are appended.
 */
export function correctionsExportUrl(opts: {
  docType?: string;
  shape?: "raw" | "examples";
  includeText?: boolean;
}): string {
  const params = new URLSearchParams();
  if (opts.docType) params.set("doc_type", opts.docType);
  if (opts.shape) params.set("shape", opts.shape);
  if (opts.includeText) params.set("include_text", "true");
  const qs = params.toString();
  return `${API_BASE_URL}/corrections/export${qs ? `?${qs}` : ""}`;
}

/**
 * At-risk fields grouped by document (confidence below the threshold). Documents
 * come worst-first and fields worst-confidence-first from the backend.
 */
export async function listReviewQueue(
  opts: { threshold?: number; docType?: string } = {},
): Promise<ReviewQueueResponse> {
  return request<ReviewQueueResponse>("/review-queue", {
    query: { threshold: opts.threshold, doc_type: opts.docType },
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

// --- accuracy-evaluation harness ---------------------------------------------

/** Golden samples in the catalogue. */
export async function listEvalGoldens(): Promise<EvalGoldenSummary[]> {
  return request<EvalGoldenSummary[]>("/eval/goldens");
}

/** One golden with its expected fields/collections (404 ApiError when unknown). */
export async function getEvalGolden(id: string): Promise<EvalGoldenDetail> {
  return request<EvalGoldenDetail>(`/eval/goldens/${id}`);
}

/** Score an engine against a golden; returns the persisted run result. */
export async function runEval(body: {
  golden_id: string;
  engine?: string;
  provider?: string;
  document_id?: string | null;
}): Promise<EvalRunResult> {
  return request<EvalRunResult>("/eval/run", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      golden_id: body.golden_id,
      engine: body.engine ?? "mock",
      provider: body.provider ?? "mock",
      document_id: body.document_id ?? null,
    }),
  });
}

/** List past runs (newest-first), optionally filtered by golden/doc-type/engine. */
export async function listEvalRuns(
  params: { golden_id?: string; doc_type?: string; engine?: string } = {},
): Promise<EvalRunSummary[]> {
  return request<EvalRunSummary[]>("/eval/runs", {
    query: {
      golden_id: params.golden_id,
      doc_type: params.doc_type,
      engine: params.engine,
    },
  });
}

/** Fetch a single run's full result (404 ApiError when unknown). */
export async function getEvalRun(runId: string): Promise<EvalRunResult> {
  return request<EvalRunResult>(`/eval/runs/${runId}`);
}

// --- outbound digital signing (PAdES; off the auto-run pipeline) --------------

export async function runSign(
  id: string,
  provider?: string,
): Promise<SignResult> {
  return request<SignResult>(`/documents/${id}/sign`, {
    method: "POST",
    query: { provider },
  });
}

export async function validateSignature(
  id: string,
  provider?: string,
): Promise<SignatureValidation> {
  return request<SignatureValidation>(`/documents/${id}/validate-signature`, {
    method: "POST",
    query: { provider },
  });
}

/** Seal a generated template output PDF with a real PAdES signature. */
export async function signTemplateOutput(
  templateId: string,
  outputId: string,
  provider?: string,
): Promise<GeneratedSignResult> {
  return request<GeneratedSignResult>(
    `/templates/${templateId}/outputs/${outputId}/sign`,
    { method: "POST", query: { provider } },
  );
}
export { API_BASE_URL };
