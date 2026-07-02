// Settings dialog to connect/manage VLM OCR models. Each row is one OpenRouter
// model; enabling one makes it selectable in the upload picker. The add-model
// dropdown is populated live from OpenRouter's image-capable model list, and a
// free-text field accepts any slug directly. Mirrors DocTypeManagerDialog.
import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toggle } from "@/components/ui/toggle";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  createEngine,
  deleteEngine,
  listEngineCatalog,
  listOpenRouterModels,
  updateEngine,
} from "@/lib/api";
import type { OpenRouterModel, VlmEngineRow } from "@/lib/types";

const PASTE = "__paste__";

export function EngineManager({ onChanged }: { onChanged: () => void }) {
  const [catalog, setCatalog] = useState<VlmEngineRow[]>([]);
  const [models, setModels] = useState<OpenRouterModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string>("");
  const [pasteSlug, setPasteSlug] = useState("");
  const [label, setLabel] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setCatalog(await listEngineCatalog());
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [cat, mods] = await Promise.all([
          listEngineCatalog(),
          listOpenRouterModels().catch(() => [] as OpenRouterModel[]),
        ]);
        if (cancelled) return;
        setCatalog(cat);
        setModels(mods);
      } catch (e) {
        if (!cancelled)
          toast.error("Could not load models", {
            description: e instanceof ApiError ? e.message : String(e),
          });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const usePaste = selected === PASTE || (selected === "" && pasteSlug !== "");
  const model = usePaste ? pasteSlug.trim() : selected;

  const modelOptions: ComboboxOption[] = [
    { value: PASTE, label: "Paste a slug…" },
    ...models.map((m) => ({ value: m.id, label: m.name, hint: m.id })),
  ];

  const add = async () => {
    if (!model) {
      toast.error("Pick a model or paste an OpenRouter slug.");
      return;
    }
    const fallbackName =
      models.find((m) => m.id === model)?.name ?? model.split("/").pop() ?? model;
    setAdding(true);
    try {
      await createEngine({ label: label.trim() || fallbackName, model });
      await refetch();
      onChanged();
      setSelected("");
      setPasteSlug("");
      setLabel("");
      toast.success(`Connected ${fallbackName}`);
    } catch (e) {
      toast.error("Could not connect model", {
        description: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setAdding(false);
    }
  };

  const toggle = async (row: VlmEngineRow) => {
    setBusyKey(row.key);
    try {
      await updateEngine(row.key, { enabled: !row.enabled });
      await refetch();
      onChanged();
    } catch (e) {
      toast.error("Could not update model", {
        description: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setBusyKey(null);
    }
  };

  const remove = async (row: VlmEngineRow) => {
    setBusyKey(row.key);
    try {
      await deleteEngine(row.key);
      await refetch();
      onChanged();
      toast.success(`Disconnected ${row.label}`);
    } catch (e) {
      toast.error("Could not remove model", {
        description: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div className="space-y-5 p-1">
      {/* Add a model */}
      <div className="space-y-3 rounded-xl border bg-muted/30 p-4">
        <p className="text-sm font-medium">Connect a model</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">
              OpenRouter model
            </Label>
            <Combobox
              value={selected}
              onChange={setSelected}
              options={modelOptions}
              placeholder="Choose a vision model…"
              searchPlaceholder="Search models…"
              emptyText="No models match."
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">
              Display label
            </Label>
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="auto from model"
            />
          </div>
        </div>
        {usePaste && (
          <Input
            value={pasteSlug}
            onChange={(e) => setPasteSlug(e.target.value)}
            placeholder="provider/model-slug (e.g. google/gemini-3-pro)"
            className="font-mono text-sm"
          />
        )}
        <Button size="sm" onClick={add} disabled={adding || !model}>
          {adding ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Plus className="size-4" />
          )}
          Connect
        </Button>
      </div>

      {/* Connected models */}
      <div className="space-y-2">
        <p className="text-sm font-medium">Connected models</p>
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : catalog.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No models connected yet.
          </p>
        ) : (
          <div className="divide-y rounded-xl border">
            {catalog.map((row) => (
              <div
                key={row.key}
                className="flex items-center gap-3 px-3 py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {row.label}
                  </div>
                  <div className="truncate font-mono text-xs text-muted-foreground">
                    {row.model}
                  </div>
                </div>
                <Toggle
                  size="sm"
                  variant="outline"
                  pressed={row.enabled}
                  disabled={busyKey === row.key}
                  onPressedChange={() => void toggle(row)}
                  aria-label={row.enabled ? "Enabled" : "Disabled"}
                >
                  {row.enabled ? "Enabled" : "Disabled"}
                </Toggle>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="text-muted-foreground hover:text-destructive"
                      disabled={busyKey === row.key}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>
                        Disconnect {row.label}?
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        This removes the model from the picker. Existing OCR
                        results already saved for documents are kept.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction onClick={() => void remove(row)}>
                        Disconnect
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function EngineSettingsDialog({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>OCR models</DialogTitle>
          <DialogDescription>
            Connect vision-language models (via OpenRouter) and choose which are
            selectable at upload. Docling stays available as the layout engine.
          </DialogDescription>
        </DialogHeader>
        <ScrollArea className="max-h-[70vh]">
          {/* Remount on open so the catalog/model list is always fresh. */}
          {open && <EngineManager onChanged={onChanged} />}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
