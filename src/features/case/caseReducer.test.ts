import { describe, expect, it } from "vitest";
import { caseReducer, initialCaseState, type CaseState } from "./caseReducer";
import type { CaseDecisionResult, CaseReconciliation, ClassifyResult } from "@/lib/types";

function seeded(): CaseState {
  let s = initialCaseState();
  s = caseReducer(s, {
    type: "CREATE_CASE_DONE",
    caseId: "case-1",
    caseType: "loan_application",
    label: "My case",
    ocrEngine: "docling",
  });
  s = caseReducer(s, {
    type: "ADD_MEMBERS",
    members: [
      { memberId: "m1", file: null, filename: "a.pdf" },
      { memberId: "m2", file: null, filename: "b.pdf" },
    ],
  });
  return s;
}

const classifyResult: ClassifyResult = {
  document_id: "doc-1",
  provider: "heuristic",
  doc_type: "invoice",
  confidence: 0.9,
  candidates: [{ doc_type: "invoice", score: 0.9 }],
};

describe("caseReducer", () => {
  it("CREATE_CASE_DONE sets case identity", () => {
    const s = caseReducer(initialCaseState(), {
      type: "CREATE_CASE_DONE",
      caseId: "case-1",
      caseType: "loan_application",
      label: "L",
      ocrEngine: "docling",
    });
    expect(s.caseId).toBe("case-1");
    expect(s.caseType).toBe("loan_application");
    expect(s.label).toBe("L");
    expect(s.ocrEngine).toBe("docling");
  });

  it("ADD_MEMBERS seeds queued members in order", () => {
    const s = seeded();
    expect(s.memberOrder).toEqual(["m1", "m2"]);
    expect(s.members.m1.status).toBe("queued");
    expect(s.members.m2.filename).toBe("b.pdf");
    expect(s.members.m1.documentId).toBeNull();
  });

  it("ADD_MEMBERS appends rather than replacing", () => {
    let s = seeded();
    s = caseReducer(s, {
      type: "ADD_MEMBERS",
      members: [{ memberId: "m3", file: null, filename: "c.pdf" }],
    });
    expect(s.memberOrder).toEqual(["m1", "m2", "m3"]);
  });

  it("walks one member through the stage transitions", () => {
    let s = seeded();
    s = caseReducer(s, { type: "MEMBER_STAGE_START", memberId: "m1", status: "uploading" });
    expect(s.members.m1.status).toBe("uploading");
    s = caseReducer(s, {
      type: "MEMBER_STAGE_DONE",
      memberId: "m1",
      status: "uploaded",
      documentId: "doc-1",
    });
    expect(s.members.m1.status).toBe("uploaded");
    expect(s.members.m1.documentId).toBe("doc-1");
    s = caseReducer(s, { type: "MEMBER_STAGE_START", memberId: "m1", status: "ocr_running" });
    s = caseReducer(s, { type: "MEMBER_CLASSIFY_DONE", memberId: "m1", classify: classifyResult });
    expect(s.members.m1.status).toBe("classified");
    expect(s.members.m1.classify).toBe(classifyResult);
  });

  it("MEMBER_CLASSIFY_DONE records the actual OCR engine when provided", () => {
    let s = seeded();
    expect(s.members.m1.ocrEngine).toBeNull();
    s = caseReducer(s, {
      type: "MEMBER_CLASSIFY_DONE",
      memberId: "m1",
      classify: classifyResult,
      ocrEngine: "gemini-flash",
    });
    expect(s.members.m1.ocrEngine).toBe("gemini-flash");
  });

  it("MEMBER_CLASSIFY_DONE leaves ocrEngine untouched when omitted", () => {
    let s = seeded();
    s = caseReducer(s, {
      type: "MEMBER_CLASSIFY_DONE",
      memberId: "m1",
      classify: classifyResult,
    });
    expect(s.members.m1.ocrEngine).toBeNull();
  });

  it("classify -> confirm sets confirmedDocType", () => {
    let s = seeded();
    s = caseReducer(s, { type: "MEMBER_CLASSIFY_DONE", memberId: "m1", classify: classifyResult });
    s = caseReducer(s, { type: "MEMBER_CONFIRM_DOC_TYPE", memberId: "m1", docType: "invoice" });
    expect(s.members.m1.confirmedDocType).toBe("invoice");
    expect(s.members.m1.status).toBe("confirmed");
  });

  it("one member's error never mutates its siblings", () => {
    let s = seeded();
    const before = s.members.m2;
    s = caseReducer(s, { type: "MEMBER_STAGE_ERROR", memberId: "m1", error: "boom" });
    expect(s.members.m1.status).toBe("error");
    expect(s.members.m1.error).toBe("boom");
    // The sibling object is untouched (referentially identical).
    expect(s.members.m2).toBe(before);
    expect(s.members.m2.status).toBe("queued");
  });

  it("STAGE_START clears a prior error on that member", () => {
    let s = seeded();
    s = caseReducer(s, { type: "MEMBER_STAGE_ERROR", memberId: "m1", error: "boom" });
    s = caseReducer(s, { type: "MEMBER_STAGE_START", memberId: "m1", status: "uploading" });
    expect(s.members.m1.error).toBeNull();
  });

  it("is a no-op for an unknown member", () => {
    const s = seeded();
    const next = caseReducer(s, {
      type: "MEMBER_STAGE_START",
      memberId: "ghost",
      status: "uploading",
    });
    expect(next).toBe(s);
  });

  it("toggles reconcile flag + stores the result", () => {
    let s = seeded();
    s = caseReducer(s, { type: "RECONCILE_START" });
    expect(s.reconciling).toBe(true);
    const recon = { case_id: "case-1" } as CaseReconciliation;
    s = caseReducer(s, { type: "RECONCILE_DONE", result: recon });
    expect(s.reconciling).toBe(false);
    expect(s.reconciliation).toBe(recon);
  });

  it("RECONCILE_ERROR clears the flag without a result", () => {
    let s = caseReducer(seeded(), { type: "RECONCILE_START" });
    s = caseReducer(s, { type: "RECONCILE_ERROR" });
    expect(s.reconciling).toBe(false);
    expect(s.reconciliation).toBeNull();
  });

  it("toggles decide flag + stores the result", () => {
    let s = seeded();
    s = caseReducer(s, { type: "DECIDE_START" });
    expect(s.deciding).toBe(true);
    const decision = { case_id: "case-1", decision: "approve" } as CaseDecisionResult;
    s = caseReducer(s, { type: "DECIDE_DONE", result: decision });
    expect(s.deciding).toBe(false);
    expect(s.decision).toBe(decision);
  });

  it("OPEN_MEMBER + NAVIGATE_TO_FIELD set activeDocId and focus; CLOSE clears", () => {
    let s = seeded();
    s = caseReducer(s, { type: "OPEN_MEMBER", documentId: "doc-1" });
    expect(s.activeDocId).toBe("doc-1");
    expect(s.focus).toEqual({ documentId: "doc-1" });
    s = caseReducer(s, {
      type: "NAVIGATE_TO_FIELD",
      documentId: "doc-2",
      field: "total",
      page: 2,
    });
    expect(s.activeDocId).toBe("doc-2");
    expect(s.focus).toEqual({ documentId: "doc-2", field: "total", page: 2 });
    s = caseReducer(s, { type: "CLOSE_DRILLDOWN" });
    expect(s.activeDocId).toBeNull();
    expect(s.focus).toBeNull();
  });

  it("RESET returns a fresh initial state", () => {
    let s = seeded();
    s = caseReducer(s, { type: "DECIDE_START" });
    s = caseReducer(s, { type: "RESET" });
    expect(s).toEqual(initialCaseState());
  });
});
