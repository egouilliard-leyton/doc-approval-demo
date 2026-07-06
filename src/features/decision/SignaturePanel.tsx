import { useEffect, useState } from "react";
import {
  Download,
  Loader2,
  PenLine,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ApiError, fileUrl, getSign, runSign, validateSignature } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/format";
import type { DecisionResult, SignResult } from "@/lib/types";

const TONE_CARD: Record<"approve" | "flag", string> = {
  approve: "border-approve/40 bg-approve/[0.06]",
  flag: "border-flag/40 bg-flag/[0.06]",
};

const TONE_BADGE: Record<"approve" | "flag", string> = {
  approve: "bg-approve text-approve-foreground",
  flag: "bg-flag text-flag-foreground",
};

function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Unexpected error";
}

function StatusBadge({ label, ok }: { label: string; ok: boolean }) {
  const tone = ok ? "approve" : "flag";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium",
        TONE_BADGE[tone],
      )}
    >
      {ok ? <ShieldCheck className="size-3.5" /> : <ShieldAlert className="size-3.5" />}
      {label}
    </span>
  );
}

export function SignaturePanel({
  documentId,
  decision,
}: {
  documentId: string;
  decision: DecisionResult;
}) {
  const [sign, setSign] = useState<SignResult | null>(null);
  const [busy, setBusy] = useState(false);

  // Hydrate the persisted signature, and re-sync whenever the decision changes. A
  // signature is only valid for the decision it attested: re-deciding invalidates it
  // server-side (the backend drops the stored sign result + signed PDF), so a 404 here
  // means "never signed OR just invalidated" — clear the card rather than leave a stale
  // seal (and a dead download link) on screen. Depending on `decision` re-runs this on
  // every re-decide; signing/re-verifying don't change `decision`, so they keep their
  // freshly-set state.
  useEffect(() => {
    let active = true;
    getSign(documentId)
      .then((result) => {
        if (active) setSign(result);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) {
          if (active) setSign(null);
          return;
        }
        if (active) toast.error("Could not load signature", { description: errMessage(e) });
      });
    return () => {
      active = false;
    };
  }, [documentId, decision]);

  if (decision.decision !== "approve") {
    return (
      <p className="rounded-2xl border border-dashed px-4 py-3 text-sm text-muted-foreground">
        Only approved documents can be signed for transmission.
      </p>
    );
  }

  async function handleSign() {
    setBusy(true);
    try {
      const result = await runSign(documentId);
      setSign(result);
      toast.success("Document signed for transmission");
    } catch (e) {
      toast.error("Signing failed", { description: errMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  async function handleReverify() {
    setBusy(true);
    try {
      const validation = await validateSignature(documentId);
      setSign((prev) => (prev ? { ...prev, validation } : prev));
      if (validation.valid) {
        toast.success("Signature verified", { description: validation.summary });
      } else {
        toast.error("Signature invalid", { description: validation.summary });
      }
    } catch (e) {
      toast.error("Verification failed", { description: errMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  if (!sign) {
    return (
      <div className="space-y-3">
        <Button onClick={handleSign} disabled={busy}>
          {busy ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <PenLine className="size-4" />
          )}
          Sign for transmission
        </Button>
        <p className="text-xs text-muted-foreground">
          Signs the original PDF with a server-held demo certificate (PAdES). Not
          a production/qualified certificate.
        </p>
      </div>
    );
  }

  const { validation } = sign;
  const tone = validation.valid ? "approve" : "flag";
  const signedAt = validation.signed_at ? formatDate(validation.signed_at) : null;

  return (
    <div className={cn("space-y-4 rounded-2xl border p-5", TONE_CARD[tone])}>
      <div className="flex items-center gap-3">
        <div
          className={cn(
            "flex size-12 items-center justify-center rounded-xl",
            TONE_BADGE[tone],
          )}
        >
          {validation.valid ? (
            <ShieldCheck className="size-6" />
          ) : (
            <ShieldAlert className="size-6" />
          )}
        </div>
        <div>
          <div className="text-2xl font-semibold tracking-tight">
            {validation.valid ? "Signed" : "Signature issue"}
          </div>
          <div className="font-mono text-xs text-muted-foreground">
            {sign.provider} · {sign.engine_version} · {sign.level}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <StatusBadge label="Intact" ok={validation.intact} />
        <StatusBadge label="Trusted" ok={validation.trusted} />
        <StatusBadge label="Valid" ok={validation.valid} />
      </div>

      <dl className="space-y-1.5 text-sm">
        {validation.signer && (
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-muted-foreground">Signer</dt>
            <dd className="text-foreground/90">{validation.signer.common_name}</dd>
          </div>
        )}
        <div className="flex gap-2">
          <dt className="w-28 shrink-0 text-muted-foreground">Level</dt>
          <dd className="text-foreground/90">{validation.level}</dd>
        </div>
        {validation.trust_anchor && (
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-muted-foreground">Trust anchor</dt>
            <dd className="text-foreground/90">{validation.trust_anchor}</dd>
          </div>
        )}
        {signedAt && (
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-muted-foreground">Signed at</dt>
            <dd className="text-foreground/90">{signedAt}</dd>
          </div>
        )}
        {validation.summary && (
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-muted-foreground">Summary</dt>
            <dd className="font-mono text-xs text-foreground/90">
              {validation.summary}
            </dd>
          </div>
        )}
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <Button asChild>
          <a href={fileUrl(sign.signed_pdf_url)} download>
            <Download className="size-4" />
            Download signed PDF
          </a>
        </Button>
        <Button variant="outline" onClick={handleReverify} disabled={busy}>
          {busy ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <ShieldCheck className="size-4" />
          )}
          Re-verify signature
        </Button>
      </div>
    </div>
  );
}
