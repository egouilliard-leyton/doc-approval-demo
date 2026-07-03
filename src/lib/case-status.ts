// Shared case vocabulary (member-status labels, decision badge tones, and the
// reconciliation agreement/kind helpers). Mirrors doc-status.ts: pure label maps +
// class-name helpers, no React. The member-status union lives here (lib) so both the
// reducer and the Wave 2 screens read one source of truth.
import type { Decision } from "@/lib/types";

/** Per-member pipeline status inside a case (queued -> ... -> structured | error). */
export type CaseMemberStatus =
  | "queued"
  | "uploading"
  | "uploaded"
  | "prescanning"
  | "ocr_running"
  | "classifying"
  | "classified"
  | "confirmed"
  | "structuring"
  | "structured"
  | "error";

export const CASE_MEMBER_STATUS_LABEL: Record<CaseMemberStatus, string> = {
  queued: "Queued",
  uploading: "Uploading",
  uploaded: "Uploaded",
  prescanning: "Pre-scanning",
  ocr_running: "OCR",
  classifying: "Classifying",
  classified: "Classified",
  confirmed: "Confirmed",
  structuring: "Structuring",
  structured: "Structured",
  error: "Error",
};

/** Order for member lists / progress display — in-flight/terminal at the ends. */
export const CASE_MEMBER_STATUS_ORDER: CaseMemberStatus[] = [
  "queued",
  "uploading",
  "uploaded",
  "prescanning",
  "ocr_running",
  "classifying",
  "classified",
  "confirmed",
  "structuring",
  "structured",
  "error",
];

/** Terminal member states: no further pipeline work will run for them. */
export function isMemberTerminal(status: CaseMemberStatus): boolean {
  return status === "structured" || status === "error";
}

// --- case decision badge tones (mirror doc-status decision vocabulary) --------

export const CASE_DECISION_LABEL: Record<Decision, string> = {
  approve: "Approved",
  needs_review: "Needs review",
  flag: "Flagged",
};

/** Border+text classes for a case decision badge (approve=green, review=amber, flag=red). */
export function caseDecisionClass(decision: Decision): string {
  if (decision === "approve") return "border-approve/40 text-approve";
  if (decision === "flag") return "border-flag/40 text-flag";
  return "border-review/40 text-review-foreground";
}

// --- reconciliation helpers --------------------------------------------------

/** Tone for a reconciled field's agreement flag: agree=green, conflict=amber (review). */
export function agreementTone(agreement: boolean): string {
  return agreement ? "text-approve" : "text-review-foreground";
}

/** Human label for a canonical field's reconciliation kind (money/date/string/...). */
export function kindLabel(kind: string): string {
  const known: Record<string, string> = {
    money: "Money",
    date: "Date",
    string: "Text",
  };
  return known[kind] ?? (kind ? kind[0].toUpperCase() + kind.slice(1) : "—");
}
