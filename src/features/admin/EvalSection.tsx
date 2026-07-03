// Admin evaluation harness: score extraction engines against golden samples.
// Left is the golden catalogue (each row runs an engine); right is the run
// history (newest-first). Selecting a run expands its per-field / per-collection
// scorecard. A run deep-links via `#/admin/eval?run=<id>`.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ChevronRight,
  ExternalLink,
  Loader2,
  Play,
  Target,
} from "lucide-react";
import {
  ApiError,
  getEvalRun,
  listEngines,
  listEvalGoldens,
  listEvalRuns,
  runEval,
} from "@/lib/api";
import { humanize } from "@/lib/fields";
import { formatDate, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfidencePill } from "@/features/inspector/StructuredPanel";
import type {
  EngineInfo,
  EvalCollectionScore,
  EvalFieldScore,
  EvalGoldenSummary,
  EvalRunResult,
  EvalRunSummary,
} from "@/lib/types";

/** Engine options for the run buttons: always the mock engine, plus live ones. */
interface EngineOption {
  key: string;
  label: string;
  provider: string;
}

function display(v: string | number | boolean | null): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

// --- one field's expected-vs-actual scorecard row ----------------------------

function FieldScoreRow({ s }: { s: EvalFieldScore }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2 hover:bg-muted/50">
      <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
        {humanize(s.path.replace(/\./g, " "))}
      </span>
      <div className="flex items-center gap-2 font-mono text-xs">
        <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
          {display(s.expected)}
        </span>
        <ArrowRight className="size-3 text-muted-foreground" />
        <span
          className={cn(
            "rounded px-1.5 py-0.5 font-medium",
            s.normalized_match
              ? "bg-approve/10 text-approve"
              : "bg-flag/10 text-flag",
          )}
        >
          {display(s.actual)}
        </span>
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
            s.exact_match
              ? "bg-approve/10 text-approve"
              : "bg-muted text-muted-foreground",
          )}
        >
          exact
        </span>
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
            s.normalized_match
              ? "bg-approve/10 text-approve"
              : "bg-flag/10 text-flag",
          )}
        >
          norm
        </span>
      </div>
    </div>
  );
}

// --- one collection's row P/R/F1 + cell accuracy -----------------------------

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card px-2.5 py-1.5">
      <div className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-sm tabular-nums">{value}</div>
    </div>
  );
}

function CollectionScoreCard({
  name,
  s,
}: {
  name: string;
  s: EvalCollectionScore;
}) {
  return (
    <div className="rounded-xl border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{humanize(name)}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {s.matched}/{s.n_expected} matched · {s.n_actual} extracted
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Metric label="Row P" value={formatPct(s.row_precision)} />
        <Metric label="Row R" value={formatPct(s.row_recall)} />
        <Metric label="Row F1" value={formatPct(s.row_f1)} />
        <Metric label="Cell acc" value={formatPct(s.cell_accuracy)} />
        <Metric label="Line item" value={formatPct(s.line_item_score)} />
      </div>
    </div>
  );
}

// --- expanded run detail -----------------------------------------------------

