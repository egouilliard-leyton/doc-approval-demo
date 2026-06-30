// Pure-reducer tests for the wizard state machine. This file imports ONLY the
// reducer + initial state and the plain types — never a wizard .tsx component — so
// the node test env never has to load react-markdown's ESM-only stack.
import { describe, expect, it } from "vitest";
import type { AssistResponse, DocTypeCreate } from "@/lib/doc-type-schema";
import type { AnswerState, WizardCoreState } from "./types";
import { initialWizardState, wizardReducer } from "./useWizardState";

function makeResponse(overrides: Partial<AssistResponse> = {}): AssistResponse {
  return {
    questions: ["What is the doc type called?", "What fields matter?"],
    updated_spec_markdown: "# Spec\n\nContent",
    done: false,
    draft_doctype: null,
    warnings: [],
    ...overrides,
  };
}

function withAnswers(answers: AnswerState[]): WizardCoreState {
  return { ...initialWizardState, answers };
}

describe("wizardReducer", () => {
  it("has a sane initial state", () => {
    expect(initialWizardState.messages).toEqual([]);
    expect(initialWizardState.loading).toBe(false);
    expect(initialWizardState.done).toBe(false);
    expect(initialWizardState.draftDocType).toBeNull();
    expect(initialWizardState.error).toBeNull();
  });

  it("TURN_START sets loading, clears warnings/error, resets answers", () => {
    const start: WizardCoreState = {
      ...initialWizardState,
      warnings: ["old warning"],
      error: "old error",
      answers: [
        { text: "a", saved: true },
        { text: "b", saved: false },
      ],
    };
    const next = wizardReducer(start, { type: "TURN_START" });
    expect(next.loading).toBe(true);
    expect(next.warnings).toEqual([]);
    expect(next.error).toBeNull();
    expect(next.answers).toEqual([
      { text: "", saved: false },
      { text: "", saved: false },
    ]);
  });

  it("TURN_SUCCESS folds in the response and appends user+assistant messages", () => {
    const draft: DocTypeCreate = {
      name: "memo",
      label: "Memo",
      extraction_definition: {},
      rule_definition: {},
    };
    const response = makeResponse({ done: true, draft_doctype: draft });
    const userMessage = { role: "user" as const, content: "Q1: ...\nA: ..." };

    const next = wizardReducer(
      { ...initialWizardState, loading: true },
      { type: "TURN_SUCCESS", response, userMessage },
    );

    expect(next.loading).toBe(false);
    expect(next.currentQuestions).toEqual(response.questions);
    expect(next.specMarkdown).toBe(response.updated_spec_markdown);
    expect(next.done).toBe(true);
    expect(next.draftDocType).toEqual(draft);
    // user message + assistant message (questions joined by newline)
    expect(next.messages).toHaveLength(2);
    expect(next.messages[0]).toEqual(userMessage);
    expect(next.messages[1]).toEqual({
      role: "assistant",
      content: response.questions.join("\n"),
    });
    // answers reset to the new question count
    expect(next.answers).toHaveLength(response.questions.length);
    expect(next.answers.every((a) => a.text === "" && !a.saved)).toBe(true);
  });

  it("TURN_ERROR sets error and clears loading", () => {
    const next = wizardReducer(
      { ...initialWizardState, loading: true },
      { type: "TURN_ERROR", error: "boom" },
    );
    expect(next.error).toBe("boom");
    expect(next.loading).toBe(false);
  });

  it("ANSWER_SET mutates only the targeted index", () => {
    const start = withAnswers([
      { text: "", saved: false },
      { text: "", saved: false },
    ]);
    const next = wizardReducer(start, {
      type: "ANSWER_SET",
      index: 1,
      text: "hello",
    });
    expect(next.answers[0]).toEqual({ text: "", saved: false });
    expect(next.answers[1]).toEqual({ text: "hello", saved: false });
  });

  it("ANSWER_SAVE flags only the targeted index", () => {
    const start = withAnswers([
      { text: "x", saved: false },
      { text: "y", saved: false },
    ]);
    const next = wizardReducer(start, { type: "ANSWER_SAVE", index: 0 });
    expect(next.answers[0].saved).toBe(true);
    expect(next.answers[1].saved).toBe(false);
  });

  it("DOC_ADD / DOC_REMOVE update the right list", () => {
    const added = wizardReducer(initialWizardState, {
      type: "DOC_ADD",
      list: "process",
      doc: { text: "abc", filename: "p.txt" },
    });
    expect(added.processDocs).toHaveLength(1);
    expect(added.exampleDocs).toHaveLength(0);

    const exampleAdded = wizardReducer(added, {
      type: "DOC_ADD",
      list: "example",
      doc: { text: "def", filename: "e.txt" },
    });
    expect(exampleAdded.exampleDocs).toHaveLength(1);

    const removed = wizardReducer(exampleAdded, {
      type: "DOC_REMOVE",
      list: "process",
      index: 0,
    });
    expect(removed.processDocs).toHaveLength(0);
    expect(removed.exampleDocs).toHaveLength(1);
  });

  it("ANNOTATION_CAPTURED appends an annotation entry", () => {
    const entry = { decision: "edit", feedback: "tighten it", round: 1 };
    const next = wizardReducer(initialWizardState, {
      type: "ANNOTATION_CAPTURED",
      entry,
    });
    expect(next.annotations).toEqual([entry]);
  });
});
