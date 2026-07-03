// The unified landing. One dropzone, one submit: drop a single document and it runs
// the single-document pipeline (upfront doc-type picker, Option A); drop several and
// they become a multi-document case that gets classified and reconciled together. The
// staged-file count alone decides which controls show and which flow submit runs —
// there is no mode switch. Neither submit navigates; the Shell's state→URL effects flip
// to the document or case pane once the pipeline / case has state.
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Layers, ScanLine, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, listCaseTypes } from "@/lib/api";
import type { CaseTypeResponse } from "@/lib/types";
import { usePipelineContext } from "@/features/pipeline/PipelineContext";
import { useCaseContext } from "@/features/case/CaseContext";
import { Dropzone } from "@/features/upload/Dropzone";
import { DocTypeToggle } from "@/features/upload/DocTypeToggle";
import { EngineSelect, AUTO_ENGINE } from "@/features/upload/EngineSelect";
import { useEngines } from "@/features/upload/useEngines";
import { useDocTypes } from "@/features/doctypes/useDocTypes";
import { DocumentLibrary } from "@/features/upload/DocumentLibrary";
import { CaseList } from "@/features/case/CaseList";

const STAGES = [
  { label: "Pre-scan", hint: "quality & deskew" },
  { label: "OCR", hint: "VLM / Docling" },
  { label: "Structure", hint: "LangExtract" },
  { label: "Decide", hint: "approve / flag" },
];

// Sentinel for the "Open pile" (no case type) option — maps to `null` on submit.
const OPEN_PILE = "__open_pile__";

