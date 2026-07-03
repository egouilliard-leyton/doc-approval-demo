// The case overview (Review stage): the members roster, a completeness banner, the
// cross-document reconciliation table, a Decide action (gated on reconciliation with an
// explicit reason when disabled), the case decision once made, and the member drill-down
// overlay. This is the reviewer's home base — everything needed to trust or challenge
// the case's canonical values sits on one scannable screen.
import { useMemo } from "react";
import {
  ExternalLink,
  RefreshCw,
  Gavel,
  CheckCircle2,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import {
  CASE_DECISION_LABEL,
  CASE_MEMBER_STATUS_LABEL,
  caseDecisionClass,
  isMemberTerminal,
} from "@/lib/case-status";
import { useCaseContext } from "@/features/case/CaseContext";
import { CaseStageHeader } from "@/features/case/CaseStageHeader";
import { ReconciliationView } from "@/features/case/ReconciliationView";
import { CaseDecisionPanel } from "@/features/case/CaseDecisionPanel";
import { CaseMemberDrilldown } from "@/features/case/CaseMemberDrilldown";
import type { CaseMemberState } from "@/features/case/caseReducer";

export function CaseOverview({ onBack }: { onBack: () => void }) {
  const {
    label,
    caseType,
    members,
    memberOrder,
    reconciliation,
    decision,
    reconciling,
    deciding,
    reconcile,
    decide,
    openMember,
  } = useCaseContext();

  const membersArr = useMemo(
    () =>
      memberOrder
        .map((id) => members[id])
        .filter((m): m is CaseMemberState => Boolean(m)),
    [members, memberOrder],
  );

  const filenameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const m of membersArr) {
      if (m.documentId) map[m.documentId] = m.filename;
    }
    return map;
  }, [membersArr]);

  const conflicts =
    reconciliation?.canonical_fields.filter((f) => !f.agreement).length ?? 0;
  // Don't allow reconciling a still-extracting case — every member must be terminal.
  const allTerminal = membersArr.every((m) => isMemberTerminal(m.status));
  const decideReason = !reconciliation
    ? "Reconcile the case first to enable a decision."
    : deciding
      ? "Deciding…"
      : null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <CaseStageHeader
        stage="overview"
        caseLabel={label}
        onBack={onBack}
        right={
          decision ? (
            <Badge
              variant="outline"
              className={cn("gap-1", caseDecisionClass(decision.decision))}
            >
              {CASE_DECISION_LABEL[decision.decision]}
            </Badge>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">
            {label || "Untitled case"}
          </h2>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            {caseType ? (
              <Badge variant="secondary" className="capitalize">
                {caseType}
              </Badge>
            ) : (
              <Badge variant="outline" className="text-muted-foreground">
                Open pile
              </Badge>
            )}
            <span>
              {membersArr.length} document{membersArr.length === 1 ? "" : "s"}
            </span>
          </div>
        </div>
      </div>

      {/* Members roster */}
      <section className="space-y-2">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Documents
        </h3>
        <div className="overflow-hidden rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Document</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {membersArr.map((m) => {
                const Icon = resolveDocTypeIcon(m.confirmedDocType);
                const failed = m.status === "error";
                return (
                  <TableRow key={m.memberId}>
                    <TableCell className="max-w-[16rem]">
                      <span className="flex items-center gap-2">
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate" title={m.filename}>
                          {m.filename}
                        </span>
                      </span>
                    </TableCell>
                    <TableCell>
                      {m.confirmedDocType ? (
                        <Badge variant="secondary" className="capitalize">
                          {m.confirmedDocType}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={cn(
                          failed
                            ? "border-flag/40 text-flag"
                            : m.status === "structured"
                              ? "border-approve/40 text-approve"
                              : "border-border text-muted-foreground",
                        )}
                      >
                        {CASE_MEMBER_STATUS_LABEL[m.status]}
                      </Badge>
                      {failed && m.error && (
                        <span
                          className="ml-2 text-xs text-flag"
                          title={m.error}
                        >
                          {m.error}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!m.documentId}
                        onClick={() => m.documentId && openMember(m.documentId)}
                      >
                        <ExternalLink className="size-3.5" />
                        Open
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </section>

      {/* Completeness banner */}
      {reconciliation ? (
        <CompletenessBanner
          memberCount={reconciliation.member_count}
          structuredCount={reconciliation.structured_count}
          conflicts={conflicts}
          warnings={reconciliation.warnings}
        />
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-review/40 bg-review-muted/30 p-4">
          <div className="flex items-center gap-2 text-sm">
            <AlertTriangle className="size-4 text-review-foreground" />
            <span>
              {allTerminal
                ? "Documents extracted — reconcile them into canonical fields."
                : "Waiting for all documents to finish extracting…"}
            </span>
          </div>
          <Button
            onClick={() => void reconcile()}
            disabled={reconciling || !allTerminal}
            title={
              !allTerminal
                ? "Waiting for all documents to finish extracting"
                : undefined
            }
          >
            {reconciling ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Reconcile
          </Button>
        </div>
      )}

      {/* Reconciliation table */}
      {reconciliation && (
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Reconciled fields
            </h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void reconcile()}
              disabled={reconciling}
            >
              {reconciling ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <RefreshCw className="size-3.5" />
              )}
              Re-reconcile
            </Button>
          </div>
          <ReconciliationView
            reconciliation={reconciliation}
            filenameById={filenameById}
          />
        </section>
      )}

      {/* Decide — only once a reconciliation exists, so the disabled primary doesn't
          steal attention from the real next step (Reconcile) before then. */}
      {reconciliation && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-4">
          <div className="min-w-0 space-y-0.5">
            <p className="text-sm font-medium">Case decision</p>
            <p className="text-xs text-muted-foreground">
              {decision
                ? "Re-run the decision after resolving conflicts, if needed."
                : "Approve, flag, or route the whole case for human review."}
            </p>
          </div>
          <Button
            onClick={() => void decide()}
            disabled={deciding}
            title={decideReason ?? undefined}
          >
            {deciding ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Gavel className="size-4" />
            )}
            {decision ? "Decide again" : "Decide case"}
          </Button>
        </div>
      )}

      {/* Decision panel */}
      {decision && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Decision
          </h3>
          <CaseDecisionPanel decision={decision} />
        </section>
      )}

      {/* Member drill-down overlay */}
      <CaseMemberDrilldown />
    </div>
  );
}

function CompletenessBanner({
  memberCount,
  structuredCount,
  conflicts,
  warnings,
}: {
  memberCount: number;
  structuredCount: number;
  conflicts: number;
  warnings: string[];
}) {
  const complete = structuredCount >= memberCount && conflicts === 0;
  const Icon = complete ? CheckCircle2 : AlertTriangle;
  return (
    <div
      className={cn(
        "space-y-2 rounded-xl border p-4",
        complete
          ? "border-approve/40 bg-approve/[0.05]"
          : "border-review/40 bg-review-muted/30",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span
          className={cn(
            "flex items-center gap-2 font-medium",
            complete ? "text-approve" : "text-review-foreground",
          )}
        >
          <Icon className="size-4" />
          {structuredCount} of {memberCount} document
          {memberCount === 1 ? "" : "s"} extracted
        </span>
        {conflicts > 0 && (
          <span className="flex items-center gap-1.5 text-review-foreground">
            <AlertTriangle className="size-3.5" />
            {conflicts} field{conflicts === 1 ? "" : "s"} in conflict
          </span>
        )}
      </div>
      {warnings.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <span className="mt-1.5 size-1 shrink-0 rounded-full bg-current opacity-50" />
              {w}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
