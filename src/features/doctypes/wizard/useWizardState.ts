// Wizard state container. The reducer is a pure function defined OUTSIDE the hook
// (so it can be unit-tested in isolation), and `sendTurn` drives one stateless
// round-trip against POST /doc-types/assist: it assembles the labeled user message
// from the current questions + answers, re-sends the whole transcript, and folds
// the response back into state.
import { useCallback, useReducer } from "react";
import { toast } from "sonner";
import { assistTurn } from "@/lib/api";
import type { AssistMessage } from "@/lib/doc-type-schema";
import type { AnswerState, WizardAction, WizardCoreState } from "./types";

export const initialWizardState: WizardCoreState = {
  messages: [],
  processDocs: [],
  exampleDocs: [],
  specMarkdown: "",
  annotations: [],
  currentQuestions: [],
  answers: [],
  loading: false,
  warnings: [],
  done: false,
  draftDocType: null,
  error: null,
};

function freshAnswers(count: number): AnswerState[] {
  return Array.from({ length: count }, () => ({ text: "", saved: false }));
}

export function wizardReducer(
  state: WizardCoreState,
  action: WizardAction,
): WizardCoreState {
  switch (action.type) {
    case "TURN_START":
      return {
        ...state,
        loading: true,
        error: null,
        warnings: [],
        answers: freshAnswers(state.answers.length),
      };

    case "TURN_SUCCESS": {
      const { response, userMessage } = action;
      const assistantMessage: AssistMessage = {
        role: "assistant",
        content: response.questions.join("\n"),
      };
      return {
        ...state,
        loading: false,
        error: null,
        messages: [...state.messages, userMessage, assistantMessage],
        currentQuestions: response.questions,
        answers: freshAnswers(response.questions.length),
        specMarkdown: response.updated_spec_markdown,
        warnings: response.warnings,
        done: response.done,
        draftDocType: response.draft_doctype,
      };
    }

    case "TURN_ERROR":
      return { ...state, loading: false, error: action.error };

    case "ANNOTATION_CAPTURED":
      return { ...state, annotations: [...state.annotations, action.entry] };

    case "DOC_ADD": {
      const key = action.list === "process" ? "processDocs" : "exampleDocs";
      return { ...state, [key]: [...state[key], action.doc] };
    }

    case "DOC_REMOVE": {
      const key = action.list === "process" ? "processDocs" : "exampleDocs";
      return {
        ...state,
        [key]: state[key].filter((_, i) => i !== action.index),
      };
    }

    case "ANSWER_SET":
      return {
        ...state,
        answers: state.answers.map((a, i) =>
          i === action.index ? { ...a, text: action.text } : a,
        ),
      };

    case "ANSWER_SAVE":
      return {
        ...state,
        answers: state.answers.map((a, i) =>
          i === action.index ? { ...a, saved: true } : a,
        ),
      };

    case "RESET":
      return initialWizardState;

    default:
      return state;
  }
}

/** Assemble a labeled "Q1: …\nA: …" block from the current questions + answers. */
function buildUserContent(questions: string[], answers: string[]): string {
  if (questions.length === 0) {
    return "Let's design a new document type. Please ask me what you need to know.";
  }
  return questions
    .map((q, i) => {
      const answer = answers[i]?.trim() ? answers[i].trim() : "(no answer)";
      return `Q${i + 1}: ${q}\nA: ${answer}`;
    })
    .join("\n\n");
}

export function useWizardState() {
  const [state, dispatch] = useReducer(wizardReducer, initialWizardState);

  const sendTurn = useCallback(
    async (answers: string[]): Promise<void> => {
      if (state.loading) return;

      const userMessage: AssistMessage = {
        role: "user",
        content: buildUserContent(state.currentQuestions, answers),
      };

      dispatch({ type: "TURN_START" });
      try {
        const response = await assistTurn({
          messages: [...state.messages, userMessage],
          process_docs: state.processDocs.map((d) => d.text),
          example_docs: state.exampleDocs.map((d) => d.text),
          spec_markdown: state.specMarkdown,
          annotations: state.annotations as unknown as Record<
            string,
            unknown
          >[],
        });
        dispatch({ type: "TURN_SUCCESS", response, userMessage });
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        dispatch({ type: "TURN_ERROR", error: message });
        toast.error("Wizard turn failed", { description: message });
      }
    },
    [state],
  );

  return { state, dispatch, sendTurn };
}
