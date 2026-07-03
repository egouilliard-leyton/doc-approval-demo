// Case orchestration: wraps the pure caseReducer with useReducer and drives the
// multi-document flow. Mirrors usePipeline's imperative-orchestration style, but fans
// per-member work out with bounded concurrency (cap = 3) so one document's failure is
// isolated from its siblings (mapWithConcurrency collects, never rejects the batch).
//
// Phases:
//   A (createAndUpload)  per member: upload -> prescan -> ocr -> classify
//   confirm              reviewer sets each member's doc type
//   C (confirmAndExtract) per confirmed member: structure; then D auto-reconcile
//   reconcile / decide   case-level, decide is manual (not auto-chained)
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { toast } from "sonner";
import {
  ApiError,
  classifyDocument,
  createCase,
  decideCase,
  reconcileCase,
  runOcr,
  runPrescan,
  runStructure,
  uploadDocument,
} from "@/lib/api";
import { isMemberTerminal } from "@/lib/case-status";
import { AUTO_ENGINE } from "@/features/upload/EngineSelect";
import { mapWithConcurrency } from "@/lib/concurrency";
import type { DocType, OcrEngine } from "@/lib/types";
import {
  caseReducer,
  initialCaseState,
  type CaseState,
  type NewCaseMember,
} from "@/features/case/caseReducer";

/** Max member pipelines running at once (upload/OCR/classify, extract). */
const CONCURRENCY = 3;

function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Unexpected error";
}

function newMemberId(): string {
  return crypto.randomUUID();
}

export interface UseCase extends CaseState {
  createAndUpload: (
    files: File[],
    caseType: string | null,
    label: string,
    ocrEngine: OcrEngine,
  ) => Promise<boolean>;
  setConfirmedDocType: (memberId: string, docType: DocType) => void;
  confirmAndExtract: (ocrEngine: OcrEngine) => Promise<void>;
  reconcile: () => Promise<void>;
  decide: (provider?: string) => Promise<void>;
  openMember: (documentId: string) => void;
  navigateToCanonicalField: (
    documentId: string,
    field?: string,
    page?: number,
  ) => void;
  closeDrilldown: () => void;
  reset: () => void;
}

