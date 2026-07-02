// The case → single-document drill-down seam. The whole single-document inspector
// stack (SplitInspector/PageViewer/GridViewer/highlights) is reused UNMODIFIED by
// mounting a SECOND, independently-keyed PipelineProvider around it. That nested
// provider owns its own usePipeline instance, so opening a member document here never
// disturbs the app's top-level pipeline (the Workspace). `key={documentId}` forces a
// clean remount per navigation so no stale page/highlight state leaks across members.
import { createElement, useEffect, useRef } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import {
  PipelineProvider,
  usePipelineContext,
} from "@/features/pipeline/PipelineContext";
import { SplitInspector } from "@/features/inspector/SplitInspector";
import { useCaseContext } from "@/features/case/CaseContext";

function CaseMemberDrilldownInner({
  documentId,
  focusField,
  focusPage,
  onClose,
}: {
  documentId: string;
  focusField?: string;
  focusPage?: number;
  onClose: () => void;
}) {
  // Resolves to the NEAREST provider — the nested one mounted just below. This is the
  // existing rehydration path: openDocument fetches the document + its persisted stage
  // results into this isolated pipeline instance.
  const { document, openDocument } = usePipelineContext();

  // Fetch the document exactly once per mount. `key={activeDocId}` on the PipelineProvider
  // forces a fresh mount per document, so a mount-only effect is correct — and a guard is
  // needed because openDocument's identity changes after HYDRATE mutates docType/engine,
  // which would otherwise re-fire this effect and re-fetch everything.
  const openedRef = useRef(false);
  useEffect(() => {
    if (openedRef.current) return;
    openedRef.current = true;
    void openDocument(documentId);
  }, [documentId, openDocument]);

  const docIcon = resolveDocTypeIcon(document?.doc_type ?? null);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg border bg-card text-muted-foreground">
            {createElement(docIcon, { className: "size-4.5" })}
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-medium">
              {document?.filename ?? "Loading document…"}
              {focusField && (
                <span className="ml-2 font-mono text-xs font-normal text-brand">
                  · {focusField}
                </span>
              )}
            </h3>
            <p className="text-xs text-muted-foreground">
              {document?.doc_type ? (
                <span className="capitalize">{document.doc_type}</span>
              ) : (
                "Member document"
              )}
              {focusField && " — jumping to field"}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onClose}>
          <X className="size-4" />
          Close
        </Button>
      </div>

      <SplitInspector focus={{ field: focusField, page: focusPage }} />
    </div>
  );
}

/**
 * Overlay drill-down for the active case member. Reads the active document + focus
 * from the case context; renders nothing when no member is open.
 */
export function CaseMemberDrilldown() {
  const { activeDocId, focus, closeDrilldown } = useCaseContext();
  if (!activeDocId) return null;
  const focused = focus?.documentId === activeDocId ? focus : null;

  // A real modal: the Dialog primitive brings Escape-to-close, focus trap, focus
  // restoration, and aria-modal for free. It portals, so the CaseOverview underneath
  // stays mounted. Near-fullscreen (mirrors the AI wizard) so the inspector has room.
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) closeDrilldown();
      }}
    >
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        className="flex h-[92vh] w-[96vw] max-w-[calc(100%-2rem)] flex-col gap-0 overflow-hidden p-5 sm:max-w-[1700px]"
      >
        <DialogTitle className="sr-only">Member document</DialogTitle>
        {/* key={activeDocId} forces a clean remount (fresh nested pipeline) per member. */}
        <PipelineProvider key={activeDocId}>
          <CaseMemberDrilldownInner
            documentId={activeDocId}
            focusField={focused?.field}
            focusPage={focused?.page}
            onClose={closeDrilldown}
          />
        </PipelineProvider>
      </DialogContent>
    </Dialog>
  );
}
