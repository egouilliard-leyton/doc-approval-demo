// Case-level decision panel — a parallel to DecisionCard (which is typed to the
// single-doc DecisionResult and so not reusable here), reusing the generic
// ConfidenceMeter + CheckTrace. Presentational: it renders a CaseDecisionResult and
// routes citation clicks back through the case context so a reviewer can jump to the
// cited source document. When the decision is needs_review it spells out what the human
// should do next, making the "flag for human review" policy actionable in the UI.
import { CheckCircle2, Flag, HelpCircle, ArrowUpRight } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { ConfidenceMeter } from "@/features/decision/ConfidenceMeter";
import { CheckTrace } from "@/features/decision/CheckTrace";
import { useCaseContext } from "@/features/case/CaseContext";
import type { CaseDecisionResult, Decision } from "@/lib/types";

const DECISION_META: Record<
  Decision,
  { label: string; tone: "approve" | "flag" | "review"; icon: typeof CheckCircle2 }
> = {
  // Past-tense labels (a decision that's been made reads "Approved"), matching the
  // CASE_DECISION_LABEL vocabulary used on the overview header badge.
  approve: { label: "Approved", tone: "approve", icon: CheckCircle2 },
  flag: { label: "Flagged", tone: "flag", icon: Flag },
  needs_review: { label: "Needs review", tone: "review", icon: HelpCircle },
};

const TONE_BG: Record<string, string> = {
  approve: "border-approve/40 bg-approve/[0.06]",
  flag: "border-flag/40 bg-flag/[0.06]",
  review: "border-review/40 bg-review-muted/40",
};

const TONE_BADGE: Record<string, string> = {
  approve: "bg-approve text-approve-foreground",
  flag: "bg-flag text-flag-foreground",
  review: "bg-review text-review-foreground",
};

export function CaseDecisionPanel({
  decision,
}: {
  decision: CaseDecisionResult;
}) {
  const { navigateToCanonicalField } = useCaseContext();
  const meta = DECISION_META[decision.decision];
  const Icon = meta.icon;
  const overridden =
    decision.llm_decision != null &&
    decision.llm_decision !== decision.decision;
  const failedChecks = decision.checks.filter((c) => !c.passed);

  return (
    <div className="space-y-5">
      <div className={cn("space-y-4 rounded-2xl border p-5", TONE_BG[meta.tone])}>
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex size-12 items-center justify-center rounded-xl",
              TONE_BADGE[meta.tone],
            )}
          >
            <Icon className="size-6" />
          </div>
          <div>
            <div className="text-2xl font-semibold tracking-tight">
              {meta.label}
            </div>
            <div className="font-mono text-xs text-muted-foreground">
              case decision{decision.case_type ? ` · ${decision.case_type}` : ""}
            </div>
          </div>
        </div>

        <ConfidenceMeter value={decision.confidence} tone={meta.tone} />

        {overridden && (
          <p className="rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
            Code reconciliation overrode the model (it proposed{" "}
            <span className="font-medium">{decision.llm_decision}</span>) — a
            hard rule cannot be overruled, only explained.
          </p>
        )}

        {decision.reasons.length > 0 && (
          <ul className="space-y-1.5">
            {decision.reasons.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span
                  className={cn(
                    "mt-1.5 size-1.5 shrink-0 rounded-full",
                    TONE_BADGE[meta.tone],
                  )}
                />
                <span className="text-foreground/90">{r}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* The human-review moment: say exactly what to check and let them jump there. */}
      {decision.decision === "needs_review" && (
        <div className="space-y-2 rounded-xl border border-review/40 bg-review-muted/30 p-4">
          <h3 className="flex items-center gap-2 text-sm font-medium text-review-foreground">
            <HelpCircle className="size-4" />
            Needs a human
          </h3>
          {failedChecks.length > 0 ? (
            <>
              <p className="text-xs text-muted-foreground">
                {failedChecks.length} check
                {failedChecks.length === 1 ? "" : "s"} did not pass — review
                these before approving or flagging:
              </p>
              <ul className="space-y-1">
                {failedChecks.map((c) => (
                  <li
                    key={c.name}
                    className="flex items-baseline gap-2 text-xs"
                  >
                    <span className="font-mono font-medium">{c.name}</span>
                    <span className="text-muted-foreground">{c.detail}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              Confidence is below the auto-approve threshold. Check the
              conflicting reconciliation fields above, then decide.
            </p>
          )}
        </div>
      )}

      <div className="space-y-2">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Rule checks
        </h3>
        <CheckTrace checks={decision.checks} />
      </div>

      {decision.citations.length > 0 && (
        <div className="space-y-2">
          <Separator />
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Citations
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {decision.citations.map((c, i) => (
              <button
                key={`${c.field}-${c.document_id ?? i}`}
                type="button"
                disabled={!c.document_id}
                onClick={() =>
                  c.document_id &&
                  navigateToCanonicalField(c.document_id, c.field)
                }
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border bg-muted/40 px-2 py-1 font-mono text-xs transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
                  c.document_id
                    ? "hover:border-brand/40 hover:bg-brand/[0.03]"
                    : "cursor-default",
                )}
              >
                {c.field}{" "}
                <span className="text-muted-foreground">· {c.source}</span>
                {c.document_id && (
                  <ArrowUpRight className="size-3 text-muted-foreground" />
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
