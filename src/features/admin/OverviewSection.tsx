// Admin overview: KPI cards + status/decision breakdowns from GET /overview.
import { useEffect, useState } from "react";
import {
  FileText,
  ShieldCheck,
  Flag,
  PencilLine,
  Layers,
  ScanText,
  Gauge,
  Target,
  Activity,
  Wrench,
} from "lucide-react";
import { ApiError, getOverview } from "@/lib/api";
import { formatPct, formatDate } from "@/lib/format";
import { humanize } from "@/lib/fields";
import { ConfidencePill } from "@/features/inspector/StructuredPanel";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type {
  OverviewStats,
  TimeSeries,
  DocTypeKpi,
} from "@/lib/types";

function StatCard({
  icon: Icon,
  label,
  value,
  tone,
  subtext,
}: {
  icon: typeof FileText;
  label: string;
  value: string | number;
  tone?: string;
  subtext?: string;
}) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        <Icon className="size-3.5" />
        {label}
      </div>
      <div className={cn("mt-2 text-2xl font-semibold tabular-nums", tone)}>
        {value}
      </div>
      {subtext && (
        <div className="mt-1 text-xs text-muted-foreground">{subtext}</div>
      )}
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  uploaded: "Uploaded",
  prescanned: "Pre-scanned",
  ocr_done: "OCR done",
  structured: "Structured",
  decided: "Decided",
  needs_review: "Needs review",
};

