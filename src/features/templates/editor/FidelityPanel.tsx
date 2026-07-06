// The "Fidelity" tab: a vision-QA pass that compares the rendered template to a
// reference (your uploaded PDF example, or a self-review when the source was a
// DOCX with no reference image). Shows a verdict banner, a side-by-side of the
// two renders, and a findings checklist that can be handed off to the AI editor.
import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  ImageOff,
  Loader2,
  ScanEye,
  Send,
  TriangleAlert,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, fileUrl, listDocuments, runTemplateQa } from "@/lib/api";
import type {
  DocumentStatus,
  DocumentSummary,
  QaFinding,
  QaReport,
  TemplateDetail,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Partial<Record<DocumentStatus, string>> = {
  structured: "Structured",
  decided: "Decided",
};

// Same eligibility rule GeneratePanel uses: a processed document of this type.
function isEligible(
  doc: DocumentSummary,
  docType: TemplateDetail["doc_type"],
): boolean {
  return (
    doc.doc_type === docType &&
    (doc.status === "structured" || doc.status === "decided")
  );
}

const NONE = "__none__";

function SeverityBadge({ severity }: { severity: QaFinding["severity"] }) {
  if (severity === "high") {
    return <Badge variant="destructive">high</Badge>;
  }
  if (severity === "medium") {
    return (
      <Badge variant="outline" className="border-review/40 text-review">
        medium
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-muted-foreground">
      low
    </Badge>
  );
}

// One image column (reference or rendered), matching EngineComparison's idiom.
function ImageColumn({
  title,
  urls,
  emptyLabel,
}: {
  title: string;
  urls: string[];
  emptyLabel?: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2 rounded-xl border bg-card p-3">
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {title}
      </p>
      {urls.length === 0 ? (
        <div className="flex h-[36vh] flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-sm text-muted-foreground">
          <ImageOff className="size-5" />
          {emptyLabel ?? "No image"}
        </div>
      ) : (
        <div className="flex max-h-[48vh] flex-col gap-2 overflow-y-auto rounded-lg border bg-muted/30 p-2">
          {urls.map((url, i) => (
            <img
              key={i}
              src={fileUrl(url)}
              alt={`${title} page ${i + 1}`}
              className="max-w-full rounded-md border bg-white"
            />
          ))}
        </div>
      )}
    </div>
  );
}

// Turn the findings into a single actionable instruction for the authoring agent.
function composeAgentMessage(findings: QaFinding[]): string {
  const lines = findings.map((f) => {
    const fix = f.suggested_fix ? ` (fix: ${f.suggested_fix})` : "";
    const page = f.page != null ? ` [p${f.page}]` : "";
    return `- [${f.severity}/${f.category}]${page} ${f.description}${fix}`;
  });
  return `Please fix these fidelity issues so the template matches the intended format:\n${lines.join("\n")}`;
}

export function FidelityPanel({
  template,
  onSendToAgent,
  autoRunKey,
}: {
  template: TemplateDetail;
  onSendToAgent: (message: string) => void;
  autoRunKey?: number;
}) {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>(NONE);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<QaReport | null>(null);
  // Track the last autoRunKey we handled so an auto-run fires exactly once.
  const handledAutoRunRef = useRef<number | undefined>(autoRunKey);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const all = await listDocuments();
        if (!cancelled)
          setDocs(all.filter((d) => isEligible(d, template.doc_type)));
      } catch {
        // Non-fatal: the picker just stays empty; validation still works with
        // the placeholder preview.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [template.doc_type]);

  const runValidation = async (documentId: string | null) => {
    setRunning(true);
    try {
      const res = await runTemplateQa(template.id, { document_id: documentId });
      setReport(res);
    } catch (e) {
      let msg = "Could not validate the template.";
      if (e instanceof ApiError) {
        if (e.status === 503) {
          msg = "Rendering is unavailable right now — please try again shortly.";
        } else if (e.status === 400) {
          msg = e.message || "The template couldn't be validated in its current state.";
        } else {
          msg = e.message;
        }
      }
      toast.error("Validation failed", { description: msg });
    } finally {
      setRunning(false);
    }
  };

  // Auto-run once when the parent bumps autoRunKey to a new truthy value (e.g.
  // right after a source upload converts a document into an editable template).
  useEffect(() => {
    if (
      autoRunKey !== undefined &&
      autoRunKey !== handledAutoRunRef.current &&
      autoRunKey
    ) {
      handledAutoRunRef.current = autoRunKey;
      const documentId = selectedId === NONE ? null : selectedId;
      void runValidation(documentId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRunKey]);

  const findings = report?.findings ?? [];

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="space-y-1">
        <h2 className="text-sm font-medium">Fidelity check</h2>
        <p className="text-xs text-muted-foreground">
          Render the template and let a vision model compare it to your example,
          flagging layout, color, table, spacing, and text drift.
        </p>
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Validate against a processed document (optional)
        </label>
        <Select
          value={selectedId}
          onValueChange={setSelectedId}
          disabled={running}
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>
              — none — (preview with placeholder labels)
            </SelectItem>
            {docs.map((d) => (
              <SelectItem key={d.id} value={d.id}>
                <span className="truncate">{d.filename}</span>
                <span className="text-xs text-muted-foreground">
                  {STATUS_LABEL[d.status] ?? d.status}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Button
        className="w-fit"
        disabled={running}
        onClick={() =>
          void runValidation(selectedId === NONE ? null : selectedId)
        }
      >
        {running ? <Loader2 className="animate-spin" /> : <ScanEye />}
        Run validation
      </Button>

      {report && (
        <div className="space-y-4">
          {/* Verdict banner */}
          <div
            className={cn(
              "flex items-start gap-3 rounded-xl border p-4",
              report.ok
                ? "border-approve/40 bg-approve-muted/40"
                : "border-review/40 bg-review-muted/40",
            )}
          >
            {report.ok ? (
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-approve" />
            ) : (
              <TriangleAlert className="mt-0.5 size-5 shrink-0 text-review" />
            )}
            <div className="min-w-0 space-y-1">
              <p className="text-sm font-medium">
                {report.ok
                  ? "Looks faithful to the format"
                  : `${findings.length} issue${findings.length === 1 ? "" : "s"} to review`}
              </p>
              <p className="text-sm text-muted-foreground">{report.summary}</p>
              <p className="text-xs text-muted-foreground">
                {report.mode === "source_pdf"
                  ? "compared to your uploaded PDF"
                  : "self-review (no reference image for DOCX sources)"}
                {" · "}
                {report.provider_used}
              </p>
              {report.warnings.length > 0 && (
                <ul className="space-y-0.5 pt-1">
                  {report.warnings.map((w, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-1.5 text-xs text-muted-foreground"
                    >
                      <TriangleAlert className="mt-0.5 size-3 shrink-0 text-review" />
                      {w}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Side-by-side images */}
          <div className="flex flex-col gap-3 sm:flex-row">
            <ImageColumn
              title="Your example"
              urls={report.reference_image_urls}
              emptyLabel="No reference image (DOCX source)"
            />
            <ImageColumn
              title="Rendered template"
              urls={report.rendered_image_urls}
            />
          </div>

          {/* Findings checklist */}
          <div className="space-y-2">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Findings
            </p>
            {findings.length === 0 ? (
              <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                No issues found.
              </p>
            ) : (
              <ul className="space-y-2">
                {findings.map((f, i) => (
                  <li
                    key={i}
                    className="flex flex-col gap-1.5 rounded-lg border bg-card p-3"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <SeverityBadge severity={f.severity} />
                      <Badge variant="outline" className="text-muted-foreground">
                        {f.category}
                      </Badge>
                      {f.page != null && (
                        <Badge
                          variant="outline"
                          className="font-mono text-muted-foreground"
                        >
                          p{f.page}
                        </Badge>
                      )}
                    </div>
                    <p className="text-sm">{f.description}</p>
                    {f.suggested_fix && (
                      <p className="text-xs text-muted-foreground">
                        Fix: {f.suggested_fix}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <Button
            variant="outline"
            className="w-fit"
            disabled={findings.length === 0}
            onClick={() => onSendToAgent(composeAgentMessage(findings))}
          >
            <Send />
            Send fixes to AI editor
          </Button>
        </div>
      )}
    </div>
  );
}