export function Home() {
  const {
    docType,
    activeEngine,
    setDocType,
    setActiveEngine,
    ingestFile,
    ingesting,
  } = usePipelineContext();
  const { createAndUpload } = useCaseContext();
  const { docTypes, loading, error, refetch } = useDocTypes();
  const {
    engines,
    loading: enginesLoading,
    error: enginesError,
    refetch: refetchEngines,
  } = useEngines();

  const topRef = useRef<HTMLDivElement>(null);

  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const [caseTypeValue, setCaseTypeValue] = useState(OPEN_PILE);
  const [label, setLabel] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [caseTypes, setCaseTypes] = useState<CaseTypeResponse[]>([]);
  const [typesLoading, setTypesLoading] = useState(true);
  const [typesError, setTypesError] = useState<string | null>(null);

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

  // Keep the selected doc type valid once types load: if the current selection isn't
  // among the fetched types, fall back to the first available.
  useEffect(() => {
    if (
      !loading &&
      docTypes.length > 0 &&
      !docTypes.some((d) => d.name === docType)
    ) {
      setDocType(docTypes[0].name);
    }
  }, [docTypes, docType, loading, setDocType]);

  // Same guard for engines: default to the first available if the selection is gone.
  // The "auto" sentinel is always valid (it isn't a real engine key), so leave it be.
  useEffect(() => {
    if (
      !enginesLoading &&
      engines.length > 0 &&
      activeEngine !== AUTO_ENGINE &&
      !engines.some((e) => e.key === activeEngine)
    ) {
      setActiveEngine(engines[0].key);
    }
  }, [engines, activeEngine, enginesLoading, setActiveEngine]);

  const typeOptions = useMemo<ComboboxOption[]>(
    () => [
      {
        value: OPEN_PILE,
        label: "Open pile (no type)",
        hint: "reconcile all shared fields",
      },
      ...caseTypes.map((ct) => ({
        value: ct.name,
        label: ct.label || ct.name,
        hint: `${ct.members.length} expected doc${ct.members.length === 1 ? "" : "s"}`,
      })),
    ],
    [caseTypes],
  );

  const count = stagedFiles.length;
  const isCase = count >= 2;
  const busy = ingesting || submitting;
  const canSubmit = count > 0 && !!activeEngine && !busy;

  const scrollToTop = () =>
    topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  const submit = async () => {
    if (!canSubmit) return;
    if (isCase) {
      // Multi-document: create a case and fan the files out. createAndUpload dispatches
      // CREATE_CASE_DONE early (sets caseId); the Shell's caseId effect then flips to the
      // case pane. A failed createCase returns false without flipping — re-enable the form.
      setSubmitting(true);
      const caseType = caseTypeValue === OPEN_PILE ? null : caseTypeValue;
      const ok = await createAndUpload(
        stagedFiles,
        caseType,
        label.trim(),
        activeEngine,
      );
      if (!ok) setSubmitting(false);
    } else {
      // Single document: run the existing pipeline with the picked doc type + engine.
      // No navigate — the Shell's document effect flips to the document pane once the
      // pipeline holds the ingested doc.
      await ingestFile(stagedFiles[0]);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col items-center gap-10 px-6 py-12">
      <div ref={topRef} className="flex w-full max-w-2xl flex-col items-center gap-8">
        <div className="space-y-3 text-center">
          <div className="inline-flex items-center gap-2 rounded-full border bg-muted/50 px-3 py-1 text-xs font-medium text-muted-foreground">
            <Sparkles className="size-3.5 text-brand" />
            OCR-to-decision pipeline
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
            From scanned document to a defensible decision
          </h1>
          <p className="mx-auto max-w-md text-sm text-muted-foreground text-balance">
            Drop your documents — one to analyze it, or several to cross-check
            them. Each field stays traceable to its source, all the way to an
            approve-or-flag decision.
          </p>
        </div>

        <Card className="w-full">
          <CardContent className="space-y-6">
            <Dropzone
              multiple
              onFiles={(dropped) =>
                setStagedFiles((prev) => [...prev, ...dropped])
              }
              disabled={busy}
              label="Drop your documents"
              hint={
                <>
                  or <span className="font-medium text-brand">browse</span> —
                  one to analyze it, or several to cross-check them
                </>
              }
            />

            {count > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">
                    {count} document{count === 1 ? "" : "s"} ready
                  </span>
                  <button
                    type="button"
                    onClick={() => setStagedFiles([])}
                    disabled={busy}
                    className="rounded-sm text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50"
                  >
                    Clear
                  </button>
                </div>
                <ul className="divide-y rounded-lg border bg-muted/20">
                  {stagedFiles.map((f, i) => (
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
                          setStagedFiles((prev) =>
                            prev.filter((_, j) => j !== i),
                          )
                        }
                        disabled={busy}
                        className="rounded-sm text-xs text-muted-foreground hover:text-destructive focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50"
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="grid gap-5 sm:grid-cols-2">
              {/* Single-document: pick its doc type. Multi-document: pick a case type. */}
              {isCase ? (
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
                      disabled={busy}
                    />
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                    Document type
                  </label>
                  {error ? (
                    <div className="text-sm text-muted-foreground">
                      {error}{" "}
                      <button
                        type="button"
                        onClick={refetch}
                        className="font-medium text-brand hover:underline"
                      >
                        Retry
                      </button>
                    </div>
                  ) : (
                    <DocTypeToggle
                      value={docType}
                      onChange={setDocType}
                      docTypes={docTypes}
                      loading={loading}
                      disabled={busy}
                    />
                  )}
                </div>
              )}

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
                      className="font-medium text-brand hover:underline"
                    >
                      Retry
                    </button>
                  </div>
                ) : (
                  <EngineSelect
                    engines={engines}
                    loading={enginesLoading}
                    value={activeEngine}
                    onChange={setActiveEngine}
                    disabled={busy}
                  />
                )}
              </div>
            </div>

            {isCase && (
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
                  disabled={busy}
                />
              </div>
            )}

            <Button
              className="w-full"
              onClick={() => void submit()}
              disabled={!canSubmit}
            >
              {busy ? (
                <>
                  <ScanLine className="size-4 animate-pulse" />
                  {isCase ? "Starting…" : "Ingesting & running the pipeline…"}
                </>
              ) : count <= 1 ? (
                "Analyze document"
              ) : (
                `Analyze ${count} documents`
              )}
            </Button>
          </CardContent>
        </Card>

        <div className="flex flex-wrap items-center justify-center gap-x-1 gap-y-2 text-xs text-muted-foreground">
          {STAGES.map((s, i) => (
            <div key={s.label} className="flex items-center gap-1">
              <span className="rounded-md border bg-card px-2.5 py-1">
                <span className="font-medium text-foreground">{s.label}</span>
                <span className="ml-1.5 text-muted-foreground">{s.hint}</span>
              </span>
              {i < STAGES.length - 1 && (
                <ArrowRight className="size-3.5 opacity-40" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Recent work — cases first, then individual documents. */}
      <CaseList onNewCase={scrollToTop} />
      <DocumentLibrary />
    </div>
  );
}
