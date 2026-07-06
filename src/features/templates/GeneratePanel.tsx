// Generate a filled PDF from the template + one processed source document.
// Lists eligible documents (same doc type, already structured/decided), lets an
// optional signature image be attached when the template has a signature field.
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Download,
  FileWarning,
  Loader2,
  PenLine,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  ApiError,
  downloadFile,
  generateTemplateOutput,
  listDocuments,
  signTemplateOutput,
  updateTemplate,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  DocumentStatus,
  DocumentSummary,
  GeneratedSignResult,
  GenerateOutputFile,
  GenerateResult,
  TemplateDetail,
} from "@/lib/types";

const STATUS_LABEL: Partial<Record<DocumentStatus, string>> = {
  structured: "Structured",
  decided: "Decided",
};

// Formats the generator can emit. Kept in sync with the backend's supported set.
const OUTPUT_FORMATS = ["pdf", "docx"] as const;

function isEligible(
  doc: DocumentSummary,
  docType: TemplateDetail["doc_type"],
): boolean {
  return (
    doc.doc_type === docType &&
    (doc.status === "structured" || doc.status === "decided")
  );
}

// A signature can be stamped when the template has a signature form field OR its
// rich-HTML body carries a `data-signature` image marker.
function hasSignatureTarget(template: TemplateDetail): boolean {
  return (
    template.form_fields.some((f) => f.kind === "signature") ||
    (template.html_body?.includes("data-signature") ?? false)
  );
}

// Prefer the per-format outputs; fall back to the legacy single-file fields.
function resultOutputs(result: GenerateResult): GenerateOutputFile[] {
  if (result.outputs && result.outputs.length > 0) return result.outputs;
  return [
    { format: "pdf", output_id: result.output_id, output_url: result.output_url },
  ];
}

function SignaturePicker({
  file,
  onPick,
  onClear,
  disabled,
}: {
  file: File | null;
  onPick: (f: File) => void;
  onClear: () => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-2">
      <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        Signature image (optional)
      </label>
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          disabled={disabled}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onPick(f);
            e.target.value = "";
          }}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
        >
          Choose image
        </Button>
        {file ? (
          <span className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
            <span className="truncate" title={file.name}>
              {file.name}
            </span>
            <button
              type="button"
              aria-label="Remove signature image"
              disabled={disabled}
              onClick={onClear}
              className="text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none"
            >
              <X className="size-3.5" />
            </button>
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">
            Stamped onto signature fields.
          </span>
        )}
      </div>
    </div>
  );
}

function SigBadge({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
        ok
          ? "bg-approve text-approve-foreground"
          : "bg-flag text-flag-foreground",
      )}
    >
      {ok ? (
        <ShieldCheck className="size-3" />
      ) : (
        <ShieldAlert className="size-3" />
      )}
      {label}
    </span>
  );
}

// The real PAdES seal for one generated PDF output: a "Sign for transmission"
// action that, once signed, shows the validation badges + a link to the signed
// file. This is the cryptographic counterpart to the optional stamped image — the
// document you actually transmit, validatable against a trust chain.
function OutputSigner({
  templateId,
  outputId,
}: {
  templateId: string;
  outputId: string;
}) {
  const [signed, setSigned] = useState<GeneratedSignResult | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSign() {
    setBusy(true);
    try {
      const res = await signTemplateOutput(templateId, outputId);
      setSigned(res);
      toast.success("Generated document signed for transmission");
    } catch (e) {
      toast.error("Signing failed", {
        description:
          e instanceof ApiError ? e.message : "Could not sign the PDF.",
      });
    } finally {
      setBusy(false);
    }
  }

  if (!signed) {
    return (
      <Button size="sm" variant="outline" onClick={handleSign} disabled={busy}>
        {busy ? (
          <Loader2 className="animate-spin" />
        ) : (
          <PenLine />
        )}
        Sign for transmission
      </Button>
    );
  }

  const { validation } = signed;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SigBadge label="Intact" ok={validation.intact} />
      <SigBadge label="Trusted" ok={validation.trusted} />
      <SigBadge label="Valid" ok={validation.valid} />
      <Button
        size="sm"
        onClick={() =>
          downloadFile(
            signed.signed_output_url,
            `${signed.signed_output_id}.pdf`,
          ).catch((e) =>
            toast.error("Download failed", {
              description: e instanceof ApiError ? e.message : String(e),
            }),
          )
        }
      >
        <Download />
        Download signed PDF
      </Button>
    </div>
  );
}

