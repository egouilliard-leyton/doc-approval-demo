// Admin corrections: reviewer edits across all documents, grouped by document so
// the list stays scannable. Two lenses on the same data: an accordion (drill in per
// doc) and a master–detail split (browse docs left, edits right).
import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  ChevronRight,
  Download,
  ExternalLink,
  PencilLine,
} from "lucide-react";
import {
  ApiError,
  correctionsExportUrl,
  listCorrections,
  listDocuments,
} from "@/lib/api";
import { humanize } from "@/lib/fields";
import { cn } from "@/lib/utils";
import { DOC_STATUS_LABEL, docStatusClass } from "@/lib/doc-status";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  DocumentStatus,
  DocumentSummary,
  FieldCorrection,
} from "@/lib/types";

interface DocGroup {
  docId: string;
  filename: string;
  status: DocumentStatus | null;
  items: FieldCorrection[];
}

function display(v: string | number | boolean | null): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

function StatusBadge({ status }: { status: DocumentStatus | null }) {
  if (!status) return null;
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[10px] font-medium",
        docStatusClass(status),
      )}
    >
      {DOC_STATUS_LABEL[status]}
    </span>
  );
}

function DiffRow({ c }: { c: FieldCorrection }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2 hover:bg-muted/50">
      <span className="text-sm text-muted-foreground">
        {humanize(c.field_path.replace(/\./g, " "))}
      </span>
      <div className="flex items-center gap-2 font-mono text-xs">
        <span className="rounded bg-flag/10 px-1.5 py-0.5 text-flag line-through">
          {display(c.original_value)}
        </span>
        <ArrowRight className="size-3 text-muted-foreground" />
        <span className="rounded bg-approve/10 px-1.5 py-0.5 font-medium text-approve">
          {display(c.new_value)}
        </span>
      </div>
    </div>
  );
}

function OpenButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <ExternalLink className="size-3.5" /> Open
    </button>
  );
}

// --- accordion lens ----------------------------------------------------------

