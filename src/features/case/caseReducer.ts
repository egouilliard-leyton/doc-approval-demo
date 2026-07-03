// Pure state machine for a multi-document case: owns the per-member pipeline
// progress, the reconciliation + decision results, and the drill-down focus. Extracted
// from the useCase hook (unlike usePipeline's inline reducer) so it's unit-testable in
// isolation. Every transition is pure and immutable — a member update never mutates its
// siblings. Mirrors usePipeline's Action-union + initial-state-factory conventions.
import type { CaseMemberStatus } from "@/lib/case-status";
import type {
  CaseDecisionResult,
  CaseReconciliation,
  ClassifyResult,
  DocType,
} from "@/lib/types";

export type { CaseMemberStatus };

/** One document as it moves through the case pipeline (upload -> ... -> structured). */
export interface CaseMemberState {
  memberId: string; // stable client-side id, assigned before upload
  file: File | null; // the source file; null once reopened from the server
  documentId: string | null; // set once uploaded
  filename: string;
  status: CaseMemberStatus;
  classify: ClassifyResult | null; // the auto-classification guess, if run
  confirmedDocType: DocType | null; // the reviewer-confirmed doc type
  ocrEngine: string | null; // the engine that ACTUALLY ran OCR (may be routed under "auto")
  error: string | null;
}

export interface CaseState {
  caseId: string | null;
  caseType: string | null;
  label: string;
  ocrEngine: string; // case-global OCR engine, chosen at upload and reused for extraction

  members: Record<string, CaseMemberState>;
  memberOrder: string[]; // memberIds in insertion order
  reconciliation: CaseReconciliation | null;
  decision: CaseDecisionResult | null;
  reconciling: boolean;
  deciding: boolean;
  activeDocId: string | null; // the drilled-into member document, if any
  focus: { documentId: string; field?: string; page?: number } | null;
}

/** A member to seed (queued) — the minimal shape known before upload. */
export interface NewCaseMember {
  memberId: string;
  file: File | null;
  filename: string;
}

export function initialCaseState(): CaseState {
  return {
    caseId: null,
    caseType: null,
    label: "",
    ocrEngine: "",
    members: {},
    memberOrder: [],
    reconciliation: null,
    decision: null,
    reconciling: false,
    deciding: false,
    activeDocId: null,
    focus: null,
  };
}

export type CaseAction =
  | {
      type: "CREATE_CASE_DONE";
      caseId: string;
      caseType: string | null;
      label: string;
      ocrEngine: string;
    }
  | { type: "ADD_MEMBERS"; members: NewCaseMember[] }
  | { type: "MEMBER_STAGE_START"; memberId: string; status: CaseMemberStatus }
  | {
      type: "MEMBER_STAGE_DONE";
      memberId: string;
      status: CaseMemberStatus;
      documentId?: string;
    }
  | { type: "MEMBER_STAGE_ERROR"; memberId: string; error: string }
  | {
      type: "MEMBER_CLASSIFY_DONE";
      memberId: string;
      classify: ClassifyResult;
      ocrEngine?: string; // the engine that produced the OCR feeding this classify
    }
  | { type: "MEMBER_CONFIRM_DOC_TYPE"; memberId: string; docType: DocType }
  | { type: "RECONCILE_START" }
  | { type: "RECONCILE_DONE"; result: CaseReconciliation }
  | { type: "RECONCILE_ERROR" }
  | { type: "DECIDE_START" }
  | { type: "DECIDE_DONE"; result: CaseDecisionResult }
  | { type: "DECIDE_ERROR" }
  | { type: "OPEN_MEMBER"; documentId: string }
  | { type: "NAVIGATE_TO_FIELD"; documentId: string; field?: string; page?: number }
  | { type: "CLOSE_DRILLDOWN" }
  | { type: "RESET" };

/** Immutably replace one member; a no-op (same state) if the member is unknown. */
function patchMember(
  state: CaseState,
  memberId: string,
  patch: Partial<CaseMemberState>,
): CaseState {
  const member = state.members[memberId];
  if (!member) return state;
  return {
    ...state,
    members: { ...state.members, [memberId]: { ...member, ...patch } },
  };
}

export function caseReducer(state: CaseState, action: CaseAction): CaseState {
  switch (action.type) {
    case "CREATE_CASE_DONE":
      return {
        ...state,
        caseId: action.caseId,
        caseType: action.caseType,
        label: action.label,
        ocrEngine: action.ocrEngine,
      };
    case "ADD_MEMBERS": {
      const members = { ...state.members };
      const order = [...state.memberOrder];
      for (const m of action.members) {
        members[m.memberId] = {
          memberId: m.memberId,
          file: m.file,
          documentId: null,
          filename: m.filename,
          status: "queued",
          classify: null,
          confirmedDocType: null,
          ocrEngine: null,
          error: null,
        };
        order.push(m.memberId);
      }
      return { ...state, members, memberOrder: order };
    }
    case "MEMBER_STAGE_START":
      return patchMember(state, action.memberId, {
        status: action.status,
        error: null,
      });
    case "MEMBER_STAGE_DONE":
      return patchMember(state, action.memberId, {
        status: action.status,
        ...(action.documentId ? { documentId: action.documentId } : {}),
      });
    case "MEMBER_STAGE_ERROR":
      return patchMember(state, action.memberId, {
        status: "error",
        error: action.error,
      });
    case "MEMBER_CLASSIFY_DONE":
      return patchMember(state, action.memberId, {
        classify: action.classify,
        status: "classified",
        ...(action.ocrEngine ? { ocrEngine: action.ocrEngine } : {}),
      });
    case "MEMBER_CONFIRM_DOC_TYPE":
      return patchMember(state, action.memberId, {
        confirmedDocType: action.docType,
        status: "confirmed",
      });
    case "RECONCILE_START":
      return { ...state, reconciling: true };
    case "RECONCILE_DONE":
      return { ...state, reconciling: false, reconciliation: action.result };
    case "RECONCILE_ERROR":
      return { ...state, reconciling: false };
    case "DECIDE_START":
      return { ...state, deciding: true };
    case "DECIDE_DONE":
      return { ...state, deciding: false, decision: action.result };
    case "DECIDE_ERROR":
      return { ...state, deciding: false };
    case "OPEN_MEMBER":
      return {
        ...state,
        activeDocId: action.documentId,
        focus: { documentId: action.documentId },
      };
    case "NAVIGATE_TO_FIELD":
      return {
        ...state,
        activeDocId: action.documentId,
        focus: {
          documentId: action.documentId,
          field: action.field,
          page: action.page,
        },
      };
    case "CLOSE_DRILLDOWN":
      return { ...state, activeDocId: null, focus: null };
    case "RESET":
      return initialCaseState();
    default:
      return state;
  }
}
