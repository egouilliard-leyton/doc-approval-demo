// Pure-logic tests for the wizard container helpers. Imports ONLY the helper module
// + plain types — never a wizard .tsx component — so the node test env never loads
// react-markdown's ESM-only stack.
import { describe, expect, it } from "vitest";
import type { AnnotationEntry, IngestedDoc } from "./types";
import { findDocIndex, nextAnnotationEntry } from "./wizard-helpers";

describe("nextAnnotationEntry", () => {
  it("numbers the first round 1", () => {
    expect(nextAnnotationEntry([], "edit", "tighten it")).toEqual({
      decision: "edit",
      feedback: "tighten it",
      round: 1,
    });
  });

  it("increments the round off the existing list", () => {
    const existing: AnnotationEntry[] = [
      { decision: "edit", feedback: "a", round: 1 },
      { decision: "approve", feedback: "b", round: 2 },
    ];
    expect(nextAnnotationEntry(existing, "edit", "c")).toEqual({
      decision: "edit",
      feedback: "c",
      round: 3,
    });
  });
});

describe("findDocIndex", () => {
  const docs: IngestedDoc[] = [
    { text: "x", filename: "a.pdf" },
    { text: "y", filename: "b.txt" },
  ];

  it("finds an existing filename", () => {
    expect(findDocIndex(docs, "b.txt")).toBe(1);
  });

  it("returns -1 when absent", () => {
    expect(findDocIndex(docs, "missing.pdf")).toBe(-1);
  });
});