function AccordionView({
  groups,
  onOpenDocument,
}: {
  groups: DocGroup[];
  onOpenDocument: (id: string) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-2">
      {groups.map((g) => {
        const expanded = open.has(g.docId);
        return (
          <div key={g.docId} className="overflow-hidden rounded-xl border">
            <button
              type="button"
              onClick={() => toggle(g.docId)}
              className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50"
            >
              <ChevronRight
                className={cn(
                  "size-4 shrink-0 text-muted-foreground transition-transform",
                  expanded && "rotate-90",
                )}
              />
              <span className="min-w-0 flex-1 truncate font-medium">
                {g.filename}
              </span>
              <StatusBadge status={g.status} />
              <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                {g.items.length} edit{g.items.length === 1 ? "" : "s"}
              </span>
              <OpenButton onClick={() => onOpenDocument(g.docId)} />
            </button>
            {expanded && (
              <div className="border-t bg-muted/20 p-1">
                {g.items.map((c) => (
                  <DiffRow key={c.field_path} c={c} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// --- master–detail lens ------------------------------------------------------

function MasterDetailView({
  groups,
  onOpenDocument,
}: {
  groups: DocGroup[];
  onOpenDocument: (id: string) => void;
}) {
  const [selected, setSelected] = useState<string>(groups[0]?.docId ?? "");
  const active = groups.find((g) => g.docId === selected) ?? groups[0];

  return (
    <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_1fr]">
      {/* Master: documents with edits */}
      <div className="max-h-[60vh] space-y-1 overflow-y-auto rounded-xl border p-1">
        {groups.map((g) => (
          <button
            key={g.docId}
            type="button"
            onClick={() => setSelected(g.docId)}
            className={cn(
              "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors",
              g.docId === active?.docId
                ? "bg-brand/10 text-brand"
                : "hover:bg-muted",
            )}
          >
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {g.filename}
            </span>
            <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground">
              {g.items.length}
            </span>
          </button>
        ))}
      </div>

      {/* Detail: selected document's corrections */}
      <div className="rounded-xl border">
        {active && (
          <>
            <div className="flex items-center gap-2 border-b px-3 py-2.5">
              <span className="min-w-0 flex-1 truncate font-medium">
                {active.filename}
              </span>
              <StatusBadge status={active.status} />
              <OpenButton onClick={() => onOpenDocument(active.docId)} />
            </div>
            <div className="p-1">
              {active.items.map((c) => (
                <DiffRow key={c.field_path} c={c} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// --- export affordance -------------------------------------------------------

// Downloads the corrections as JSONL. The doc-type filter is derived from the
// already-loaded rows (no extra fetch); "all" omits the doc_type param.
function ExportControls({ docTypes }: { docTypes: string[] }) {
  const [docType, setDocType] = useState<string>("all");
  const scope = docType === "all" ? {} : { docType };

  return (
    <div className="flex items-center gap-1.5">
      <Select value={docType} onValueChange={setDocType}>
        <SelectTrigger size="sm" aria-label="Filter export by document type">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All types</SelectItem>
          {docTypes.map((t) => (
            <SelectItem key={t} value={t}>
              {humanize(t)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button asChild variant="outline" size="sm">
        <a href={correctionsExportUrl({ ...scope, shape: "raw" })} download>
          <Download /> Raw JSONL
        </a>
      </Button>
      <Button asChild variant="outline" size="sm">
        <a href={correctionsExportUrl({ ...scope, shape: "examples" })} download>
          <Download /> Labeled examples JSONL
        </a>
      </Button>
    </div>
  );
}

export function CorrectionsSection({
  onOpenDocument,
}: {
  onOpenDocument: (id: string) => void;
}) {
  const [rows, setRows] = useState<FieldCorrection[] | null>(null);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [c, d] = await Promise.all([listCorrections(), listDocuments()]);
        if (cancelled) return;
        setRows(c);
        setDocs(d);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "Could not load corrections.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo<DocGroup[]>(() => {
    if (!rows) return [];
    const byDoc = new Map<string, FieldCorrection[]>();
    for (const c of rows) {
      const arr = byDoc.get(c.document_id) ?? [];
      arr.push(c);
      byDoc.set(c.document_id, arr);
    }
    const nameById = new Map(docs.map((d) => [d.id, d]));
    return Array.from(byDoc.entries())
      .map(([docId, items]) => ({
        docId,
        filename: nameById.get(docId)?.filename ?? docId,
        status: nameById.get(docId)?.status ?? null,
        items,
      }))
      .sort((a, b) => b.items.length - a.items.length); // worst extractions first
  }, [rows, docs]);

  // Unique doc types present in the loaded corrections, for the export filter.
  const docTypes = useMemo(
    () =>
      Array.from(
        new Set((rows ?? []).map((c) => c.doc_type).filter(Boolean)),
      ).sort(),
    [rows],
  );

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!rows) return <Skeleton className="h-64 w-full rounded-xl" />;
  if (groups.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
        No corrections yet. Edited fields will show up here.
      </div>
    );
  }

  const totalEdits = rows.length;

  return (
    <Tabs defaultValue="grouped" className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <TabsList>
          <TabsTrigger value="grouped">Grouped</TabsTrigger>
          <TabsTrigger value="split">Master–detail</TabsTrigger>
        </TabsList>
        <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <PencilLine className="size-3.5" />
            {totalEdits} edit{totalEdits === 1 ? "" : "s"} across {groups.length}{" "}
            document{groups.length === 1 ? "" : "s"}
          </span>
          <ExportControls docTypes={docTypes} />
        </div>
      </div>

      <TabsContent value="grouped">
        <AccordionView groups={groups} onOpenDocument={onOpenDocument} />
      </TabsContent>
      <TabsContent value="split">
        <MasterDetailView groups={groups} onOpenDocument={onOpenDocument} />
      </TabsContent>
    </Tabs>
  );
}
