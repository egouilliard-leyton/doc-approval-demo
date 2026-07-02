// Shared case-flow header: a breadcrumb ("Cases › <label>") so you always know which
// case you're in, a three-step stage stepper (Upload → Classify → Review) with the
// current stage highlighted so you always know where you are, and a consistent back
// action. Used by ClassifyConfirmView and CaseOverview so the whole flow
// reads as one connected experience.
import { ChevronRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type CaseStageKey = "new" | "classify" | "overview";

const STEPS: { key: CaseStageKey; label: string }[] = [
  { key: "new", label: "Upload" },
  { key: "classify", label: "Classify" },
  { key: "overview", label: "Review" },
];

export function CaseStageHeader({
  stage,
  caseLabel,
  onBack,
  backLabel = "All cases",
  showBack = true,
  right,
}: {
  stage: CaseStageKey;
  /** The active case's label; omitted on the New-case screen. */
  caseLabel?: string;
  /** Back affordance target — the case list. */
  onBack: () => void;
  backLabel?: string;
  /** Render the trailing back button. Off where a footer already offers the action. */
  showBack?: boolean;
  /** Optional trailing content (e.g. a decision badge on the overview). */
  right?: React.ReactNode;
}) {
  const currentIdx = STEPS.findIndex((s) => s.key === stage);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Breadcrumb */}
        <nav className="flex items-center gap-1.5 text-sm">
          <button
            type="button"
            onClick={onBack}
            className="font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Cases
          </button>
          <ChevronRight className="size-3.5 text-muted-foreground/60" />
          <span className="max-w-[24rem] truncate font-medium text-foreground">
            {caseLabel || (stage === "new" ? "New case" : "Untitled case")}
          </span>
        </nav>
        <div className="flex items-center gap-2">
          {right}
          {showBack && (
            <Button variant="outline" size="sm" onClick={onBack}>
              {backLabel}
            </Button>
          )}
        </div>
      </div>

      {/* Stage stepper */}
      <ol className="flex items-center gap-1.5 text-xs">
        {STEPS.map((step, i) => {
          const done = i < currentIdx;
          const active = i === currentIdx;
          return (
            <li key={step.key} className="flex items-center gap-1.5">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium transition-colors",
                  active && "border-brand/40 bg-brand/10 text-brand",
                  done && "border-approve/40 text-approve",
                  !active && !done && "border-border text-muted-foreground",
                )}
              >
                <span
                  className={cn(
                    "flex size-4 items-center justify-center rounded-full text-[10px]",
                    active && "bg-brand text-brand-foreground",
                    done && "bg-approve text-approve-foreground",
                    !active && !done && "bg-muted text-muted-foreground",
                  )}
                >
                  {done ? <Check className="size-2.5" /> : i + 1}
                </span>
                {step.label}
              </span>
              {i < STEPS.length - 1 && (
                <ChevronRight className="size-3.5 text-muted-foreground/40" />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
