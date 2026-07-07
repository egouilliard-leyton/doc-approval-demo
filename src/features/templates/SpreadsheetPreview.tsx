// Formula-computed preview of a spreadsheet template filled from a processed
// document. Pick a source document (same doc type, structured/decided — mirrors
// GeneratePanel's doc list), fill + recompute via the backend, and render the
// computed sheets read-only. A banner shows when LibreOffice recompute was
// unavailable (raw formula strings are shown instead). xlsx/PDF export reuses the
// generate endpoint.
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Download, Eye, FileWarning, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ApiError,
  downloadFile,
  generateTemplateOutput,
  listDocuments,
  previewSpreadsheet,
} from "@/lib/api";
import type {
  DocumentSummary,
  SpreadsheetPreviewResponse,
  TemplateDetail,
} from "@/lib/types";
import { SpreadsheetGridTable } from "@/features/templates/SpreadsheetGridTable";

function isEligible(
  doc: DocumentSummary,
  docType: TemplateDetail["doc_type"],
): boolean {
  return (
    doc.doc_type === docType &&
    (doc.status === "structured" || doc.status === "decided")
  );
}

export function SpreadsheetPreview({ template }: { template: TemplateDetail }) {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [preview, setPreview] = useState<SpreadsheetPreviewResponse | null>(null);
  const [activeSheet, setActiveSheet] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const all = await listDocuments();
        if (!cancelled) setDocs(all.filter((d) => isEligible(d, template.doc_type)));
      } catch (e) {
        if (!cancelled)
          toast.error("Could not load documents", {
            description: e instanceof ApiError ? e.message : String(e),
          });
      } finally {
        if (!cancelled) setLoadingDocs(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [template.doc_type]);

  async function handlePreview() {
    if (!selectedId) return;
    setPreviewing(true);
    try {
      const res = await previewSpreadsheet(template.id, selectedId);
      setPreview(res);
      setActiveSheet(res.sheets[0]?.name ?? "");
    } catch (e) {
      toast.error("Preview failed", {
        description: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setPreviewing(false);
    }
  }

  async function handleExport() {
    if (!selectedId) return;
    setExporting(true);
    try {
      const res = await generateTemplateOutput(template.id, { documentId: selectedId });
      const outputs =
        res.outputs.length > 0
          ? res.outputs
          : [{ format: "xlsx", output_id: res.output_id, output_url: res.output_url }];
      for (const out of outputs) {
        await downloadFile(out.output_url, `${out.output_id}.${out.format}`);
      }
      if (res.warnings.length > 0)
        toast.warning("Exported with warnings", {
          description: res.warnings.join("; "),
        });
      else toast.success("Exported");
    } catch (e) {
      toast.error("Export failed", {
        description: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setExporting(false);
    }
  }

  const sheetNames = useMemo(
    () => preview?.sheets.map((s) => s.name) ?? [],
    [preview],
  );
  const activeGrid = useMemo(
    () => preview?.sheets.find((s) => s.name === activeSheet) ?? null,
    [preview, activeSheet],
  );

  if (loadingDocs) {
    return (
      <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading documents…
      </div>
    );
  }

  if (docs.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-center">
        <div className="flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <FileWarning className="size-5" />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-medium">No eligible documents</p>
          <p className="mx-auto max-w-sm text-sm text-muted-foreground text-balance">
            Upload &amp; process a {template.doc_type} first — once it's structured
            you can preview the filled workbook here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] flex-1 space-y-2">
          <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Source document
          </label>
          <Select value={selectedId} onValueChange={setSelectedId}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Pick a processed document…" />
            </SelectTrigger>
            <SelectContent>
              {docs.map((d) => (
                <SelectItem key={d.id} value={d.id}>
                  <span className="truncate">{d.filename}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant="outline"
          disabled={!selectedId || previewing}
          onClick={() => void handlePreview()}
        >
          {previewing ? <Loader2 className="animate-spin" /> : <Eye />}
          Preview
        </Button>
        <Button
          disabled={!selectedId || exporting}
          onClick={() => void handleExport()}
        >
          {exporting ? <Loader2 className="animate-spin" /> : <Download />}
          Export
        </Button>
      </div>

      {preview && !preview.computed && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            Formulas were not computed (LibreOffice unavailable) — cells show their
            raw formula. The exported file still recomputes in Excel.
          </span>
        </div>
      )}

      {preview && (
        <div className="min-h-[20rem]">
          <SpreadsheetGridTable
            grid={activeGrid}
            sheetNames={sheetNames}
            activeSheet={activeSheet}
            onSheetChange={setActiveSheet}
          />
        </div>
      )}
    </div>
  );
}