function RunDetail({
  run,
  onOpenDocument,
}: {
  run: EvalRunResult;
  onOpenDocument: (id: string) => void;
}) {
  const collections = Object.entries(run.collection_scores);
  return (
    <div className="space-y-4 border-t bg-muted/20 p-3">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>
          Exact fields:{" "}
          <span className="font-mono text-foreground">
            {formatPct(run.field_accuracy_exact)}
          </span>
        </span>
        <span>
          Normalized:{" "}
          <span className="font-mono text-foreground">
            {formatPct(run.field_accuracy_normalized)}
          </span>
        </span>
        {run.document_id && (
          <Button
            size="xs"
            variant="outline"
            className="ml-auto"
            onClick={() => onOpenDocument(run.document_id)}
          >
            <ExternalLink className="size-3.5" /> Open document
          </Button>
        )}
      </div>

      <div>
        <div className="mb-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Fields ({run.field_scores.length})
        </div>
        {run.field_scores.length === 0 ? (
          <p className="px-3 py-2 text-sm text-muted-foreground/60 italic">
            No scored fields.
          </p>
        ) : (
          <div className="rounded-xl border bg-card p-1">
            {run.field_scores.map((s) => (
              <FieldScoreRow key={s.path} s={s} />
            ))}
          </div>
        )}
      </div>

      {collections.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Collections ({collections.length})
          </div>
          <div className="space-y-2">
            {collections.map(([name, s]) => (
              <CollectionScoreCard key={name} name={name} s={s} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// --- one run row in the results list -----------------------------------------

function RunRow({
  run,
  detail,
  expanded,
  onToggle,
  onOpenDocument,
}: {
  run: EvalRunSummary;
  detail: EvalRunResult | undefined;
  expanded: boolean;
  onToggle: () => void;
  onOpenDocument: (id: string) => void;
}) {
  const lineItem =
    detail && Object.keys(detail.collection_scores).length > 0
      ? Math.max(
          ...Object.values(detail.collection_scores).map(
            (c) => c.line_item_score,
          ),
        )
      : null;

  return (
    <div className="overflow-hidden rounded-xl border">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50"
      >
        <ChevronRight
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-90",
          )}
        />
        <ConfidencePill value={run.overall_score} />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {humanize(run.doc_type)}
        </span>
        {lineItem != null && (
          <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground">
            line item {formatPct(lineItem)}
          </span>
        )}
        <span className="shrink-0 text-xs text-muted-foreground">
          {run.engine} · {run.provider}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
          {formatDate(run.created_at)}
        </span>
      </button>
      {expanded &&
        (detail ? (
          <RunDetail run={detail} onOpenDocument={onOpenDocument} />
        ) : (
          <div className="border-t p-3">
            <Skeleton className="h-24 w-full rounded-lg" />
          </div>
        ))}
    </div>
  );
}

// --- golden catalogue row ----------------------------------------------------

function GoldenRow({
  golden,
  engines,
  running,
  onRun,
}: {
  golden: EvalGoldenSummary;
  engines: EngineOption[];
  running: string | null;
  onRun: (engine: EngineOption) => void;
}) {
  return (
    <div className="rounded-xl border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{golden.id}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {humanize(golden.doc_type)} · {golden.field_count} field
            {golden.field_count === 1 ? "" : "s"} · {golden.collection_count}{" "}
            collection{golden.collection_count === 1 ? "" : "s"}
          </div>
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {engines.map((e) => {
          const busy = running === `${golden.id}:${e.key}`;
          return (
            <Button
              key={e.key}
              size="xs"
              variant="outline"
              disabled={busy}
              onClick={() => onRun(e)}
            >
              {busy ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Play className="size-3.5" />
              )}
              {e.label}
            </Button>
          );
        })}
      </div>
    </div>
  );
}

// --- section -----------------------------------------------------------------

export function EvalSection({
  runId,
  onOpenDocument,
}: {
  runId?: string;
  onOpenDocument: (id: string) => void;
}) {
  const [goldens, setGoldens] = useState<EvalGoldenSummary[] | null>(null);
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [details, setDetails] = useState<Record<string, EvalRunResult>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [g, r, e] = await Promise.all([
          listEvalGoldens(),
          listEvalRuns(),
          listEngines(),
        ]);
        if (cancelled) return;
        setGoldens(g);
        setRuns(r);
        setEngines(e);
      } catch (err) {
        if (!cancelled)
          setError(
            err instanceof ApiError ? err.message : "Could not load evaluations.",
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Deep-link: expand the run named in the URL, fetching it if not in the list.
  // Guarded by the last-applied runId so it fires once per link change, and the
  // state updates are deferred out of the render pass (rAF) to avoid cascading
  // renders — same shape as the config section's focus deep-link.
  const appliedRunRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (runId === appliedRunRef.current) return;
    appliedRunRef.current = runId;
    if (!runId) return;
    let cancelled = false;
    const raf = requestAnimationFrame(() => {
      if (cancelled) return;
      setExpanded(runId);
      void (async () => {
        try {
          const full = await getEvalRun(runId);
          if (cancelled) return;
          setDetails((prev) => ({ ...prev, [runId]: full }));
          setRuns((prev) =>
            prev.some((r) => r.id === runId) ? prev : [full, ...prev],
          );
        } catch {
          /* unknown run id — leave the row collapsed */
        }
      })();
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [runId]);

  const engineOptions = useMemo<EngineOption[]>(
    () => [
      { key: "mock", label: "Mock", provider: "mock" },
      ...engines.map((e) => ({ key: e.key, label: e.label, provider: "" })),
    ],
    [engines],
  );

  const toggle = async (id: string) => {
    if (expanded === id) {
      setExpanded(null);
      return;
    }
    setExpanded(id);
    if (!details[id]) {
      try {
        const full = await getEvalRun(id);
        setDetails((prev) => ({ ...prev, [id]: full }));
      } catch {
        /* keep collapsed skeleton on failure */
      }
    }
  };

  const run = async (golden: EvalGoldenSummary, engine: EngineOption) => {
    if (running !== null) return; // one run at a time (shared eval document)
    const token = `${golden.id}:${engine.key}`;
    setRunning(token);
    setError(null); // clear any stale error from a previous action
    try {
      const result = await runEval({
        golden_id: golden.id,
        engine: engine.key,
        provider: engine.provider,
      });
      setRuns((prev) => [result, ...prev]);
      setDetails((prev) => ({ ...prev, [result.id]: result }));
      setExpanded(result.id);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Evaluation run failed.",
      );
    } finally {
      setRunning(null);
    }
  };

  if (error && !goldens) {
    return <p className="text-sm text-muted-foreground">{error}</p>;
  }
  if (!goldens) {
    return (
      <div className="grid gap-3 lg:grid-cols-2">
        <Skeleton className="h-64 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-flag">{error}</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Golden catalogue */}
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            <Target className="size-3.5" /> Golden samples ({goldens.length})
          </div>
          {goldens.length === 0 ? (
            <div className="flex h-40 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
              No golden samples registered.
            </div>
          ) : (
            goldens.map((g) => (
              <GoldenRow
                key={g.id}
                golden={g}
                engines={engineOptions}
                running={running}
                onRun={(e) => void run(g, e)}
              />
            ))
          )}
        </div>

        {/* Results */}
        <div className="space-y-2">
          <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Runs ({runs.length})
          </div>
          {runs.length === 0 ? (
            <div className="flex h-40 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
              No runs yet. Score an engine against a golden to begin.
            </div>
          ) : (
            runs.map((r) => (
              <RunRow
                key={r.id}
                run={r}
                detail={details[r.id]}
                expanded={expanded === r.id}
                onToggle={() => void toggle(r.id)}
                onOpenDocument={onOpenDocument}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
