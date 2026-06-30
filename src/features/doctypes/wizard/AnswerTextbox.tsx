// One clarifying question + its answer field. Enter inserts a newline (native);
// Ctrl+Enter marks the answer saved and advances focus to the NEXT box (whose ref
// the parent passes in via `textareaRef`). The box stays editable after saving.
import { CheckCircle2 } from "lucide-react";
import { forwardRef } from "react";
import type { RefObject } from "react";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { AnswerState } from "./types";

interface AnswerTextboxProps {
  question: string;
  answer: AnswerState;
  onChange: (text: string) => void;
  onSave: () => void;
  /** Ref of the NEXT answer box, focused on Ctrl+Enter (undefined for the last). */
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  disabled?: boolean;
}

export const AnswerTextbox = forwardRef<
  HTMLTextAreaElement,
  AnswerTextboxProps
>(function AnswerTextbox(
  { question, answer, onChange, onSave, textareaRef, disabled },
  ref,
) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-start gap-1.5">
        <label className="flex-1 text-sm font-medium text-foreground">
          {question}
        </label>
        {answer.saved && (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-approve" />
        )}
      </div>
      <Textarea
        ref={ref}
        value={answer.text}
        disabled={disabled}
        placeholder="Type your answer… (Ctrl+Enter to save & advance)"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.ctrlKey && e.key === "Enter") {
            e.preventDefault();
            onSave();
            textareaRef?.current?.focus?.();
          }
        }}
        className={cn(
          answer.saved && "border-approve ring-2 ring-approve/30",
        )}
      />
    </div>
  );
});