export function useCase(): UseCase {
  const [state, dispatch] = useReducer(caseReducer, undefined, initialCaseState);

  // Latest state, for orchestration that must read members/caseId after awaits
  // without re-binding every callback to the whole state object. Synced in an effect
  // (writing a ref during render is disallowed); flushed before any awaited work resolves.
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  // Bumped on every createAndUpload/reset; lets in-flight member work bail out if the
  // user has since started a new case, so a stale upload can't clobber the newer one.
  const runTokenRef = useRef(0);

  const createAndUpload = useCallback(
    async (
      files: File[],
      caseType: string | null,
      label: string,
      ocrEngine: OcrEngine,
    ) => {
      const token = ++runTokenRef.current;

      let caseId: string;
      try {
        const detail = await createCase({ case_type: caseType, label });
        caseId = detail.id;
        dispatch({
          type: "CREATE_CASE_DONE",
          caseId: detail.id,
          caseType: detail.case_type,
          label: detail.label,
          ocrEngine,
        });
      } catch (e) {
        toast.error("Could not create case", { description: errMessage(e) });
        return false;
      }

      const members: NewCaseMember[] = files.map((file) => ({
        memberId: newMemberId(),
        file,
        filename: file.name,
      }));
      dispatch({ type: "ADD_MEMBERS", members });

      // Phase A: upload -> prescan -> ocr -> classify, per member, bounded. Each worker
      // catches its own error and dispatches MEMBER_STAGE_ERROR so a failure is isolated.
      await mapWithConcurrency(members, CONCURRENCY, async (member) => {
        if (runTokenRef.current !== token) return;
        const { memberId, file } = member;
        if (!file) return;
        try {
          dispatch({ type: "MEMBER_STAGE_START", memberId, status: "uploading" });
          const doc = await uploadDocument(file, undefined, caseId);
          dispatch({
            type: "MEMBER_STAGE_DONE",
            memberId,
            status: "uploaded",
            documentId: doc.id,
          });

          dispatch({ type: "MEMBER_STAGE_START", memberId, status: "prescanning" });
          await runPrescan(doc.id, { deskew: true, clean: true });

          dispatch({ type: "MEMBER_STAGE_START", memberId, status: "ocr_running" });
          // "auto" omits the engine so the backend routes by doc type; capture the
          // engine it ACTUALLY ran so classify + later structure read that OCR
          // rather than re-routing (and so the sentinel never reaches the backend).
          const ocr = await runOcr(
            doc.id,
            ocrEngine === AUTO_ENGINE ? undefined : ocrEngine,
          );
          const actualEngine = ocr.engine_name;

          dispatch({ type: "MEMBER_STAGE_START", memberId, status: "classifying" });
          const classify = await classifyDocument(doc.id, {
            ocrEngine: actualEngine,
          });
          if (runTokenRef.current !== token) return;
          dispatch({
            type: "MEMBER_CLASSIFY_DONE",
            memberId,
            classify,
            ocrEngine: actualEngine,
          });
        } catch (e) {
          if (runTokenRef.current !== token) return;
          const message = errMessage(e);
          dispatch({ type: "MEMBER_STAGE_ERROR", memberId, error: message });
          toast.error(`${member.filename} failed`, { description: message });
        }
      });

      return true;
    },
    [],
  );

  const setConfirmedDocType = useCallback(
    (memberId: string, docType: DocType) =>
      dispatch({ type: "MEMBER_CONFIRM_DOC_TYPE", memberId, docType }),
    [],
  );

  const reconcile = useCallback(async () => {
    const caseId = stateRef.current.caseId;
    if (!caseId) return;
    dispatch({ type: "RECONCILE_START" });
    try {
      const result = await reconcileCase(caseId);
      dispatch({ type: "RECONCILE_DONE", result });
    } catch (e) {
      dispatch({ type: "RECONCILE_ERROR" });
      toast.error("Reconcile failed", { description: errMessage(e) });
    }
  }, []);

  const confirmAndExtract = useCallback(
    async (ocrEngine: OcrEngine) => {
      const token = runTokenRef.current;
      const snapshot = stateRef.current;

      // Phase C: structure every confirmed member (that uploaded) — bounded, isolated.
      const targets = snapshot.memberOrder
        .map((id) => snapshot.members[id])
        .filter((m) => m && m.confirmedDocType && m.documentId);

      const extracted = new Set<string>();
      const results = await mapWithConcurrency(
        targets,
        CONCURRENCY,
        async (member) => {
          if (runTokenRef.current !== token) return;
          const { memberId, documentId, confirmedDocType } = member;
          if (!documentId || !confirmedDocType) return;
          try {
            dispatch({ type: "MEMBER_STAGE_START", memberId, status: "structuring" });
            // Prefer the engine that actually ran this member's OCR (set during
            // phase A) so structure reads the stored OCR — critical under "auto",
            // where each member may have routed to a different engine. Fall back to
            // the case-global engine (never the raw sentinel).
            const structureEngine =
              member.ocrEngine ??
              (ocrEngine === AUTO_ENGINE ? undefined : ocrEngine);
            await runStructure(documentId, {
              docType: confirmedDocType,
              ocrEngine: structureEngine,
            });
            if (runTokenRef.current !== token) return;
            dispatch({ type: "MEMBER_STAGE_DONE", memberId, status: "structured" });
          } catch (e) {
            if (runTokenRef.current !== token) return;
            const message = errMessage(e);
            dispatch({ type: "MEMBER_STAGE_ERROR", memberId, error: message });
            toast.error(`${member.filename} failed`, { description: message });
          }
        },
      );

      if (runTokenRef.current !== token) return;
      results.forEach((r, i) => {
        if (r.ok) extracted.add(targets[i].memberId);
      });

      // Phase D: auto-reconcile once every member has reached a terminal state. A member
      // we just structured is terminal; an errored one is terminal; everything else keeps
      // its snapshot status. Only reconcile when the whole case has settled.
      const allTerminal = snapshot.memberOrder.every((id) => {
        const m = snapshot.members[id];
        if (!m) return true;
        const finalStatus = extracted.has(id) ? "structured" : m.status;
        return isMemberTerminal(finalStatus);
      });
      if (allTerminal) await reconcile();
    },
    [reconcile],
  );

  const decide = useCallback(async (provider?: string) => {
    const caseId = stateRef.current.caseId;
    if (!caseId) return;
    dispatch({ type: "DECIDE_START" });
    try {
      const result = await decideCase(caseId, provider);
      dispatch({ type: "DECIDE_DONE", result });
    } catch (e) {
      dispatch({ type: "DECIDE_ERROR" });
      toast.error("Decide failed", { description: errMessage(e) });
    }
  }, []);

  const openMember = useCallback(
    (documentId: string) => dispatch({ type: "OPEN_MEMBER", documentId }),
    [],
  );
  const navigateToCanonicalField = useCallback(
    (documentId: string, field?: string, page?: number) =>
      dispatch({ type: "NAVIGATE_TO_FIELD", documentId, field, page }),
    [],
  );
  const closeDrilldown = useCallback(
    () => dispatch({ type: "CLOSE_DRILLDOWN" }),
    [],
  );
  const reset = useCallback(() => {
    runTokenRef.current++;
    dispatch({ type: "RESET" });
  }, []);

  return useMemo(
    () => ({
      ...state,
      createAndUpload,
      setConfirmedDocType,
      confirmAndExtract,
      reconcile,
      decide,
      openMember,
      navigateToCanonicalField,
      closeDrilldown,
      reset,
    }),
    [
      state,
      createAndUpload,
      setConfirmedDocType,
      confirmAndExtract,
      reconcile,
      decide,
      openMember,
      navigateToCanonicalField,
      closeDrilldown,
      reset,
    ],
  );
}