function ResultCard({
  result,
  templateId,
}: {
  result: GenerateResult;
  templateId: string;
}) {
  return (
    <div className="space-y-3 rounded-xl border bg-muted/30 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline" className="border-approve/40 text-approve">
            {result.filled_fields.length} filled
          </Badge>
          {result.skipped_fields.length > 0 && (
            <Badge variant="outline" className="text-muted-foreground">
              {result.skipped_fields.length} skipped
            </Badge>
          )}
          {result.signature_stamped && (
            <Badge variant="outline" className="border-brand/40 text-brand">
              signature stamped
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {resultOutputs(result).map((out) => (
            <Button
              key={out.output_id}
              size="sm"
              onClick={() =>
                downloadFile(
                  out.output_url,
                  `${out.output_id}.${out.format}`,
                ).catch((e) =>
                  toast.error("Download failed", {
                    description: e instanceof ApiError ? e.message : String(e),
                  }),
                )
              }
            >
              <Download />
              Download {out.format.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>

      {/* Outbound digital signing: seal each generated PDF with a real PAdES
          signature (not the legally-worthless stamped image). */}
      {resultOutputs(result)
        .filter((out) => out.format === "pdf")
        .map((out) => (
          <div
            key={out.output_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-background/60 px-3 py-2"
          >
            <span className="text-xs text-muted-foreground">
              Sign the generated PDF for transmission (real PAdES certificate).
            </span>
            <OutputSigner templateId={templateId} outputId={out.output_id} />
          </div>
        ))}

      {result.skipped_fields.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Skipped: {result.skipped_fields.join(", ")}
        </p>
      )}

      {result.warnings.length > 0 && (
        <ul className="space-y-1">
          {result.warnings.map((w, i) => (
            <li
              key={i}
              className="flex items-start gap-1.5 text-xs text-muted-foreground"
            >
              <AlertTriangle className="mt-0.5 size-3 shrink-0 text-review" />
              {w}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function GeneratePanel({ template }: { template: TemplateDetail }) {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [docsError, setDocsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string>("");
  const [signature, setSignature] = useState<File | null>(null);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [formats, setFormats] = useState<string[]>(() =>
    template.output_formats.length > 0 ? template.output_formats : ["pdf"],
  );

  const hasSignatureField = hasSignatureTarget(template);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const all = await listDocuments();
        if (!cancelled)
          setDocs(all.filter((d) => isEligible(d, template.doc_type)));
      } catch (e) {
        if (!cancelled)
          setDocsError(
            e instanceof ApiError ? e.message : "Could not load documents.",
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [template.doc_type]);

  const handleGenerate = async () => {
    if (!selectedId || formats.length === 0) return;
    setGenerating(true);
    try {
      // Persist the chosen output formats so the generator emits them.
      const persisted = new Set(template.output_formats);
      const changed =
        formats.length !== persisted.size || formats.some((f) => !persisted.has(f));
      if (changed) {
        await updateTemplate(template.id, { output_formats: formats });
      }
      const res = await generateTemplateOutput(template.id, {
        documentId: selectedId,
        signatureImage: signature ?? undefined,
      });
      setResult(res);
      toast.success("Output generated");
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Could not generate the PDF.";
      toast.error("Generation failed", { description: msg });
    } finally {
      setGenerating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading documents…
      </div>
    );
  }

  if (docsError) {
    return <p className="text-sm text-flag">{docsError}</p>;
  }

  if (docs.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-center">
        <div className="flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <FileWarning className="size-5" />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-medium">No eligible documents</p>
          <p className="mx-auto max-w-sm text-sm text-muted-foreground text-balance">
            Upload &amp; process a {template.doc_type} first — once it's
            structured you can generate from it here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Source document
        </label>
        <Select value={selectedId} onValueChange={setSelectedId}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Pick a processed document…" />
          </SelectTrigger>
          <SelectContent>
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

      {hasSignatureField && (
        <SignaturePicker
          file={signature}
          onPick={setSignature}
          onClear={() => setSignature(null)}
          disabled={generating}
        />
      )}

      <div className="space-y-2">
        <label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Output formats
        </label>
        <ToggleGroup
          type="multiple"
          variant="outline"
          value={formats}
          onValueChange={(v) => {
            // Keep at least one format selected.
            if (v.length > 0) setFormats(v);
          }}
        >
          {OUTPUT_FORMATS.map((f) => (
            <ToggleGroupItem key={f} value={f} disabled={generating}>
              {f.toUpperCase()}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <Button
        disabled={!selectedId || generating || formats.length === 0}
        onClick={() => void handleGenerate()}
      >
        {generating ? <Loader2 className="animate-spin" /> : <Sparkles />}
        Generate
      </Button>

      {result && <ResultCard result={result} templateId={template.id} />}
    </div>
  );
}
