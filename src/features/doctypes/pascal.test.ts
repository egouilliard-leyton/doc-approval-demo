// pascalCase must match the backend `_pascal` byte-for-byte
// (backend/app/extraction/definition.py): PascalCase each underscore segment
// (Python str.capitalize() upcases first char + lowercases the rest), then drop
// a single trailing "s". These cases mirror the backend's own examples.
import { describe, expect, it } from "vitest";
import { pascalCase } from "./pascal";

describe("pascalCase (mirrors backend _pascal)", () => {
  const cases: [string, string][] = [
    ["line_items", "LineItem"],
    ["termination_clause", "TerminationClause"],
    ["effective_date", "EffectiveDate"],
    ["total", "Total"],
    ["address", "Addres"], // single trailing s dropped
    ["PARTIES", "Partie"], // rest lowercased, then -s
    ["po_number", "PoNumber"],
    ["", ""],
  ];

  it.each(cases)("pascalCase(%j) === %j", (input, expected) => {
    expect(pascalCase(input)).toBe(expected);
  });
});
