// Two-step dialog for creating a template: pick a doc type, then name it and
// start blank. The form's state lives in WizardForm, which is keyed by `open`
// so it remounts (and resets) every time the dialog is reopened.
import { useState } from "react";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, createTemplate } from "@/lib/api";
import type { DocType, TemplateDetail } from "@/lib/types";
import { DocTypeToggle } from "@/features/upload/DocTypeToggle";

function WizardForm({
  onCreated,
}: {
  onCreated: (t: TemplateDetail) => void;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [docType, setDocType] = useState<DocType>("invoice");
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);

  const handleCreate = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setPending(true);
    try {
      const detail = await createTemplate({ name: trimmed, doc_type: docType });
      onCreated(detail);
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Could not create template.";
      toast.error(msg);
      setPending(false);
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>New template</DialogTitle>
        <DialogDescription>
          {step === 1
            ? "Which kind of document is this template for?"
            : "Give the template a name to get started."}
        </DialogDescription>
      </DialogHeader>

      {step === 1 ? (
        <div className="space-y-2">
          <Label className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Document type
          </Label>
          <DocTypeToggle value={docType} onChange={setDocType} />
        </div>
      ) : (
        <div className="space-y-2">
          <Label htmlFor="template-name">Name</Label>
          <Input
            id="template-name"
            autoFocus
            value={name}
            placeholder="e.g. Standard invoice"
            disabled={pending}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleCreate();
            }}
          />
        </div>
      )}

      <DialogFooter>
        {step === 1 ? (
          <Button onClick={() => setStep(2)}>
            Continue
            <ArrowRight />
          </Button>
        ) : (
          <>
            <Button
              variant="outline"
              disabled={pending}
              onClick={() => setStep(1)}
            >
              <ArrowLeft />
              Back
            </Button>
            <Button
              disabled={pending || name.trim() === ""}
              onClick={() => void handleCreate()}
            >
              {pending && <Loader2 className="animate-spin" />}
              Start blank
            </Button>
          </>
        )}
      </DialogFooter>
    </>
  );
}

export function TemplateWizard({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (t: TemplateDetail) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by `open` so the form fully resets whenever it reopens. */}
        <WizardForm key={open ? "open" : "closed"} onCreated={onCreated} />
      </DialogContent>
    </Dialog>
  );
}
