// Pure helpers shared by the wizard container. Kept free of React/component imports
// so they can be unit-tested under the node vitest env (react-markdown is ESM-only
// and breaks there, so component .tsx files must stay out of tests).
import type { AnnotationEntry, IngestedDoc } from "./types";

/** Build the next annotation entry, numbering rounds 1-based off the existing list. */
export function nextAnnotationEntry(
  existing: AnnotationEntry[],
  decision: string,
  feedback: string,
): AnnotationEntry {
  return { decision, feedback, round: existing.length + 1 };
}

/** Locate an ingested doc by filename (returns -1 when absent). */
export function findDocIndex(docs: IngestedDoc[], filename: string): number {
  return docs.findIndex((d) => d.filename === filename);
}