function Breakdown({
  title,
  data,
  labels,
}: {
  title: string;
  data: Record<string, number>;
  labels?: Record<string, string>;
}) {
  const entries = Object.entries(data);
  const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {title}
      </div>
      {entries.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground/60 italic">No data yet.</p>
      ) : (
        <div className="mt-3 space-y-2">
          {entries.map(([key, n]) => (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span className="capitalize">{labels?.[key] ?? key.replace(/_/g, " ")}</span>
                <span className="font-mono text-muted-foreground">{n}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-brand"
                  style={{ width: `${(n / total) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * A fixed-width daily time-series chart. Points always span the full width
 * regardless of bucket count, so a sparse 2-point series reads full-width and a
 * zero-filled series renders as a flat baseline (never broken/empty).
 */
function Sparkline({ series }: { series: TimeSeries }) {
  const buckets = series.buckets;
  const W = 100;
  const H = 40;
  const max = Math.max(1, ...buckets.map((b) => b.count));
  // Map a count to a y in [2, 38]: 0 -> flat baseline near the bottom.
  const yOf = (count: number) => H - 2 - (count / max) * (H - 4);
  const xOf = (i: number) =>
    buckets.length <= 1 ? W / 2 : (i / (buckets.length - 1)) * W;

  let points: Array<[number, number]>;
  if (buckets.length === 0) {
    points = [
      [0, yOf(0)],
      [W, yOf(0)],
    ];
  } else if (buckets.length === 1) {
    const y = yOf(buckets[0].count);
    points = [
      [0, y],
      [W, y],
    ];
  } else {
    points = buckets.map((b, i) => [xOf(i), yOf(b.count)]);
  }
  const poly = points.map(([x, y]) => `${x},${y}`).join(" ");
  const slot = buckets.length > 0 ? W / buckets.length : W;

  return (
    <svg
      className="h-10 w-full text-brand"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Daily counts"
    >
      <polyline
        points={poly}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      {buckets.map((b, i) => (
        <rect
          key={b.date}
          x={i * slot}
          y={0}
          width={slot}
          height={H}
          fill="transparent"
        >
          <title>{`${formatDate(b.date) || b.date}: ${b.count}`}</title>
        </rect>
      ))}
    </svg>
  );
}

function SparklineCard({
  icon: Icon,
  title,
  series,
}: {
  icon: typeof FileText;
  title: string;
  series: TimeSeries;
}) {
  const total = series.buckets.reduce((s, b) => s + b.count, 0);
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          <Icon className="size-3.5" />
          {title}
        </div>
        <span className="text-sm font-semibold tabular-nums">{total}</span>
      </div>
      <div className="mt-3">
        <Sparkline series={series} />
      </div>
    </div>
  );
}

/** Per-doc-type KPI rollup: one row per by_doc_type entry (pre-sorted). */
function DocTypeTable({ rows }: { rows: DocTypeKpi[] }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        By document type
      </div>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground/60 italic">
          No data yet.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground">
                <th className="py-1.5 pr-3 text-left font-medium">Type</th>
                <th className="px-3 py-1.5 text-right font-medium">Docs</th>
                <th className="px-3 py-1.5 text-right font-medium">Share</th>
                <th className="px-3 py-1.5 text-right font-medium">Extraction</th>
                <th className="px-3 py-1.5 text-right font-medium">Accuracy</th>
                <th className="py-1.5 pl-3 text-right font-medium">Corrections</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.doc_type} className="border-t">
                  <td className="py-2 pr-3 font-medium">
                    {humanize(d.doc_type)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {d.documents}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                    {formatPct(d.pct_of_total)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {d.avg_extraction_confidence == null ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <ConfidencePill value={d.avg_extraction_confidence} />
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {d.eval_runs === 0 || d.latest_accuracy == null ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <ConfidencePill value={d.latest_accuracy} />
                    )}
                  </td>
                  <td className="py-2 pl-3 text-right tabular-nums">
                    {d.corrections_total}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function OverviewSection() {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const s = await getOverview();
        if (!cancelled) setStats(s);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "Could not load overview.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <p className="text-sm text-muted-foreground">{error}</p>;
  }
  if (!stats) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
    );
  }

  const flagged = stats.decisions["flag"] ?? 0;
  const needsReview =
    (stats.documents_by_status["needs_review"] ?? 0) +
    (stats.decisions["needs_review"] ?? 0);

  const acc = stats.accuracy;
  const accuracySubtext =
    acc.eval_runs_total === 0
      ? "No eval runs yet"
      : `line-item: ${formatPct(acc.latest_line_item_score)} · ${acc.eval_runs_total} eval ${
          acc.eval_runs_total === 1 ? "run" : "runs"
        }`;
  const coverage = Object.fromEntries(
    stats.by_doc_type.map((d) => [d.doc_type, d.documents]),
  );

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={FileText} label="Documents" value={stats.documents_total} />
        <StatCard
          icon={Gauge}
          label="Avg extraction"
          value={
            stats.avg_extraction_confidence == null
              ? "—"
              : formatPct(stats.avg_extraction_confidence)
          }
          tone={
            (stats.avg_extraction_confidence ?? 0) >= 0.6
              ? "text-approve"
              : "text-review"
          }
        />
        <StatCard
          icon={Flag}
          label="Needs attention"
          value={flagged + needsReview}
          tone={flagged + needsReview > 0 ? "text-review" : undefined}
        />
        <StatCard
          icon={PencilLine}
          label="Corrections"
          value={stats.corrections_total}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={ShieldCheck}
          label="Approved"
          value={stats.decisions["approve"] ?? 0}
          tone="text-approve"
        />
        <StatCard
          icon={PencilLine}
          label="Corrected docs"
          value={stats.corrected_documents}
        />
        <StatCard icon={Layers} label="Doc types" value={stats.doc_types} />
        <StatCard
          icon={ScanText}
          label="Models enabled"
          value={stats.engines_enabled}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <StatCard
          icon={Target}
          label="Accuracy"
          value={
            acc.eval_runs_total === 0
              ? "—"
              : formatPct(acc.latest_overall_score)
          }
          tone={
            acc.eval_runs_total === 0
              ? undefined
              : (acc.latest_overall_score ?? 0) >= 0.8
                ? "text-approve"
                : "text-review"
          }
          subtext={accuracySubtext}
        />
        <Breakdown title="Coverage by type" data={coverage} labels={
          Object.fromEntries(
            stats.by_doc_type.map((d) => [d.doc_type, humanize(d.doc_type)]),
          )
        } />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <SparklineCard
          icon={Activity}
          title="Documents / day"
          series={stats.throughput}
        />
        <SparklineCard
          icon={Wrench}
          title="Corrections / day"
          series={stats.maintenance}
        />
      </div>

      <DocTypeTable rows={stats.by_doc_type} />

      <div className="grid gap-3 lg:grid-cols-2">
        <Breakdown
          title="Documents by status"
          data={stats.documents_by_status}
          labels={STATUS_LABEL}
        />
        <Breakdown title="Decisions" data={stats.decisions} />
      </div>
    </div>
  );
}
