// State + action shapes for the "Create with AI" doc-type wizard. The backend is
// stateless, so the frontend holds the full transcript and re-sends it each turn;
// these types describe everything the wizard reducer tracks between turns.
import type {
  AssistMessage,
  AssistResponse,
  DocTypeCreate,
} from "@/lib/doc-type-schema";

/** A document ingested to plain text (process or example doc). */
export interface IngestedDoc {
  text: string;
  filename: string;
}

/** One annotation captured from a Plannotator review round (Wave 2). */
export interface AnnotationEntry {
  decision: string;
  feedback: string;
  round: number;
}

/** Per-question answer draft, with a "saved" flag for the Ctrl+Enter UX. */
export interface AnswerState {
  text: string;
  saved: boolean;
}

/** Everything the wizard tracks across turns. */
export interface WizardCoreState {
  messages: AssistMessage[];
  processDocs: IngestedDoc[];
  exampleDocs: IngestedDoc[];
  specMarkdown: string;
  annotations: AnnotationEntry[];
  currentQuestions: string[];
  answers: AnswerState[];
  loading: boolean;
  warnings: string[];
  done: boolean;
  draftDocType: DocTypeCreate | null;
  error: string | null;
}

export type WizardAction =
  | { type: "TURN_START" }
  | { type: "TURN_SUCCESS"; response: AssistResponse; userMessage: AssistMessage }
  | { type: "TURN_ERROR"; error: string }
  | { type: "ANNOTATION_CAPTURED"; entry: AnnotationEntry }
  | { type: "DOC_ADD"; list: "process" | "example"; doc: IngestedDoc }
  | { type: "DOC_REMOVE"; list: "process" | "example"; index: number }
  | { type: "ANSWER_SET"; index: number; text: string }
  | { type: "ANSWER_SAVE"; index: number }
  | { type: "RESET" };
