// Admin documents: status filter chips (with counts) + search + pagination, so the
// table stays scannable no matter how many documents accumulate. Row → open in workspace.
import { useEffect, useMemo, useState } from "react";
import { Search, ChevronLeft, ChevronRight } from "lucide-react";
import { ApiError, listDocuments } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { DOC_STATUS_LABEL, DOC_STATUS_ORDER, docStatusClass } from "@/lib/doc-status";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import type { DocumentStatus, DocumentSummary } from "@/lib/types";

const PAGE_SIZE = 8;

export function DocumentsSection({
  onOpenDocument,
}: {
  onOpenDocument: (id: string) => void;
}) {
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<DocumentStatus | "all">("all");
  const [page, setPage] = useState(1);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const d = await listDocuments();
        if (!cancelled) setDocs(d);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "Could not load documents.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Counts per status for the filter chips.
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const d of docs ?? []) c[d.status] = (c[d.status] ?? 0) + 1;
    return c;
  }, [docs]);

  const filtered = useMemo(() => {
    let list = docs ?? [];
    if (status !== "all") list = list.filter((d) => d.status === status);
    const term = q.trim().toLowerCase();
    if (term)
      list = list.filter((d) =>
        `${d.filename} ${d.doc_type ?? ""}`.toLowerCase().includes(term),
      );
    return list;
  }, [docs, status, q]);

  // Keep the page valid as filters change.
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const shown = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  const setFilter = (s: DocumentStatus | "all") => {
    setStatus(s);
    setPage(1);
  };

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!docs) return <Skeleton className="h-64 w-full rounded-xl" />;

  const chips: { id: DocumentStatus | "all"; label: string; n: number }[] = [
    { id: "all", label: "All", n: docs.length },
    ...DOC_STATUS_ORDER.filter((s) => counts[s]).map((s) => ({
      id: s,
      label: DOC_STATUS_LABEL[s],
      n: counts[s],
    })),
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {chips.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => setFilter(c.id)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
              status === c.id
                ? "border-brand bg-brand/10 text-brand"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            {c.label}{" "}
            <span className="tabular-nums opacity-70">{c.n}</span>
          </button>
        ))}
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
          placeholder="Search documents…"
          className="pl-8"
        />
      </div>

      <div className="overflow-x-auto rounded-xl border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Document</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Pages</TableHead>
              <TableHead className="text-right">Added</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  No documents match.
                </TableCell>
              </TableRow>
            ) : (
              shown.map((d) => {
                const Icon = resolveDocTypeIcon(d.doc_type);
                return (
                  <TableRow
                    key={d.id}
                    onClick={() => onOpenDocument(d.id)}
                    className="cursor-pointer"
                  >
                    <TableCell className="max-w-64">
                      <div className="flex items-center gap-2">
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate font-medium">{d.filename}</span>
                      </div>
                    </TableCell>
                    <TableCell className="capitalize text-muted-foreground">
                      {d.doc_type ?? "—"}
                    </TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-xs font-medium",
                          docStatusClass(d.status),
                        )}
                      >
                        {DOC_STATUS_LABEL[d.status]}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {d.page_count}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      {formatDate(d.created_at)}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {filtered.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {(current - 1) * PAGE_SIZE + 1}–
            {Math.min(current * PAGE_SIZE, filtered.length)} of {filtered.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={current <= 1}
              onClick={() => setPage(current - 1)}
              className="flex items-center gap-1 rounded-md border px-2 py-1 disabled:opacity-40 enabled:hover:bg-muted"
            >
              <ChevronLeft className="size-3.5" /> Prev
            </button>
            <span className="tabular-nums">
              {current} / {pageCount}
            </span>
            <button
              type="button"
              disabled={current >= pageCount}
              onClick={() => setPage(current + 1)}
              className="flex items-center gap-1 rounded-md border px-2 py-1 disabled:opacity-40 enabled:hover:bg-muted"
            >
              Next <ChevronRight className="size-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
