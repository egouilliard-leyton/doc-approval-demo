// Corrections activity view: every reviewer edit as original → final, alongside the
// document with the selected edit's source box highlighted (where it was extracted).
import { useState } from "react";
import { ArrowRight } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { buildFieldTree, displayValue, flattenLeaves } from "@/lib/fields";
import type { Highlights } from "@/lib/highlights";
import { PageViewer } from "@/features/inspector/PageViewer";
import { GridViewer } from "@/features/inspector/GridViewer";
import type { PageInfo, StructuredResult } from "@/lib/types";

export function CorrectionsDialog({
  open,
  onClose,
  pages,
  structure,
  highlights,
  spreadsheet = false,
}: {
  open: boolean;
  onClose: () => void;
  pages: PageInfo[];
  structure: StructuredResult | null;
  highlights: Highlights;
  /** Render the source pane as a grid (CSV/XLSX) instead of a page image. */
  spreadsheet?: boolean;
}) {
  const edits = structure
    ? flattenLeaves(buildFieldTree(structure.fields)).filter((l) => l.fv.edited)
    : [];

  const [selected, setSelected] = useState<string | null>(edits[0]?.path ?? null);
  const [page, setPage] = useState<number>(1);
  const [flashTick, setFlashTick] = useState(0);

  const select = (path: string) => {
    setSelected(path);
    const p = highlights.pageByPath[path];
    if (p) setPage(p);
    setFlashTick((t) => t + 1);
  };

  const selectedKey = selected
    ? (highlights.regionKeyByPath[selected] ?? null)
    : null;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] gap-4 sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>Corrections</DialogTitle>
          <DialogDescription>
            Fields a reviewer changed — likely extraction errors. Click one to see
            where it was read from on the document.
          </DialogDescription>
        </DialogHeader>

        {edits.length === 0 ? (
          <div className="flex h-40 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
            No edits yet.
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Document with the selected edit's source box / cell */}
            <div className="min-h-0 min-w-0">
              {spreadsheet && structure ? (
                <GridViewer
                  docId={structure.document_id}
                  page={page}
                  regions={highlights.regions}
                  selectedKey={selectedKey}
                  hoveredKey={null}
                  flashTick={flashTick}
                  onPageChange={setPage}
                />
              ) : (
                <PageViewer
                  pages={pages}
                  page={page}
                  regions={highlights.regions}
                  selectedKey={selectedKey}
                  hoveredKey={null}
                  flashTick={flashTick}
                  onPageChange={setPage}
                />
              )}
            </div>

            {/* Edit list: original -> final */}
            <div className="min-w-0 space-y-2 overflow-y-auto pr-1">
              {edits.map((leaf) => {
                const color = highlights.colorByPath[leaf.path];
                const active = selected === leaf.path;
                return (
                  <button
                    key={leaf.path}
                    type="button"
                    onClick={() => select(leaf.path)}
                    style={active ? { boxShadow: `inset 3px 0 0 0 ${color}` } : undefined}
                    className={cn(
                      "w-full rounded-xl border p-3 text-left transition-colors",
                      active ? "bg-muted/70" : "hover:bg-muted/40",
                    )}
                  >
                    <div className="mb-1.5 flex items-center gap-2">
                      <span
                        className="size-2.5 shrink-0 rounded-[3px]"
                        style={{
                          backgroundColor:
                            color ?? "var(--color-muted-foreground)",
                        }}
                      />
                      <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                        {leaf.label}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 font-mono text-sm">
                      <span className="rounded bg-flag/10 px-1.5 py-0.5 text-flag line-through">
                        {displayValue(leaf.fv.original_value ?? null)}
                      </span>
                      <ArrowRight className="size-3.5 text-muted-foreground" />
                      <span className="rounded bg-approve/10 px-1.5 py-0.5 font-medium text-approve">
                        {displayValue(leaf.fv.value)}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
