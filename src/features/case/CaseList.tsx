// The case list — the home of the Cases tab. Lists persisted cases (label, type,
// created) with a prominent "New case" CTA, a per-row delete (confirmation-gated), and
// an "open for viewing" action that fetches the case + its reconciliation/decision into
// a read-only overview (a full live "resume" of orchestration is out of scope). Real
// empty/loading/error states keep the screen legible at every moment.
import { useCallback, useMemo, useState } from "react";
import {
  Plus,
  Trash2,
  Loader2,
  FolderKanban,
  FolderOpen,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
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
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import { DOC_STATUS_LABEL, docStatusClass } from "@/lib/doc-status";
import {
  CASE_DECISION_LABEL,
  caseDecisionClass,
} from "@/lib/case-status";
import {
  ApiError,
  deleteCase,
  getCase,
  getCaseDecision,
  getCaseReconciliation,
} from "@/lib/api";
import type {
  CaseDecisionResult,
  CaseDetail,
  CaseReconciliation,
} from "@/lib/types";
import { useCases } from "@/features/case/useCases";
import { useCaseContext } from "@/features/case/CaseContext";
import { CaseStageHeader } from "@/features/case/CaseStageHeader";
import { ReconciliationView } from "@/features/case/ReconciliationView";
import { CaseDecisionPanel } from "@/features/case/CaseDecisionPanel";
import { CaseMemberDrilldown } from "@/features/case/CaseMemberDrilldown";

interface ReadView {
  detail: CaseDetail;
  reconciliation: CaseReconciliation | null;
  decision: CaseDecisionResult | null;
}

/** Read-only overview of a persisted case (no live orchestration). */
function CaseReadView({
  view,
  onBack,
}: {
  view: ReadView;
  onBack: () => void;
}) {
  const { openMember } = useCaseContext();
  const { detail, reconciliation, decision } = view;

  const filenameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const m of detail.members) map[m.document_id] = m.filename;
    return map;
  }, [detail]);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <CaseStageHeader
        stage="overview"
        caseLabel={detail.label}
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

      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight">
          {detail.label || "Untitled case"}
        </h2>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {detail.case_type ? (
            <Badge variant="secondary" className="capitalize">
              {detail.case_type}
            </Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground">
              Open pile
            </Badge>
          )}
          <span>
            {detail.members.length} document
            {detail.members.length === 1 ? "" : "s"}
          </span>
        </div>
      </div>

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
              {detail.members.map((m) => {
                const Icon = resolveDocTypeIcon(m.doc_type);
                return (
                  <TableRow key={m.document_id}>
                    <TableCell className="max-w-[16rem]">
                      <span className="flex items-center gap-2">
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate" title={m.filename}>
                          {m.filename}
                        </span>
                      </span>
                    </TableCell>
                    <TableCell>
                      {m.doc_type ? (
                        <Badge variant="secondary" className="capitalize">
                          {m.doc_type}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={docStatusClass(m.status)}
                      >
                        {DOC_STATUS_LABEL[m.status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openMember(m.document_id)}
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

      {reconciliation && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Reconciled fields
          </h3>
          <ReconciliationView
            reconciliation={reconciliation}
            filenameById={filenameById}
          />
        </section>
      )}

      {decision && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Decision
          </h3>
          <CaseDecisionPanel decision={decision} />
        </section>
      )}

      <CaseMemberDrilldown />
    </div>
  );
}

export function CaseList({ onNewCase }: { onNewCase: () => void }) {
  const { cases, loading, error, refetch } = useCases();
  const [view, setView] = useState<ReadView | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [deletingIds, setDeletingIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  const openCase = useCallback(async (id: string) => {
    setOpeningId(id);
    try {
      const detail = await getCase(id);
      // Reconciliation/decision may not exist yet (404) — tolerate and show what we have.
      const [reconciliation, decision] = await Promise.all([
        getCaseReconciliation(id).catch(() => null),
        getCaseDecision(id).catch(() => null),
      ]);
      setView({ detail, reconciliation, decision });
    } catch (e) {
      toast.error("Could not open case", {
        description: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setOpeningId(null);
    }
  }, []);

  const handleDelete = useCallback(
    async (id: string) => {
      setDeletingIds((prev) => new Set(prev).add(id));
      try {
        await deleteCase(id);
        toast.success("Case deleted");
        refetch();
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          refetch();
        } else {
          toast.error("Delete failed", {
            description: e instanceof ApiError ? e.message : String(e),
          });
        }
      } finally {
        setDeletingIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    },
    [refetch],
  );

  if (view) {
    return <CaseReadView view={view} onBack={() => setView(null)} />;
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">Cases</h2>
          <p className="text-sm text-muted-foreground">
            Group related documents, reconcile their shared fields, and decide
            the whole case at once.
          </p>
        </div>
        <Button onClick={onNewCase}>
          <Plus className="size-4" />
          New case
        </Button>
      </div>

      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full rounded-lg" />
          <Skeleton className="h-12 w-full rounded-lg" />
          <Skeleton className="h-12 w-full rounded-lg" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">
          {error}{" "}
          <button
            type="button"
            onClick={refetch}
            className="rounded-sm font-medium text-brand hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            Retry
          </button>
        </div>
      ) : cases.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-16 text-center">
          <div className="flex size-12 items-center justify-center rounded-full border bg-muted/40 text-muted-foreground">
            <FolderOpen className="size-6" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium">No cases yet</p>
            <p className="max-w-sm text-xs text-muted-foreground">
              A case bundles related documents — an invoice with its contract, a
              claim with its receipts — so their shared fields can be reconciled
              and decided together.
            </p>
          </div>
          <Button onClick={onNewCase}>
            <Plus className="size-4" />
            New case
          </Button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {cases.map((c) => {
                const deleting = deletingIds.has(c.id);
                const opening = openingId === c.id;
                return (
                  <TableRow key={c.id}>
                    <TableCell>
                      <button
                        type="button"
                        onClick={() => void openCase(c.id)}
                        disabled={opening || deleting}
                        className="flex items-center gap-2 rounded-sm text-left font-medium transition-colors hover:text-brand focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-60"
                      >
                        <FolderKanban className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">
                          {c.label || "Untitled case"}
                        </span>
                      </button>
                    </TableCell>
                    <TableCell>
                      {c.case_type ? (
                        <Badge variant="secondary" className="capitalize">
                          {c.case_type}
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="text-muted-foreground"
                        >
                          Open pile
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(c.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void openCase(c.id)}
                          disabled={opening || deleting}
                        >
                          {opening ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : (
                            <ExternalLink className="size-3.5" />
                          )}
                          Open
                        </Button>
                        <AlertDialog>
                          <AlertDialogTrigger
                            aria-label={`Delete ${c.label || "case"}`}
                            disabled={deleting}
                            className={cn(
                              "inline-flex size-7 items-center justify-center rounded-lg text-muted-foreground transition-all",
                              "hover:bg-destructive/10 hover:text-destructive focus-visible:ring-3 focus-visible:ring-destructive/20 focus-visible:outline-none",
                              deleting && "pointer-events-none opacity-50",
                            )}
                          >
                            {deleting ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <Trash2 className="size-4" />
                            )}
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>
                                Delete this case?
                              </AlertDialogTitle>
                              <AlertDialogDescription>
                                <span className="font-medium text-foreground">
                                  {c.label || "This case"}
                                </span>{" "}
                                will be removed. Its documents are not deleted —
                                only their grouping into this case. This can't be
                                undone.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction
                                className="bg-destructive text-white hover:bg-destructive/90"
                                onClick={() => void handleDelete(c.id)}
                              >
                                Delete
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
