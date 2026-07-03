// Generate a filled PDF from the template + one processed source document.
// Lists eligible documents (same doc type, already structured/decided), lets an
// optional signature image be attached when the template has a signature field.
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Download,
  FileWarning,
  Loader2,
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
import {
  ApiError,
  fileUrl,
  generateTemplateOutput,
  listDocuments,
} from "@/lib/api";
import type {
  DocumentStatus,
  DocumentSummary,
  GenerateResult,
  TemplateDetail,
} from "@/lib/types";

const STATUS_LABEL: Partial<Record<DocumentStatus, string>> = {
  structured: "Structured",
  decided: "Decided",
};

function isEligible(
  doc: DocumentSummary,
  docType: TemplateDetail["doc_type"],
): boolean {
  return (
    doc.doc_type === docType &&
    (doc.status === "structured" || doc.status === "decided")
  );
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

function ResultCard({ result }: { result: GenerateResult }) {
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
        <Button size="sm" asChild>
          <a
            href={fileUrl(result.output_url)}
            target="_blank"
            rel="noreferrer"
            download
          >
            <Download />
            Open generated PDF
          </a>
        </Button>
      </div>

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

  const hasSignatureField = template.form_fields.some(
    (f) => f.kind === "signature",
  );

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
    if (!selectedId) return;
    setGenerating(true);
    try {
      const res = await generateTemplateOutput(template.id, {
        documentId: selectedId,
        signatureImage: signature ?? undefined,
      });
      setResult(res);
      toast.success("PDF generated");
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

      <Button
        disabled={!selectedId || generating}
        onClick={() => void handleGenerate()}
      >
        {generating ? <Loader2 className="animate-spin" /> : <Sparkles />}
        Generate PDF
      </Button>

      {result && <ResultCard result={result} />}
    </div>
  );
}
