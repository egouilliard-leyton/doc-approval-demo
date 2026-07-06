// Shared document-status vocabulary for the admin views (labels, badge colors,
// and a sensible display order — most-actionable first).
import type { DocumentStatus } from "@/lib/types";

export const DOC_STATUS_LABEL: Record<DocumentStatus, string> = {
  uploaded: "Uploaded",
  prescanned: "Pre-scanned",
  ocr_done: "OCR done",
  structured: "Structured",
  decided: "Decided",
  needs_review: "Needs review",
  signed: "Signed",
};

/** Order used for filter chips / groups: things needing attention come first. */
export const DOC_STATUS_ORDER: DocumentStatus[] = [
  "needs_review",
  "decided",
  "signed",
  "structured",
  "ocr_done",
  "prescanned",
  "uploaded",
];

export function docStatusClass(status: DocumentStatus): string {
  if (status === "decided" || status === "signed")
    return "border-approve/40 text-approve";
  if (status === "needs_review") return "border-review/40 text-review-foreground";
  return "border-border text-muted-foreground";
}

// Spreadsheet MIME types — these render as an interactive grid (GridViewer) rather
// than a page image, and ground fields to cells. Mirror of backend SPREADSHEET_MIMES.
const SPREADSHEET_MIMES = new Set([
  "text/csv",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]);

/** True for CSV/XLSX documents (native grid + cell grounding, no page image). */
export function isSpreadsheet(mime: string): boolean {
  return SPREADSHEET_MIMES.has(mime);
}
