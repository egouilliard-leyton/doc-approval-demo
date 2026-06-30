// The "Create with AI" wizard shell. A two-column dialog: the left column is the
// Q&A conversation + the upload section (scrollable), the right column the live spec
// preview (markdown, or the Plannotator annotation iframe while a session is live).
// The first turn fires once on open (a ref guards React strict-mode's double mount);
// if it fails, the Q&A column shows the error + a Retry that re-runs the opener.
// When the assistant marks the spec done, the footer's "Create type" button commits
// the draft via createDocType and hands the new type back through onCreated so the
// parent can open the builder/editor on it.
import { useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ApiError, createDocType } from "@/lib/api";
import type { DocTypeResponse } from "@/lib/doc-type-schema";
import { useWizardState } from "./useWizardState";
import { useIngest } from "./useIngest";
import { useAnnotateSession } from "./useAnnotateSession";
import { QAPanel } from "./QAPanel";
import { SpecPanel } from "./SpecPanel";
import { findDocIndex, nextAnnotationEntry } from "./wizard-helpers";

interface CreateWithAIDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (created: DocTypeResponse) => void;
}

export function CreateWithAIDialog({
  open,
  onClose,
  onCreated,
}: CreateWithAIDialogProps) {
  const { state, dispatch, sendTurn } = useWizardState();
  const { ingestingFiles, handleIngest } = useIngest();
  const annotateSession = useAnnotateSession();
  const startedRef = useRef(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const runInitialTurn = () => {
    void sendTurn([]);
  };

  // Fire the opener exactly once per open. The ref guards against strict-mode's
  // double mount firing two opening turns.
  useEffect(() => {
    if (open && !startedRef.current) {
      startedRef.current = true;
      runInitialTurn();
    }
    if (!open) {
      startedRef.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Tear down any live annotation poll if the dialog unmounts.
  const { cancel: cancelAnnotate } = annotateSession;
  useEffect(() => {
    return () => cancelAnnotate();
  }, [cancelAnnotate]);

  const handleSend = () => {
    void sendTurn(state.answers.map((a) => a.text));
  };

  const handleIngestFile = (file: File, kind: "process" | "example") => {
    void handleIngest(file, kind, (doc) =>
      dispatch({ type: "DOC_ADD", list: kind, doc }),
    );
  };

  const handleRemoveDoc = (list: "process" | "example", filename: string) => {
    const docs = list === "process" ? state.processDocs : state.exampleDocs;
    const index = findDocIndex(docs, filename);
    if (index !== -1) dispatch({ type: "DOC_REMOVE", list, index });
  };

  const handleAnnotate = () => {
    void annotateSession.start(state.specMarkdown, (decision, feedback) =>
      dispatch({
        type: "ANNOTATION_CAPTURED",
        entry: nextAnnotationEntry(state.annotations, decision, feedback),
      }),
    );
  };

  const handleCreate = async () => {
    if (!state.draftDocType) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await createDocType(state.draftDocType);
      toast.success(`Created “${created.label}”`);
      onCreated(created);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setCreateError(
          "A type with this name already exists — open the editor to rename it.",
        );
      } else if (e instanceof ApiError && e.status === 422) {
        setCreateError(e.message);
      } else {
        toast.error("Couldn't create the type", {
          description: e instanceof ApiError ? e.message : String(e),
        });
      }
    } finally {
      setCreating(false);
    }
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      annotateSession.cancel();
      onClose();
    }
  };

  const initialError =
    state.error !== null && state.messages.length === 0 && !state.loading;

  const rightPanelMode = annotateSession.session ? "iframe" : "markdown";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex h-[85vh] flex-col gap-0 p-0 sm:max-w-5xl">
        <DialogHeader className="border-b px-4 py-3">
          <DialogTitle>Create document type with AI</DialogTitle>
          <DialogDescription>
            Answer a few questions and the assistant will draft a document-type
            specification for you.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-row">
          <div className="flex w-[420px] shrink-0 flex-col border-r">
            <ScrollArea className="min-h-0 flex-1">
              {initialError ? (
                <div className="space-y-3 p-6 text-center text-sm text-muted-foreground">
                  <div className="flex items-center justify-center gap-1.5 text-foreground">
                    <AlertTriangle className="size-4 text-flag" />
                    Couldn&apos;t start the wizard
                  </div>
                  <p>{state.error}</p>
                  <Button variant="outline" size="sm" onClick={runInitialTurn}>
                    Retry
                  </Button>
                </div>
              ) : (
                <QAPanel
                  state={state}
                  onAnswerChange={(index, text) =>
                    dispatch({ type: "ANSWER_SET", index, text })
                  }
                  onAnswerSave={(index) =>
                    dispatch({ type: "ANSWER_SAVE", index })
                  }
                  onSend={handleSend}
                  ingestingFiles={ingestingFiles}
                  onIngest={handleIngestFile}
                  onRemoveDoc={handleRemoveDoc}
                  onCreate={() => void handleCreate()}
                  creating={creating}
                  createError={createError}
                />
              )}
            </ScrollArea>
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            <SpecPanel
              specMarkdown={state.specMarkdown}
              loading={state.loading}
              rightPanelMode={rightPanelMode}
              sessionUrl={annotateSession.session?.url}
              annotating={annotateSession.annotating}
              hasAnnotated={state.annotations.length > 0}
              onAnnotate={handleAnnotate}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
