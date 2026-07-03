// The classify/confirm stage: one legible row per member document showing its live
// pipeline stage (with a subtle progress bar, not a spinner-soup), the classifier's
// ranked candidates, and a doc-type override that defaults to the top guess. The footer
// extracts every confirmed member. A member that fails is shown inline in red while its
// siblings proceed — one document's failure never blocks the case.
import { createElement, useEffect, useMemo } from "react";
import { AlertCircle, Sparkles, Wand2, ScanLine } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { cn } from "@/lib/utils";
import { formatPct } from "@/lib/format";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import {
  CASE_MEMBER_STATUS_LABEL,
  CASE_MEMBER_STATUS_ORDER,
  isMemberTerminal,
  type CaseMemberStatus,
} from "@/lib/case-status";
import { useDocTypes } from "@/features/doctypes/useDocTypes";
import { useCaseContext } from "@/features/case/CaseContext";
import { CaseStageHeader } from "@/features/case/CaseStageHeader";
import type { CaseMemberState } from "@/features/case/caseReducer";

const LAST_STEP = CASE_MEMBER_STATUS_ORDER.indexOf("structured");

/** How far through the pipeline a status is, 0–100 (used for the row progress bar). */
function stageProgress(status: CaseMemberStatus): number {
  if (status === "error") return 100;
  const idx = CASE_MEMBER_STATUS_ORDER.indexOf(status);
  return Math.round((Math.max(idx, 0) / LAST_STEP) * 100);
}

function statusBadgeClass(status: CaseMemberStatus): string {
  if (status === "structured") return "border-approve/40 text-approve";
  if (status === "error") return "border-flag/40 text-flag";
  if (status === "confirmed") return "border-brand/40 text-brand";
  return "border-border text-muted-foreground";
}

function MemberRow({
  member,
  docTypeOptions,
  docTypesLoading,
  onConfirm,
}: {
  member: CaseMemberState;
  docTypeOptions: ComboboxOption[];
  docTypesLoading: boolean;
  onConfirm: (docType: string) => void;
}) {
  const docIcon = resolveDocTypeIcon(member.confirmedDocType);
  const classified = member.classify != null || isMemberTerminal(member.status);
  const inFlight = !classified && member.status !== "error";
  const topCandidate = member.classify?.candidates[0]?.doc_type ?? null;
  const selected = member.confirmedDocType ?? topCandidate ?? "";
  const errored = member.status === "error";

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-xl border bg-card p-4",
        errored && "border-flag/30 bg-flag/[0.03]",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-lg border bg-background text-muted-foreground">
            {createElement(docIcon, { className: "size-4.5" })}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium" title={member.filename}>
              {member.filename}
            </p>
            <Badge
              variant="outline"
              className={cn("mt-0.5", statusBadgeClass(member.status))}
            >
              {member.status !== "error" &&
                member.status !== "structured" &&
                member.status !== "confirmed" && (
                  <ScanLine className="size-3 animate-pulse" />
                )}
              {CASE_MEMBER_STATUS_LABEL[member.status]}
            </Badge>
          </div>
        </div>

        {/* Doc-type override */}
        <div className="w-56 shrink-0">
          <label className="mb-1 block text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            Document type
          </label>
          {errored ? (
            <span className="text-xs text-muted-foreground">—</span>
          ) : classified ? (
            <Combobox
              value={selected}
              onChange={onConfirm}
              options={docTypeOptions}
              placeholder="Pick a type…"
              searchPlaceholder="Search types…"
              emptyText="No types match."
              disabled={docTypesLoading}
            />
          ) : (
            <Skeleton className="h-8 w-full rounded-lg" />
          )}
        </div>
      </div>

      {/* Live progress while the member's pipeline runs. */}
      {inFlight && (
        <Progress value={stageProgress(member.status)} className="h-1" />
      )}

      {/* Classifier candidates. */}
      {errored ? (
        <p className="flex items-start gap-1.5 text-xs text-flag">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
          {member.error ?? "This document failed to process."}
        </p>
      ) : classified && member.classify ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <Sparkles className="size-3.5 text-muted-foreground" />
          {member.classify.candidates.length > 0 ? (
            member.classify.candidates.map((c, i) => (
              <span
                key={c.doc_type}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs",
                  i === 0
                    ? "border-brand/30 bg-brand/[0.04] font-medium"
                    : "border-border text-muted-foreground",
                )}
              >
                <span className="capitalize">{c.doc_type}</span>
                <span className="font-mono">{formatPct(c.score)}</span>
              </span>
            ))
          ) : (
            <span className="text-xs text-muted-foreground">
              No confident guess — pick a type.
            </span>
          )}
        </div>
      ) : (
        <Skeleton className="h-4 w-2/3" />
      )}
    </div>
  );
}

