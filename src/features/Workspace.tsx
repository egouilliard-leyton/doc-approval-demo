import { createElement, useState } from "react";
import { ChevronDown, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import { usePipelineContext } from "@/features/pipeline/PipelineContext";
import { useRouteContext } from "@/features/routing/RouteContext";
import { CopyLinkButton } from "@/features/routing/CopyLinkButton";
import { Stepper } from "@/features/pipeline/Stepper";
import { QualityReportPanel } from "@/features/pipeline/QualityReportPanel";
import { SplitInspector } from "@/features/inspector/SplitInspector";

export function Workspace() {
  const { document, prescan, reset } = usePipelineContext();
  const { route, navigate } = useRouteContext();
  const [showPrescan, setShowPrescan] = useState(false);

  if (!document) return null;
  const docIcon = resolveDocTypeIcon(document.doc_type);

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col gap-4 px-4 py-5 sm:px-6">
      {/* Document header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-lg border bg-card text-muted-foreground">
            {createElement(docIcon, { className: "size-5" })}
          </div>
          <div>
            <h2 className="text-sm font-medium">{document.filename}</h2>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {document.doc_type && (
                <Badge variant="secondary" className="capitalize">
                  {document.doc_type}
                </Badge>
              )}
              <span className="font-mono">
                {document.page_count} page{document.page_count > 1 ? "s" : ""}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <CopyLinkButton />
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              reset();
              // replace (not push) so the route update batches synchronously with
              // reset() — one render straight to the upload screen, no LoadingDocument
              // flash — and "start over" doesn't leave a dead doc entry in history.
              navigate({ view: "workspace" }, { replace: true });
            }}
          >
            <Plus className="size-4" />
            New document
          </Button>
        </div>
      </div>

      {/* Stepper */}
      <Stepper />

      {/* Pre-scan quality report (collapsible) */}
      {prescan && (
        <div className="rounded-xl border bg-card">
          <button
            onClick={() => setShowPrescan((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-sm"
          >
            <span className="flex items-center gap-2 font-medium">
              Pre-scan quality
              <Badge
                variant="outline"
                className={cn(
                  prescan.verdict === "warn"
                    ? "border-review/50 text-review-foreground"
                    : "border-approve/50 text-approve",
                )}
              >
                {prescan.verdict}
              </Badge>
            </span>
            <ChevronDown
              className={cn(
                "size-4 text-muted-foreground transition-transform",
                showPrescan && "rotate-180",
              )}
            />
          </button>
          {showPrescan && (
            <div className="border-t p-4">
              <QualityReportPanel report={prescan} />
            </div>
          )}
        </div>
      )}

      {/* Split inspector */}
      <SplitInspector
        tab={route.view === "document" ? route.tab : "structured"}
        onTabChange={(t) =>
          navigate({
            view: "document",
            id: document.id,
            tab: t,
            field: undefined,
          })
        }
        focus={
          route.view === "document" && route.field
            ? { field: route.field }
            : undefined
        }
      />
    </div>
  );
}
