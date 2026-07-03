// Pure derivations for the case flow's navigation: which stage a live (in-context)
// case is at, and a legible per-member extraction progress tally. Kept here (lib, no
// React) so the shell router, the stage header, and the progress banner read one
// source of truth — and so the logic is unit-testable in isolation.
import { isMemberTerminal, type CaseMemberStatus } from "@/lib/case-status";

/** The stage of a case that is loaded in the case context (excludes list/new). */
export type CaseStage = "classify" | "overview";

/**
 * Which stage an active case is at, from its member statuses + whether it has been
 * reconciled. Reconciled (or every member settled into a terminal state) means the
 * classify/confirm work is done — move to the overview. Otherwise stay on classify.
 */
export function deriveCaseStage(
  statuses: CaseMemberStatus[],
  hasReconciliation: boolean,
): CaseStage {
  if (hasReconciliation) return "overview";
  if (statuses.length > 0 && statuses.every(isMemberTerminal)) return "overview";
  return "classify";
}

/** Per-member extraction tally for the "3 of 5 extracted" progress banner. */
export interface MemberProgress {
  total: number;
  settled: number; // terminal: structured or errored
  structured: number;
  errored: number;
  active: number; // still in flight (not terminal)
}

export function memberProgress(statuses: CaseMemberStatus[]): MemberProgress {
  let structured = 0;
  let errored = 0;
  for (const s of statuses) {
    if (s === "structured") structured++;
    else if (s === "error") errored++;
  }
  const settled = structured + errored;
  return {
    total: statuses.length,
    settled,
    structured,
    errored,
    active: statuses.length - settled,
  };
}
