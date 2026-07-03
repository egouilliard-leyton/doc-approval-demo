// Admin review queue: every extracted field whose confidence falls below the
// backend threshold, grouped by document. Documents come sorted worst-first and
// each document's fields worst-confidence-first, so we render the response as-is.
// Each field row deep-links straight to that field in the document's structured
// tab (the inspector focuses it on load).
import { useEffect, useState } from "react";
import { AlertTriangle, ChevronRight, ExternalLink } from "lucide-react";
import { ApiError, listReviewQueue } from "@/lib/api";
import { humanize } from "@/lib/fields";
import { cn } from "@/lib/utils";
import { CASE_DECISION_LABEL, caseDecisionClass } from "@/lib/case-status";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfidencePill } from "@/features/inspector/StructuredPanel";
import type { Route } from "@/lib/route";
import type { Decision, ReviewQueueDocument, ReviewQueueField } from "@/lib/types";

function display(v: string | number | boolean | null): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

function DocTypeBadge({ docType }: { docType: string }) {
  return (
    <span className="shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium text-muted-foreground capitalize">
      {humanize(docType)}
    </span>
  );
}

/** Annotation-only badge for the document's last decision (may be absent). */
function DecisionBadge({ decision }: { decision: Decision | null }) {
  if (!decision) return null;
  return (
    <span
      className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        caseDecisionClass(decision),
      )}
    >
      {CASE_DECISION_LABEL[decision]}
    </span>
  );
}

// --- one at-risk field row: humanized path, value, confidence; opens the field --

function FieldRow({
  field,
  onOpen,
}: {
  field: ReviewQueueField;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2 text-left hover:bg-muted/50"
    >
      <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
        {humanize(field.path.replace(/\./g, " "))}
      </span>
      <div className="flex items-center gap-2 font-mono text-xs">
        <span className="rounded bg-muted px-1.5 py-0.5 text-foreground">
          {display(field.value)}
        </span>
        <ConfidencePill value={field.confidence} />
        <ExternalLink className="size-3.5 text-muted-foreground" />
      </div>
    </button>
  );
}

// --- one document card, expandable to its at-risk fields ---------------------

function DocumentCard({
  doc,
  expanded,
  onToggle,
  onOpenField,
}: {
  doc: ReviewQueueDocument;
  expanded: boolean;
  onToggle: () => void;
  onOpenField: (field: ReviewQueueField) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50"
      >
        <ChevronRight
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-90",
          )}
        />
        <span className="min-w-0 flex-1 truncate font-medium">
          {doc.filename}
        </span>
        <DocTypeBadge docType={doc.doc_type} />
        <DecisionBadge decision={doc.last_decision} />
        <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
          {doc.at_risk_count} at-risk field{doc.at_risk_count === 1 ? "" : "s"}
        </span>
        <ConfidencePill value={doc.lowest_confidence} />
      </button>
      {expanded && (
        <div className="border-t bg-muted/20 p-1">
          {doc.fields.map((f) => (
            <FieldRow key={f.path} field={f} onOpen={() => onOpenField(f)} />
          ))}
        </div>
      )}
    </div>
  );
}

// --- section -----------------------------------------------------------------

export function ReviewQueueSection({
  navigate,
}: {
  navigate: (to: Route) => void;
}) {
  const [queue, setQueue] = useState<ReviewQueueDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await listReviewQueue();
        if (cancelled) return;
        setQueue(res.documents);
      } catch (e) {
        if (!cancelled)
          setError(
            e instanceof ApiError ? e.message : "Could not load the review queue.",
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const openField = (doc: ReviewQueueDocument, field: ReviewQueueField) =>
    navigate({
      view: "document",
      id: doc.document_id,
      tab: "structured",
      field: field.path,
    });

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!queue) return <Skeleton className="h-64 w-full rounded-xl" />;
  if (queue.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-xl border border-dashed px-4 text-center text-sm text-muted-foreground">
        No at-risk fields — every extracted field meets the confidence threshold.
      </div>
    );
  }

  const totalFields = queue.reduce((sum, d) => sum + d.at_risk_count, 0);

  return (
    <div className="space-y-3">
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <AlertTriangle className="size-3.5" />
        {totalFields} at-risk field{totalFields === 1 ? "" : "s"} across{" "}
        {queue.length} document{queue.length === 1 ? "" : "s"}
      </span>
      <div className="space-y-2">
        {queue.map((doc) => (
          <DocumentCard
            key={doc.document_id}
            doc={doc}
            expanded={expanded.has(doc.document_id)}
            onToggle={() => toggle(doc.document_id)}
            onOpenField={(f) => openField(doc, f)}
          />
        ))}
      </div>
    </div>
  );
}
