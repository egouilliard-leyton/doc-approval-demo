// Top-level Templates section. Self-fetches the template list, groups it by
// doc type, and routes to a single-template view when the hash carries an id.
// Mirrors DocumentLibrary's load/delete shape and card affordances.
import { useCallback, useEffect, useState } from "react";
import { FilePlus2, Loader2, Trash2 } from "lucide-react";
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
import { ApiError, deleteTemplate, listTemplates } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { routeToHash } from "@/lib/route";
import { cn } from "@/lib/utils";
import type {
  DocType,
  TemplateDetail,
  TemplateStatus,
  TemplateSummary,
} from "@/lib/types";
import { useHashRoute } from "@/hooks/useHashRoute";
import { TemplateDetailStub } from "@/features/templates/TemplateDetailStub";
import { TemplateWizard } from "@/features/templates/TemplateWizard";

const LOAD_ERROR = "Could not load templates.";

const MODE_LABEL = {
  form_fill: "Form-fill",
  rich_html: "Rich HTML",
} as const;

// Order sections predictably even when only one doc type is present.
const DOC_TYPE_ORDER: DocType[] = ["invoice", "contract"];

// Borrow the approve token for a ready template so it reads green; a draft stays
// muted/outline.
function statusBadgeClass(status: TemplateStatus): string {
  return status === "ready"
    ? "border-approve/40 text-approve"
    : "border-border text-muted-foreground";
}

function TemplateCard({
  template,
  onDelete,
  deleting,
}: {
  template: TemplateSummary;
  onDelete: (id: string) => void;
  deleting: boolean;
}) {
  const open = () => {
    window.location.hash = routeToHash({
      view: "templates",
      id: template.id,
    });
  };

  return (
    <div className="group/tpl relative">
      <button
        type="button"
        onClick={open}
        disabled={deleting}
        className={cn(
          "flex w-full flex-col gap-3 rounded-xl bg-card p-4 text-left ring-1 ring-foreground/10 transition-all",
          "hover:ring-brand/40 hover:shadow-sm focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
          deleting && "pointer-events-none opacity-50",
        )}
      >
        <span
          className="truncate pr-7 text-sm font-medium"
          title={template.name}
        >
          {template.name}
        </span>
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
        </div>
        <span className="text-xs text-muted-foreground">
          {formatDate(template.updated_at)}
        </span>
      </button>

      {/* Delete — confirmation gated. */}
      <AlertDialog>
        <AlertDialogTrigger
          aria-label={`Delete ${template.name}`}
          disabled={deleting}
          className={cn(
            "absolute top-2 right-2 z-10 flex size-7 items-center justify-center rounded-lg bg-background/80 text-muted-foreground backdrop-blur transition-all",
            "hover:bg-destructive/10 hover:text-destructive focus-visible:ring-3 focus-visible:ring-destructive/20 focus-visible:outline-none",
            "opacity-0 group-hover/tpl:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100",
            deleting && "pointer-events-none",
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
            <AlertDialogTitle>Delete this template?</AlertDialogTitle>
            <AlertDialogDescription>
              <span className="font-medium text-foreground">
                {template.name}
              </span>{" "}
              will be permanently removed. This can't be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={() => onDelete(template.id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function TemplateList() {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  // A set, not a single id: deletes are independent and can overlap.
  const [deletingIds, setDeletingIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTemplates(await listTemplates());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : LOAD_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await listTemplates();
        if (!cancelled) setTemplates(data);
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
  }, []);

  const handleCreated = useCallback((t: TemplateDetail) => {
    setWizardOpen(false);
    setTemplates((prev) => [t, ...prev]);
    toast.success("Template created");
  }, []);

  const handleDelete = useCallback(
    async (id: string) => {
      setDeletingIds((prev) => new Set(prev).add(id));
      try {
        await deleteTemplate(id);
        setTemplates((prev) => prev.filter((t) => t.id !== id));
        toast.success("Template deleted");
      } catch (e) {
        // Already gone (e.g. a concurrent delete won): treat as success.
        if (e instanceof ApiError && e.status === 404) {
          setTemplates((prev) => prev.filter((t) => t.id !== id));
        } else {
          const msg =
            e instanceof ApiError ? e.message : "Could not delete template.";
          toast.error("Delete failed", { description: msg });
          void load(); // resync in case the server state diverged
        }
      } finally {
        setDeletingIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    },
    [load],
  );

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-10">
      <div className="flex items-center justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Templates</h1>
          <p className="text-sm text-muted-foreground">
            Reusable layouts for generating invoices and contracts.
          </p>
        </div>
        <Button onClick={() => setWizardOpen(true)}>
          <FilePlus2 />
          New template
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading templates…
        </div>
      ) : error ? (
        <div className="py-16 text-center text-sm text-muted-foreground">
          {error}{" "}
          <button
            type="button"
            onClick={() => void load()}
            className="font-medium text-brand hover:underline"
          >
            Retry
          </button>
        </div>
      ) : templates.length === 0 ? (
        <div className="flex flex-col items-center gap-4 py-16 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            <FilePlus2 className="size-6" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium">No templates yet</p>
            <p className="mx-auto max-w-sm text-sm text-muted-foreground text-balance">
              Create a template to define how generated invoices and contracts
              are laid out.
            </p>
          </div>
          <Button onClick={() => setWizardOpen(true)}>
            <FilePlus2 />
            New template
          </Button>
        </div>
      ) : (
        <div className="space-y-8">
          {DOC_TYPE_ORDER.map((docType) => {
            const group = templates.filter((t) => t.doc_type === docType);
            if (group.length === 0) return null;
            return (
              <section key={docType} className="space-y-3">
                <h2 className="text-sm font-medium capitalize">{docType}</h2>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                  {group.map((template) => (
                    <TemplateCard
                      key={template.id}
                      template={template}
                      onDelete={handleDelete}
                      deleting={deletingIds.has(template.id)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      <TemplateWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        onCreated={handleCreated}
      />
    </div>
  );
}

export function TemplatesView() {
  const route = useHashRoute();
  if (route.view === "templates" && route.id) {
    return <TemplateDetailStub id={route.id} />;
  }
  return <TemplateList />;
}
