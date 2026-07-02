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
} from "lucide-react";
import { ApiError, getOverview } from "@/lib/api";
import { formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { OverviewStats } from "@/lib/types";

function StatCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof FileText;
  label: string;
  value: string | number;
  tone?: string;
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
