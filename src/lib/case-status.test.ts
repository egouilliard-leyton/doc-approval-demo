import { describe, expect, it } from "vitest";
import {
  CASE_DECISION_LABEL,
  CASE_MEMBER_STATUS_LABEL,
  agreementTone,
  caseDecisionClass,
  isMemberTerminal,
  kindLabel,
} from "@/lib/case-status";

describe("case-status", () => {
  it("labels every member status", () => {
    expect(CASE_MEMBER_STATUS_LABEL.queued).toBe("Queued");
    expect(CASE_MEMBER_STATUS_LABEL.ocr_running).toBe("OCR");
    expect(CASE_MEMBER_STATUS_LABEL.structured).toBe("Structured");
    expect(CASE_MEMBER_STATUS_LABEL.error).toBe("Error");
  });

  it("marks only structured/error as terminal", () => {
    expect(isMemberTerminal("structured")).toBe(true);
    expect(isMemberTerminal("error")).toBe(true);
    expect(isMemberTerminal("classifying")).toBe(false);
    expect(isMemberTerminal("confirmed")).toBe(false);
  });

  it("maps decisions to the approve/review/flag tone vocabulary", () => {
    expect(CASE_DECISION_LABEL.approve).toBe("Approved");
    expect(caseDecisionClass("approve")).toContain("text-approve");
    expect(caseDecisionClass("flag")).toContain("text-flag");
    expect(caseDecisionClass("needs_review")).toContain("text-review-foreground");
  });

  it("tones agreement green and conflict amber (review)", () => {
    expect(agreementTone(true)).toBe("text-approve");
    expect(agreementTone(false)).toBe("text-review-foreground");
  });

  it("labels known kinds and title-cases unknown ones", () => {
    expect(kindLabel("money")).toBe("Money");
    expect(kindLabel("date")).toBe("Date");
    expect(kindLabel("string")).toBe("Text");
    expect(kindLabel("custom")).toBe("Custom");
    expect(kindLabel("")).toBe("—");
  });
});
