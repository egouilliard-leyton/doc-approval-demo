// Detail view for a single template. Fetches the template on mount and shows
// its identity. Form-fill templates get the full authoring flow (upload → map →
// generate); rich-HTML templates still show a "later phase" placeholder.
import { useEffect, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError, getTemplate } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type {
  TemplateDetail as TemplateDetailData,
  TemplateStatus,
} from "@/lib/types";
import { FormFillPanel } from "@/features/templates/FormFillPanel";

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
          <span className="text-xs text-muted-foreground">
            Updated {formatDate(template.updated_at)}
          </span>
        </div>
      </div>

      {template.mode === "form_fill" ? (
        <FormFillPanel template={template} onChange={setTemplate} />
      ) : (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            The rich-HTML template editor arrives in a later phase.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
