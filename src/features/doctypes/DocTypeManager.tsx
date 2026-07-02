// Lists configurable document types (built-in + custom) with create / edit /
// delete affordances. Built-in types are read-only (their edit/delete controls
// are disabled behind an explanatory tooltip); custom types can be edited or
// deleted (delete is gated behind an AlertDialog confirmation).
import { createElement, useEffect, useRef, useState } from "react";
import { Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, deleteDocType } from "@/lib/api";
import { cn } from "@/lib/utils";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import type { DocTypeResponse } from "@/lib/doc-type-schema";
import { useDocTypes } from "./useDocTypes";
import { DocTypeBuilderDialog } from "./DocTypeBuilderDialog";
import { CreateWithAIDialog } from "./wizard/CreateWithAIDialog";

export function DocTypeManager({
  focusName,
  onChanged,
}: {
  focusName?: string;
  onChanged: () => void;
}) {
  const { docTypes, loading, error, refetch } = useDocTypes();
  const [builderOpen, setBuilderOpen] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [editingType, setEditingType] = useState<DocTypeResponse | undefined>();
  const [deletingName, setDeletingName] = useState<string | null>(null);
  // The row a `focusName` deep-link points at, briefly ring-highlighted after scroll.
  const [highlightName, setHighlightName] = useState<string | null>(null);

  const openCreate = () => {
    setEditingType(undefined);
    setBuilderOpen(true);
  };

  const openEdit = (t: DocTypeResponse) => {
    setEditingType(t);
    setBuilderOpen(true);
  };

  // A `#/admin/config/doctype/<name>` deep-link focuses one type once the registry
  // loads: a custom type opens straight into the editor, a built-in one (read-only)
  // scrolls its row into view with a transient highlight. Guarded by the last-applied
  // focusName so it fires once per link change — not on every render — and never
  // fights a user who then navigates away.
  const appliedFocusRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (loading) return;
    if (focusName === appliedFocusRef.current) return;
    appliedFocusRef.current = focusName;
    if (!focusName) return;
    const target = docTypes.find((t) => t.name === focusName);
    if (!target) return; // unknown/deleted key: silent no-op

    // Defer to after paint: the rows must already be in the DOM to scroll to one,
    // and this keeps the focus side-effects (open editor / flash highlight) out of
    // the render pass.
    let timer: ReturnType<typeof setTimeout> | undefined;
    const raf = requestAnimationFrame(() => {
      if (!target.builtin) {
        openEdit(target); // custom type: straight into the editor
        return;
      }
      // Built-in (read-only): scroll its row in and briefly ring-highlight it.
      document
        .getElementById(`doctype-row-${target.name}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlightName(target.name);
      timer = setTimeout(() => setHighlightName(null), 2000);
    });
    return () => {
      cancelAnimationFrame(raf);
      if (timer) clearTimeout(timer);
    };
  }, [focusName, docTypes, loading]);

  const handleSaved = () => {
    onChanged();
    refetch();
  };

  // The AI wizard committed a new type: open the builder/editor on it so the user
  // can fine-tune, and refresh the lists/toggle so it shows up immediately.
  const handleWizardCreated = (t: DocTypeResponse) => {
    setWizardOpen(false);
    setEditingType(t);
    setBuilderOpen(true);
    onChanged();
    refetch();
  };

  const handleDelete = async (name: string) => {
    setDeletingName(name);
    try {
      await deleteDocType(name);
      toast.success("Doc type deleted");
      onChanged();
      refetch();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.error("Type in use", { description: e.message });
      } else {
        toast.error("Delete failed", {
          description: e instanceof ApiError ? e.message : String(e),
        });
      }
    } finally {
      setDeletingName(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-14 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-6 text-center text-sm text-muted-foreground">
        {error}{" "}
        <button
          type="button"
          onClick={refetch}
          className="font-medium text-brand hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="space-y-3">
        <div className="space-y-2">
          {docTypes.map((t) => {
            const icon = resolveDocTypeIcon(t.name, t.icon);
            const deleting = deletingName === t.name;
            return (
              <div
                key={t.name}
                id={`doctype-row-${t.name}`}
                className={cn(
                  "flex items-center gap-3 rounded-lg border p-3 transition-shadow",
                  highlightName === t.name && "ring-2 ring-brand",
                )}
              >
                {createElement(icon, {
                  className: "size-5 shrink-0 text-muted-foreground",
                })}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">
                      {t.label || t.name}
                    </span>
                    {t.builtin && (
                      <Badge variant="secondary">built-in</Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">{t.name}</span>
                    <span>·</span>
                    <span>v{t.version}</span>
                  </div>
                </div>

                {t.builtin ? (
                  <div className="flex items-center gap-1">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span>
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled
                            aria-label="Edit type"
                          >
                            <Pencil />
                          </Button>
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        Built-in types are read-only
                      </TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span>
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled
                            aria-label="Delete type"
                          >
                            <Trash2 />
                          </Button>
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        Built-in types are read-only
                      </TooltipContent>
                    </Tooltip>
                  </div>
                ) : (
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Edit type"
                      onClick={() => openEdit(t)}
                    >
                      <Pencil />
                    </Button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="text-destructive hover:text-destructive"
                          disabled={deleting}
                          aria-label="Delete type"
                        >
                          <Trash2 />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>
                            Delete this document type?
                          </AlertDialogTitle>
                          <AlertDialogDescription>
                            <span className="font-medium text-foreground">
                              {t.label}
                            </span>{" "}
                            will be permanently removed. This can't be undone.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            className="bg-destructive text-white hover:bg-destructive/90"
                            onClick={() => void handleDelete(t.name)}
                          >
                            Delete
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={openCreate}>
            <Plus className="size-3.5" />
            Create new type
          </Button>
          <Button variant="outline" size="sm" onClick={() => setWizardOpen(true)}>
            <Sparkles className="size-3.5" />
            Create with AI
          </Button>
        </div>

        {builderOpen && (
          <DocTypeBuilderDialog
            key={editingType?.name ?? "create"}
            open={builderOpen}
            onClose={() => setBuilderOpen(false)}
            editingType={editingType}
            onSaved={handleSaved}
          />
        )}

        {wizardOpen && (
          <CreateWithAIDialog
            open
            onClose={() => setWizardOpen(false)}
            onCreated={handleWizardCreated}
          />
        )}
      </div>
    </TooltipProvider>
  );
}
