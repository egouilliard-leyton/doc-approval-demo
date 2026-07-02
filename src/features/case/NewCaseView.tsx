// Start a new case: pick a case type (or an open pile), a case-global OCR engine, name
// it, and drop in one or more documents. "Upload & classify" fans the files out through
// the case orchestration (createAndUpload) — as soon as the case is created the shell
// flips to the classify/confirm stage where per-document progress is shown live.
import { useEffect, useMemo, useState } from "react";
import { Layers, ScanLine } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, listCaseTypes } from "@/lib/api";
import type { CaseTypeResponse } from "@/lib/types";
import { Dropzone } from "@/features/upload/Dropzone";
import { EngineSelect } from "@/features/upload/EngineSelect";
import { useEngines } from "@/features/upload/useEngines";
import { useCaseContext } from "@/features/case/CaseContext";
import { CaseStageHeader } from "@/features/case/CaseStageHeader";

// Sentinel for the "Open pile" (no case type) option — maps to `null` on submit.
const OPEN_PILE = "__open_pile__";

export function NewCaseView({
  engine,
  onEngineChange,
  onCancel,
}: {
  /** Case-global OCR engine, owned by the shell so it survives the stage flip. */
  engine: string;
  onEngineChange: (engine: string) => void;
  onCancel: () => void;
}) {
  const { createAndUpload } = useCaseContext();
  const {
    engines,
    loading: enginesLoading,
    error: enginesError,
    refetch: refetchEngines,
  } = useEngines();

  const [caseTypes, setCaseTypes] = useState<CaseTypeResponse[]>([]);
  const [typesLoading, setTypesLoading] = useState(true);
  const [typesError, setTypesError] = useState<string | null>(null);

  const [caseTypeValue, setCaseTypeValue] = useState(OPEN_PILE);
  const [label, setLabel] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await listCaseTypes();
        if (!cancelled) setCaseTypes(data);
      } catch (e) {
        if (!cancelled)
          setTypesError(
            e instanceof ApiError ? e.message : "Could not load case types.",
          );
      } finally {
        if (!cancelled) setTypesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Default the engine to the first available once engines load.
  useEffect(() => {
    if (!enginesLoading && engines.length > 0 && !engine) {
      onEngineChange(engines[0].key);
    }
  }, [engines, enginesLoading, engine, onEngineChange]);

  const typeOptions = useMemo<ComboboxOption[]>(
    () => [
      { value: OPEN_PILE, label: "Open pile (no type)", hint: "reconcile all shared fields" },
      ...caseTypes.map((ct) => ({
        value: ct.name,
        label: ct.label || ct.name,
        hint: `${ct.members.length} expected doc${ct.members.length === 1 ? "" : "s"}`,
      })),
    ],
    [caseTypes],
  );

  const canSubmit = files.length > 0 && !!engine && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    const caseType = caseTypeValue === OPEN_PILE ? null : caseTypeValue;
    // createAndUpload creates the case then flips the shell to the classify stage (this
    // view unmounts). If the initial createCase fails it returns false without flipping —
    // re-enable the form so the reviewer can retry instead of being locked out.
    const ok = await createAndUpload(files, caseType, label.trim(), engine);
    if (!ok) setSubmitting(false);
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <CaseStageHeader stage="new" onBack={onCancel} showBack={false} />

      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight">New case</h2>
        <p className="text-sm text-muted-foreground">
          Group related documents into one case, then reconcile their shared
          fields into a single defensible decision.
        </p>
      </div>

      <Card>
        <CardContent className="space-y-6">
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-2">
              <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Case type
              </label>
              {typesError ? (
                <div className="text-sm text-muted-foreground">
                  {typesError}
                </div>
              ) : typesLoading ? (
                <Skeleton className="h-8 w-full rounded-lg" />
              ) : (
                <Combobox
                  value={caseTypeValue}
                  onChange={setCaseTypeValue}
                  options={typeOptions}
                  placeholder="Open pile (no type)"
                  searchPlaceholder="Search case types…"
                  emptyText="No case types match."
                  disabled={submitting}
                />
              )}
            </div>

            <div className="space-y-2">
              <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                OCR engine
              </label>
              {enginesError ? (
                <div className="text-sm text-muted-foreground">
                  {enginesError}{" "}
                  <button
                    type="button"
                    onClick={refetchEngines}
                    className="rounded-sm font-medium text-brand hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <EngineSelect
                  engines={engines}
                  loading={enginesLoading}
                  value={engine}
                  onChange={onEngineChange}
                  disabled={submitting}
                />
              )}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Case label{" "}
              <span className="font-normal text-muted-foreground/70 lowercase">
                (optional)
              </span>
            </label>
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Acme onboarding — Q3"
              disabled={submitting}
            />
          </div>

          <Dropzone
            multiple
            onFiles={(dropped) =>
              setFiles((prev) => [...prev, ...dropped])
            }
            disabled={submitting}
            label="Drag & drop the case's documents"
            hint={
              <>
                or <span className="font-medium text-brand">browse</span> — add
                as many as belong to this case
              </>
            }
          />

          {files.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">
                  {files.length} document{files.length === 1 ? "" : "s"} ready
                </span>
                <button
                  type="button"
                  onClick={() => setFiles([])}
                  disabled={submitting}
                  className="rounded-sm text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50"
                >
                  Clear
                </button>
              </div>
              <ul className="divide-y rounded-lg border bg-muted/20">
                {files.map((f, i) => (
                  <li
                    key={`${f.name}-${i}`}
                    className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Layers className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">{f.name}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setFiles((prev) => prev.filter((_, j) => j !== i))
                      }
                      disabled={submitting}
                      className="rounded-sm text-xs text-muted-foreground hover:text-destructive focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" onClick={onCancel} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={() => void submit()} disabled={!canSubmit}>
              {submitting ? (
                <>
                  <ScanLine className="size-4 animate-pulse" />
                  Starting…
                </>
              ) : (
                <>Upload &amp; classify{files.length > 0 ? ` ${files.length}` : ""}</>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
