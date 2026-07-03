// The "Create with AI" wizard shell. A two-column dialog: the left column is the
// Q&A conversation + the upload section (scrollable), the right column the live spec
// preview (markdown, or the Plannotator annotation iframe while a session is live).
// The first turn fires once on open (a ref guards React strict-mode's double mount);
// if it fails, the Q&A column shows the error + a Retry that re-runs the opener.
// When the assistant marks the spec done, the footer's "Create type" button commits
// the draft via createDocType and hands the new type back through onCreated so the
// parent can open the builder/editor on it.
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ApiError, createDocType } from "@/lib/api";
import type { DocTypeResponse } from "@/lib/doc-type-schema";
import { useWizardState } from "./useWizardState";
import { useIngest } from "./useIngest";
import { useAnnotateSession } from "./useAnnotateSession";
import { QAPanel } from "./QAPanel";
import { SpecPanel } from "./SpecPanel";
import { findDocIndex, nextAnnotationEntry } from "./wizard-helpers";
import { INITIAL_QUESTIONS, INITIAL_SPEC_TEMPLATE } from "./wizard-template";

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
  const [freeform, setFreeform] = useState("");

  // The assistant sometimes returns a full spec with no follow-up questions yet isn't
  // done — that used to strand the turn (no answer boxes, Send disabled). In that state
  // we offer a free-form "continue / finalize" box instead.
  const awaitingContinue =
    !state.loading && !state.done && state.currentQuestions.length === 0;

  // Opening the wizard pre-loads the always-the-same spec template + first questions
  // instead of calling the assistant. The AI only runs from the first Send onward.
  const seedInitial = () => {
    dispatch({
      type: "SEED_INITIAL",
      questions: INITIAL_QUESTIONS,
      specMarkdown: INITIAL_SPEC_TEMPLATE,
    });
  };

  // Seed exactly once per open. The ref guards against strict-mode's double mount.
  useEffect(() => {
    if (open && !startedRef.current) {
      startedRef.current = true;
      seedInitial();
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
    if (awaitingContinue) {
      void sendTurn([], freeform);
      setFreeform("");
      return;
    }
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

  const rightPanelMode = annotateSession.session ? "iframe" : "markdown";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex h-[92vh] w-[96vw] flex-col gap-0 p-0 sm:max-w-[1700px]">
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
              <QAPanel
                state={state}
                onAnswerChange={(index, text) =>
                  dispatch({ type: "ANSWER_SET", index, text })
                }
                onAnswerSave={(index) => dispatch({ type: "ANSWER_SAVE", index })}
                onSend={handleSend}
                ingestingFiles={ingestingFiles}
                onIngest={handleIngestFile}
                onRemoveDoc={handleRemoveDoc}
                onCreate={() => void handleCreate()}
                creating={creating}
                createError={createError}
                awaitingContinue={awaitingContinue}
                freeform={freeform}
                onFreeformChange={setFreeform}
              />
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
