import { describe, expect, it } from "vitest";
import { deriveCaseStage, memberProgress } from "@/lib/case-stage";
import type { CaseMemberStatus } from "@/lib/case-status";

describe("deriveCaseStage", () => {
  it("stays on classify while members are still in flight", () => {
    expect(deriveCaseStage(["classifying", "confirmed"], false)).toBe(
      "classify",
    );
    expect(deriveCaseStage(["structured", "structuring"], false)).toBe(
      "classify",
    );
  });

  it("moves to overview once every member is terminal", () => {
    expect(deriveCaseStage(["structured", "error"], false)).toBe("overview");
    expect(deriveCaseStage(["structured", "structured"], false)).toBe(
      "overview",
    );
  });

  it("moves to overview as soon as reconciliation exists", () => {
    expect(deriveCaseStage(["confirmed"], true)).toBe("overview");
  });

  it("treats an empty case as classify (nothing settled yet)", () => {
    expect(deriveCaseStage([], false)).toBe("classify");
  });
});

describe("memberProgress", () => {
  it("tallies structured, errored, settled and active", () => {
    const statuses: CaseMemberStatus[] = [
      "structured",
      "structured",
      "error",
      "classifying",
    ];
    expect(memberProgress(statuses)).toEqual({
      total: 4,
      settled: 3,
      structured: 2,
      errored: 1,
      active: 1,
    });
  });

  it("handles an empty list", () => {
    expect(memberProgress([])).toEqual({
      total: 0,
      settled: 0,
      structured: 0,
      errored: 0,
      active: 0,
    });
  });
});
