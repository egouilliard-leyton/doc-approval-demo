// The "History" tab beside the editor: a newest-first list of persisted
// revisions (every saved edit + each agent turn snapshots one). Restoring rolls
// the template's body/CSS back to that snapshot — and because the backend
// snapshots the current state first, a restore is itself undoable. When the user
// has unsaved local edits, a restore is gated behind a confirm dialog so they
// don't silently lose work.
import { useEffect, useState } from "react";
import { History, Loader2, RotateCcw } from "lucide-react";
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
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  listTemplateRevisions,
  restoreTemplateRevision,
} from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { TemplateDetail, TemplateRevisionInfo } from "@/lib/types";

export function HistoryPanel({
  templateId,
  hasUnsavedChanges,
  onRestored,
}: {
  templateId: string;
  hasUnsavedChanges: boolean;
  onRestored: (t: TemplateDetail) => void;
}) {
  const [revisions, setRevisions] = useState<TemplateRevisionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  // The revision awaiting confirmation when there are unsaved local edits.
  const [pending, setPending] = useState<TemplateRevisionInfo | null>(null);

  // Refetch on mount. This tab is not forceMounted, so it naturally remounts on
  // activation — showing the latest revisions each time it's opened.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const rows = await listTemplateRevisions(templateId);
        if (!cancelled) setRevisions(rows);
      } catch (e) {
        const msg =
          e instanceof ApiError ? e.message : "Could not load revisions.";
        if (!cancelled) toast.error("Failed to load history", { description: msg });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId]);

  const restore = async (rev: TemplateRevisionInfo) => {
    setRestoringId(rev.id);
    try {
      const updated = await restoreTemplateRevision(templateId, rev.id);
      onRestored(updated);
      toast.success("Restored");
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Could not restore this revision.";
      toast.error("Restore failed", { description: msg });
    } finally {
      setRestoringId(null);
    }
  };

  const handleRestoreClick = (rev: TemplateRevisionInfo) => {
    if (hasUnsavedChanges) {
      setPending(rev);
    } else {
      void restore(rev);
    }
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="space-y-1">
        <h2 className="text-sm font-medium">History</h2>
        <p className="text-xs text-muted-foreground">
          Every saved edit is snapshotted here. Restore rolls the body back to a
          snapshot — and is itself undoable.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading history…
        </div>
      ) : revisions.length === 0 ? (
        <p className="flex items-center gap-2 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
          <History className="size-4 shrink-0" />
          No revisions yet — saved edits appear here.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {revisions.map((rev) => (
            <li
              key={rev.id}
              className="flex items-center justify-between gap-3 rounded-lg border bg-card p-3"
            >
              <div className="min-w-0 space-y-0.5">
                <p className="truncate text-sm">{rev.note ?? "Manual edit"}</p>
                <p className="text-xs text-muted-foreground">
                  {formatDate(rev.created_at)}
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={restoringId !== null}
                onClick={() => handleRestoreClick(rev)}
              >
                {restoringId === rev.id ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <RotateCcw />
                )}
                Restore
              </Button>
            </li>
          ))}
        </ul>
      )}

      <AlertDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Restoring replaces the current body with this snapshot.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pending) void restore(pending);
                setPending(null);
              }}
            >
              Restore
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
