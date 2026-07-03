// The left-column conversation surface (stateless): an upload section up top (process
// + example docs), then the current clarifying questions as answer boxes, any
// warnings, and a sticky footer. The footer fires the next turn while the design is
// in progress; once the assistant marks the spec done it swaps Send for a "Create
// type" button that hands off to the parent's onCreate.
import { createRef, useMemo } from "react";
import { AlertTriangle, Loader2, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { AnswerTextbox } from "./AnswerTextbox";
import { IngestDropzone } from "./IngestDropzone";
import type { WizardCoreState } from "./types";

interface QAPanelProps {
  state: WizardCoreState;
  onAnswerChange: (index: number, text: string) => void;
  onAnswerSave: (index: number) => void;
  onSend: () => void;
  ingestingFiles: string[];
  onIngest: (file: File, kind: "process" | "example") => void;
  onRemoveDoc: (list: "process" | "example", filename: string) => void;
  onCreate: () => void;
  creating: boolean;
  createError: string | null;
  /** True when the assistant returned no questions but isn't done — show a free-form box. */
  awaitingContinue: boolean;
  freeform: string;
  onFreeformChange: (text: string) => void;
}

export function QAPanel({
  state,
  onAnswerChange,
  onAnswerSave,
  onSend,
  ingestingFiles,
  onIngest,
  onRemoveDoc,
  onCreate,
  creating,
  createError,
  awaitingContinue,
  freeform,
  onFreeformChange,
}: QAPanelProps) {
  const { currentQuestions, answers, loading, warnings, done, draftDocType } =
    state;

  // One ref per question; box `i` advances focus to box `i + 1` on Ctrl+Enter.
  const refs = useMemo(
    () =>
      currentQuestions.map(() => createRef<HTMLTextAreaElement | null>()),
    [currentQuestions],
  );

  // In the continue/finalize state Send is always allowed (an empty send nudges the
  // assistant to finalize); otherwise it needs at least one non-empty answer.
  const sendDisabled =
    loading ||
    done ||
    (!awaitingContinue && answers.every((a) => a.text.trim() === ""));

  const showSkeletons = loading && currentQuestions.length === 0;
  const showCreate = done && draftDocType !== null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 space-y-4 p-4">
        <div className="grid grid-cols-2 gap-3 rounded-lg border bg-muted/20 p-3">
          <IngestDropzone
            label="Process documents"
            kind="process"
            docs={state.processDocs}
            ingestingFiles={ingestingFiles}
            onFile={(file) => onIngest(file, "process")}
            onRemove={(filename) => onRemoveDoc("process", filename)}
          />
          <IngestDropzone
            label="Example documents"
            kind="example"
            docs={state.exampleDocs}
            ingestingFiles={ingestingFiles}
            onFile={(file) => onIngest(file, "example")}
            onRemove={(filename) => onRemoveDoc("example", filename)}
          />
        </div>

        {showSkeletons && (
          <div className="space-y-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="space-y-1.5">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-16 w-full" />
              </div>
            ))}
          </div>
        )}

        {!showSkeletons &&
          currentQuestions.map((question, i) => (
            <AnswerTextbox
              key={i}
              question={question}
              answer={answers[i] ?? { text: "", saved: false }}
              onChange={(text) => onAnswerChange(i, text)}
              onSave={() => onAnswerSave(i)}
              ref={refs[i]}
              textareaRef={refs[i + 1]}
              disabled={loading || done}
            />
          ))}

        {awaitingContinue && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              The assistant didn&apos;t ask anything more.
            </label>
            <p className="text-xs text-muted-foreground">
              Add any extra detail below, or just press Send to have it finalize
              the spec.
            </p>
            <Textarea
              value={freeform}
              placeholder="Add detail, or leave blank and send to finalize…"
              onChange={(e) => onFreeformChange(e.target.value)}
            />
          </div>
        )}

        {warnings.length > 0 && (
          <div className="space-y-1 rounded-lg border border-review/40 bg-review-muted/40 p-3 text-xs text-foreground">
            <div className="flex items-center gap-1.5 font-medium">
              <AlertTriangle className="size-3.5 text-review" />
              Warnings
            </div>
            <ul className="list-disc pl-5">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}

        {showCreate && (
          <p className="rounded-lg border border-approve/40 bg-approve-muted/40 p-3 text-xs text-foreground">
            The spec is ready — create it and open the editor to fine-tune.
          </p>
        )}

        {createError && (
          <p className="rounded-lg border border-flag/40 bg-flag-muted/40 p-3 text-xs text-foreground">
            {createError}
          </p>
        )}
      </div>

      <div className="sticky bottom-0 border-t bg-background p-3">
        {showCreate ? (
          <Button
            type="button"
            className="w-full"
            disabled={creating}
            onClick={onCreate}
          >
            {creating ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            Create type
          </Button>
        ) : (
          <Button
            type="button"
            className="w-full"
            disabled={sendDisabled}
            onClick={onSend}
          >
            <Send className="size-4" />
            Send
          </Button>
        )}
      </div>
    </div>
  );
}
