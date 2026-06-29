// Lists configurable document types (built-in + custom) with create / edit /
// delete affordances. Built-in types are read-only (their edit/delete controls
// are disabled behind an explanatory tooltip); custom types can be edited or
// deleted (delete is gated behind an AlertDialog confirmation).
import { createElement, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
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
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import type { DocTypeResponse } from "@/lib/doc-type-schema";
import { useDocTypes } from "./useDocTypes";
import { DocTypeBuilderDialog } from "./DocTypeBuilderDialog";

export function DocTypeManager({ onChanged }: { onChanged: () => void }) {
  const { docTypes, loading, error, refetch } = useDocTypes();
  const [builderOpen, setBuilderOpen] = useState(false);
  const [editingType, setEditingType] = useState<DocTypeResponse | undefined>();
  const [deletingName, setDeletingName] = useState<string | null>(null);

  const openCreate = () => {
    setEditingType(undefined);
    setBuilderOpen(true);
  };

  const openEdit = (t: DocTypeResponse) => {
    setEditingType(t);
    setBuilderOpen(true);
  };

  const handleSaved = () => {
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
                className="flex items-center gap-3 rounded-lg border p-3"
              >
                {createElement(icon, {
                  className: "size-5 shrink-0 text-muted-foreground",
                })}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">
                      {t.label}
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

        <Button variant="outline" size="sm" onClick={openCreate}>
          <Plus className="size-3.5" />
          Create new type
        </Button>

        {builderOpen && (
          <DocTypeBuilderDialog
            key={editingType?.name ?? "create"}
            open={builderOpen}
            onClose={() => setBuilderOpen(false)}
            editingType={editingType}
            onSaved={handleSaved}
          />
        )}
      </div>
    </TooltipProvider>
  );
}
