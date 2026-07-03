// Presentational cross-document reconciliation table: one row per canonical field with
// its reconciled value, an agree/conflict badge, the tolerance kind, an expandable list
// of contributing candidates, and per-field citation pills. Clicking a candidate or a
// citation drills into that member document and jumps to the field via the case context.
import { useState } from "react";
import {
  ChevronRight,
  CheckCircle2,
  AlertTriangle,
  CircleDollarSign,
  CalendarDays,
  Type as TypeIcon,
} from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { kindLabel } from "@/lib/case-status";
import { ConfidencePill } from "@/features/inspector/StructuredPanel";
import { useCaseContext } from "@/features/case/CaseContext";
import type { CanonicalFieldResult, CandidateInfo } from "@/lib/types";

function formatValue(value: string | number | boolean | null): string {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

const KIND_ICON: Record<string, typeof TypeIcon> = {
  money: CircleDollarSign,
  date: CalendarDays,
  string: TypeIcon,
};

/** Short, human-friendly document reference: the filename if we know it, else the id. */
function shortDoc(candidate: CandidateInfo, filenameById: Record<string, string>): string {
  const name = filenameById[candidate.document_id];
  if (name) return name;
  return candidate.document_id.slice(0, 8);
}

function FieldRow({
  field,
  filenameById,
}: {
  field: CanonicalFieldResult;
  filenameById: Record<string, string>;
}) {
  const { navigateToCanonicalField } = useCaseContext();
  // Conflicts are the point of this screen — default-expand them so the differing
  // candidate values are visible with zero clicks.
  const [open, setOpen] = useState(!field.agreement);
  const KindIcon = KIND_ICON[field.kind] ?? TypeIcon;
  const hasCandidates = field.candidates.length > 0;

  return (
    <>
      <TableRow
        className={cn(
          hasCandidates && "cursor-pointer",
          !field.agreement && "border-review/30 bg-review-muted/30",
        )}
      >
        <TableCell className="align-top">
          <button
            type="button"
            disabled={!hasCandidates}
            onClick={() => hasCandidates && setOpen((v) => !v)}
            className="flex items-start gap-1.5 rounded-sm text-left font-medium focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-default"
            aria-expanded={open}
          >
            {hasCandidates && (
              <ChevronRight
                className={cn(
                  "mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-transform",
                  open && "rotate-90",
                )}
              />
            )}
            <span className={cn(!hasCandidates && "pl-5")}>{field.name}</span>
          </button>
        </TableCell>
        <TableCell className="align-top font-semibold whitespace-normal">
          {formatValue(field.value)}
          {!field.agreement && field.conflict_detail && (
            <div className="mt-0.5 text-xs font-normal text-muted-foreground">
              {field.conflict_detail}
            </div>
          )}
        </TableCell>
        <TableCell className="align-top">
          {field.agreement ? (
            <Badge variant="outline" className="border-approve/40 text-approve">
              <CheckCircle2 className="size-3" />
              agrees across {field.candidates.length} doc
              {field.candidates.length === 1 ? "" : "s"}
            </Badge>
          ) : (
            <Badge
              variant="outline"
              className="border-review/50 text-review-foreground"
            >
              <AlertTriangle className="size-3" />
              Conflict
            </Badge>
          )}
        </TableCell>
        <TableCell className="align-top text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <KindIcon className="size-3.5" />
            {kindLabel(field.kind)}
          </span>
        </TableCell>
      </TableRow>

      {open && hasCandidates && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={4} className="whitespace-normal">
            <div className="space-y-2 py-1">
              <div className="flex flex-wrap gap-1.5">
                {field.candidates.map((c, i) => (
                  <button
                    key={`${c.document_id}-${c.field_path}-${i}`}
                    type="button"
                    onClick={() =>
                      navigateToCanonicalField(
                        c.document_id,
                        c.field_path,
                        c.page ?? undefined,
                      )
                    }
                    className="flex items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5 text-left text-xs transition-colors hover:border-brand/40 hover:bg-brand/[0.03] focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                  >
                    <Badge variant="secondary" className="capitalize">
                      {c.doc_type}
                    </Badge>
                    <span className="font-medium">{formatValue(c.value)}</span>
                    <span className="text-muted-foreground">
                      {shortDoc(c, filenameById)}
                      {c.page != null ? ` · p.${c.page}` : ""}
                    </span>
                    <ConfidencePill value={c.confidence} />
                  </button>
                ))}
              </div>

              {field.citations.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {field.citations.map((cit, i) => (
                    <button
                      key={`${cit.field}-${cit.document_id ?? i}`}
                      type="button"
                      disabled={!cit.document_id}
                      onClick={() =>
                        cit.document_id &&
                        navigateToCanonicalField(cit.document_id, cit.field)
                      }
                      className="rounded-md border bg-muted/40 px-2 py-1 font-mono text-xs transition-colors enabled:hover:border-brand/40 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-default"
                    >
                      {cit.field}{" "}
                      <span className="text-muted-foreground">
                        · {cit.source}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

export function ReconciliationView({
  reconciliation,
  filenameById = {},
}: {
  reconciliation: import("@/lib/types").CaseReconciliation;
  /** documentId → filename, so candidates/citations can show a friendly source. */
  filenameById?: Record<string, string>;
}) {
  if (reconciliation.canonical_fields.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed px-6 py-10 text-center">
        <TypeIcon className="size-6 text-muted-foreground/50" />
        <p className="text-sm font-medium">No canonical fields yet</p>
        <p className="max-w-sm text-xs text-muted-foreground">
          This case has no reconciled fields — an open pile without a case type
          reconciles nothing, and a typed case needs its members extracted first.
        </p>
      </div>
    );
  }

  // Surface conflicts: they're the point of reconciliation, so elevate them to the
  // top (stable within each group so field order is otherwise preserved).
  const rows = [...reconciliation.canonical_fields].sort(
    (a, b) => Number(a.agreement) - Number(b.agreement),
  );

  return (
    <div className="overflow-hidden rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Field</TableHead>
            <TableHead>Value</TableHead>
            <TableHead>Agreement</TableHead>
            <TableHead>Kind</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((field) => (
            <FieldRow
              key={field.name}
              field={field}
              filenameById={filenameById}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
