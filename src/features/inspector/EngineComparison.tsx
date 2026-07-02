import { useState } from "react";
import { Columns2, Loader2, Play, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { cn } from "@/lib/utils";
import { formatMs, formatPct, confidenceTone } from "@/lib/format";
import type { EngineInfo, OCRResult } from "@/lib/types";

// One transcription pane: a dropdown to pick which engine to show + its text.
function ComparePane({
  value,
  onChange,
  options,
  ocr,
  page,
}: {
  value: string;
  onChange: (key: string) => void;
  options: ComboboxOption[];
  ocr: OCRResult | undefined;
  page: number;
}) {
  const current = ocr?.pages.find((p) => p.page === page) ?? ocr?.pages[0];
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2 rounded-xl border bg-card p-3">
      <Combobox
        value={value}
        onChange={onChange}
        options={options}
        placeholder="Pick an engine…"
        searchPlaceholder="Search engines…"
        emptyText="No engines run yet."
      />
      {ocr ? (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline" className="font-mono">
              {formatMs(ocr.latency_ms)}
            </Badge>
            <Badge
              variant="outline"
              className={cn("font-mono", confidenceTone(ocr.avg_confidence))}
            >
              {ocr.avg_confidence == null
                ? "no conf"
                : `conf ${formatPct(ocr.avg_confidence)}`}
            </Badge>
            <Badge variant="outline" className="font-mono">
              {ocr.table_count}T
            </Badge>
            {ocr.pages.length > 1 && current && (
              <Badge variant="outline" className="font-mono">
                p{current.page}/{ocr.pages.length}
              </Badge>
            )}
          </div>
          <ScrollArea className="h-[46vh] rounded-lg border bg-muted/30">
            <pre className="p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
              {current?.text || "(no text)"}
            </pre>
          </ScrollArea>
        </>
      ) : (
        <div className="flex h-[46vh] items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
          Select an engine that has run.
        </div>
      )}
    </div>
  );
}

// A compact chip per engine: metrics if it ran, a Run button if it didn't.
function EngineChip({
  label,
  ocr,
  onRun,
  running,
  disabled,
}: {
  label: string;
  ocr: OCRResult | undefined;
  onRun: () => void;
  running: boolean;
  disabled: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs",
        ocr ? "bg-card" : "border-dashed bg-card/50",
      )}
    >
      {ocr ? (
        <Check className="size-3.5 shrink-0 text-emerald-600" />
      ) : (
        <span className="size-1.5 shrink-0 rounded-full bg-muted-foreground/40" />
      )}
      <span className="max-w-40 truncate font-medium">{label}</span>
      {ocr ? (
        <span className="flex items-center gap-1.5 font-mono text-muted-foreground">
          <span>{formatMs(ocr.latency_ms)}</span>
          <span className={confidenceTone(ocr.avg_confidence)}>
            {ocr.avg_confidence == null
              ? "no conf"
              : formatPct(ocr.avg_confidence)}
          </span>
          <span>{ocr.table_count}T</span>
        </span>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          className="h-6 gap-1 px-1.5 text-xs"
          onClick={onRun}
          disabled={disabled}
        >
          {running ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Play className="size-3.5" />
          )}
          Run
        </Button>
      )}
    </div>
  );
}

export function EngineComparison({
  engines,
  ocrByEngine,
  page,
  onRunAll,
  onRunEngine,
  running,
}: {
  engines: EngineInfo[];
  ocrByEngine: Record<string, OCRResult>;
  page: number;
  onRunAll: () => void;
  onRunEngine: (key: string) => Promise<void> | void;
  running: boolean;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [paneA, setPaneA] = useState("");
  const [paneB, setPaneB] = useState("");

  // Every engine we know about (enabled + any with a stored result).
  const allKeys = Array.from(
    new Set([...engines.map((e) => e.key), ...Object.keys(ocrByEngine)]),
  );
  const labelFor = (key: string) =>
    engines.find((e) => e.key === key)?.label ?? key;

  // Engines with a result are the ones you can actually compare.
  const ranKeys = allKeys.filter((k) => ocrByEngine[k]);
  const paneOptions: ComboboxOption[] = ranKeys.map((k) => ({
    value: k,
    label: labelFor(k),
  }));

  // Derive valid pane selections without effects: fall back to the first
  // available engines, keeping A and B distinct where possible.
  const a = paneA && ocrByEngine[paneA] ? paneA : (ranKeys[0] ?? "");
  const b =
    paneB && ocrByEngine[paneB] && paneB !== a
      ? paneB
      : (ranKeys.find((k) => k !== a) ?? "");

  const missing = engines.filter((e) => !ocrByEngine[e.key]).length;
  const busy = running || pending !== null;

  const runOne = async (key: string) => {
    setPending(key);
    try {
      await onRunEngine(key);
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Run engines below, then pick any two to compare their transcription of
          the selected page side by side.
        </p>
        <Button
          size="sm"
          variant="outline"
          className="shrink-0"
          onClick={onRunAll}
          disabled={busy || missing === 0}
        >
          {running && pending === null ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Columns2 className="size-4" />
          )}
          {missing === 0 ? "All engines run" : `Run all missing (${missing})`}
        </Button>
      </div>

      {/* Roster: compact status chip per engine, wraps instead of overflowing. */}
      {allKeys.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {allKeys.map((key) => (
            <EngineChip
              key={key}
              label={labelFor(key)}
              ocr={ocrByEngine[key]}
              onRun={() => void runOne(key)}
              running={pending === key}
              disabled={busy}
            />
          ))}
        </div>
      )}

      {/* Side-by-side: two panes, each independently switchable. */}
      {ranKeys.length === 0 ? (
        <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
          Run at least one engine to start comparing.
        </div>
      ) : (
        <div className="flex flex-1 gap-3">
          <ComparePane
            value={a}
            onChange={setPaneA}
            options={paneOptions}
            ocr={ocrByEngine[a]}
            page={page}
          />
          <ComparePane
            value={b}
            onChange={setPaneB}
            options={paneOptions}
            ocr={ocrByEngine[b]}
            page={page}
          />
        </div>
      )}
    </div>
  );
}
