// Detail view for a single template. Fetches the template on mount and shows
// its identity. Form-fill templates get the full authoring flow (upload → map →
// generate); rich-HTML templates still show a "later phase" placeholder.
import { lazy, Suspense, useEffect, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ApiError, getTemplate } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type {
  TemplateDetail as TemplateDetailData,
  TemplateStatus,
} from "@/lib/types";
import { FormFillPanel } from "@/features/templates/FormFillPanel";

// Lazy-loaded so TipTap (and its ProseMirror deps) only ship when a rich-HTML
// template is actually opened, keeping the main bundle lean.
const RichHtmlPanel = lazy(() =>
  import("@/features/templates/RichHtmlPanel").then((m) => ({
    default: m.RichHtmlPanel,
  })),
);

const LOAD_ERROR = "Could not load this template.";

const MODE_LABEL = {
  form_fill: "Form-fill",
  rich_html: "Rich HTML",
} as const;

function statusBadgeClass(status: TemplateStatus): string {
  return status === "ready"
    ? "border-approve/40 text-approve"
    : "border-border text-muted-foreground";
}

function BackLink() {
  return (
    <a
      href="#/templates"
      className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft className="size-4" />
      Back to templates
    </a>
  );
}

export function TemplateDetail({ id }: { id: string }) {
  const [template, setTemplate] = useState<TemplateDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getTemplate(id);
        if (!cancelled) setTemplate(data);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : LOAD_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="mx-auto flex w-full max-w-5xl items-center justify-center gap-2 px-6 py-16 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading template…
      </div>
    );
  }

  if (error || !template) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col items-center gap-4 px-6 py-16 text-center">
        <p className="text-sm text-muted-foreground">
          {error ?? "Template not found."}
        </p>
        <BackLink />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-10">
      <BackLink />

      <div className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          {template.name}
        </h1>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary" className="capitalize">
            {template.doc_type}
          </Badge>
          <Badge variant="outline">{MODE_LABEL[template.mode]}</Badge>
          <Badge
            variant="outline"
            className={cn(statusBadgeClass(template.status))}
          >
            {template.status === "ready" ? "Ready" : "Draft"}
          </Badge>
          {template.lint.orphaned_paths.length > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge
                  variant="outline"
                  className="border-review/40 text-review"
                >
                  ⚠ {template.lint.orphaned_paths.length} placeholder
                  {template.lint.orphaned_paths.length === 1 ? "" : "s"} reference
                  removed fields
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <div className="space-y-1">
                  <p className="font-medium">Orphaned placeholders</p>
                  <ul className="space-y-0.5 font-mono">
                    {template.lint.orphaned_paths.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </div>
              </TooltipContent>
            </Tooltip>
          )}
          <span className="text-xs text-muted-foreground">
            Updated {formatDate(template.updated_at)}
          </span>
        </div>
      </div>

      {template.mode === "form_fill" ? (
        <FormFillPanel template={template} onChange={setTemplate} />
      ) : (
        <Suspense
          fallback={
            <div className="space-y-4">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-96 w-full" />
            </div>
          }
        >
          <RichHtmlPanel template={template} onChange={setTemplate} />
        </Suspense>
      )}
    </div>
  );
}
