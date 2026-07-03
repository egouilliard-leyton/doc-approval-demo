// Fetch client for the FastAPI backend.
// CORS on the backend already allows the Vite dev origin, so we call it directly.
import type {
  AgentChatMessage,
  AgentEvent,
  DocumentDetail,
  DocumentSummary,
  DecisionResult,
  DocType,
  FieldCatalogueEntry,
  GenerateResult,
  MappingSuggestResponse,
  OcrEngine,
  OCRResult,
  QaReport,
  QualityReport,
  StructuredResult,
  TemplateCreate,
  TemplateDetail,
  TemplateRevisionInfo,
  TemplateSummary,
  TemplateUpdate,
} from "@/lib/types";
import { readSSE } from "@/lib/sse";

const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const { method = "GET", query, body, headers, signal } = opts;
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
      headers,
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
): Promise<DocumentDetail> {
  const form = new FormData();
  form.append("file", file);
  if (docType) form.append("doc_type", docType);
  return request<DocumentDetail>("/documents", { method: "POST", body: form });
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/documents/${id}`);
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

export { API_BASE_URL };