export function ClassifyConfirmView({
  ocrEngine,
  onBack,
}: {
  ocrEngine: string;
  onBack: () => void;
}) {
  const { label, members, memberOrder, setConfirmedDocType, confirmAndExtract } =
    useCaseContext();
  const { docTypes, loading: docTypesLoading } = useDocTypes();

  const membersArr = useMemo(
    () =>
      memberOrder
        .map((id) => members[id])
        .filter((m): m is CaseMemberState => Boolean(m)),
    [members, memberOrder],
  );

  const docTypeOptions = useMemo<ComboboxOption[]>(
    () => docTypes.map((dt) => ({ value: dt.name, label: dt.label || dt.name })),
    [docTypes],
  );

  // Auto-apply the top guess for each newly-classified member so every document
  // carries a confirmed type into extraction (the reviewer can still override). Only
  // fires when a candidate exists and nothing is confirmed yet — never re-dispatches.
  useEffect(() => {
    for (const m of membersArr) {
      if (
        m.confirmedDocType == null &&
        m.status === "classified" &&
        m.classify?.candidates[0]?.doc_type
      ) {
        setConfirmedDocType(m.memberId, m.classify.candidates[0].doc_type);
      }
    }
  }, [membersArr, setConfirmedDocType]);

  const classifiedCount = membersArr.filter(
    (m) => m.classify != null || isMemberTerminal(m.status),
  ).length;
  const extracting = membersArr.some((m) => m.status === "structuring");
  const allClassified =
    membersArr.length > 0 &&
    membersArr.every(
      (m) => m.confirmedDocType != null || isMemberTerminal(m.status),
    );
  const extractCount = membersArr.filter(
    (m) => m.confirmedDocType && m.documentId,
  ).length;
  const canExtract = allClassified && extractCount > 0 && !extracting;

  const extractHint = extracting
    ? "Extracting…"
    : !allClassified
      ? "Waiting for every document to finish classifying."
      : extractCount === 0
        ? "Confirm at least one document's type to extract."
        : null;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <CaseStageHeader stage="classify" caseLabel={label} onBack={onBack} />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">
            Classify &amp; confirm
          </h2>
          <p className="text-sm text-muted-foreground">
            Confirm each document's type, then extract. We suggest a type — you
            have the final say.
          </p>
        </div>
        <Badge variant="outline" className="border-border text-muted-foreground">
          {classifiedCount} of {membersArr.length} classified
        </Badge>
      </div>

      <div className="space-y-3">
        {membersArr.map((member) => (
          <MemberRow
            key={member.memberId}
            member={member}
            docTypeOptions={docTypeOptions}
            docTypesLoading={docTypesLoading}
            onConfirm={(docType) => setConfirmedDocType(member.memberId, docType)}
          />
        ))}
      </div>

      <div className="sticky bottom-0 -mx-1 flex items-center justify-between gap-3 rounded-xl border bg-background/90 px-4 py-3 backdrop-blur">
        <span className="text-xs text-muted-foreground">
          {extractHint ?? `Ready to extract ${extractCount} document${extractCount === 1 ? "" : "s"}.`}
        </span>
        <Button
          onClick={() => void confirmAndExtract(ocrEngine)}
          disabled={!canExtract}
          title={extractHint ?? undefined}
        >
          {extracting ? (
            <>
              <ScanLine className="size-4 animate-pulse" />
              Extracting…
            </>
          ) : (
            <>
              <Wand2 className="size-4" />
              Extract {extractCount} document{extractCount === 1 ? "" : "s"}
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
