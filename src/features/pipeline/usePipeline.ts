// Pipeline state machine: owns the document and stage results, and drives the
// sequential auto-run (prescan -> ocr -> structure -> decide). The runner stops on
// the first error and marks downstream stages "blocked" (avoids the backend's 409s).
import { useCallback, useMemo, useReducer } from "react";
import { toast } from "sonner";
import {
  ApiError,
  runDecide,
  runOcr,
  runPrescan,
  runStructure,
  uploadDocument,
} from "@/lib/api";
import type {
  DecisionResult,
  DocType,
  DocumentDetail,
  OcrEngine,
  OCRResult,
  QualityReport,
  StructuredResult,
} from "@/lib/types";

export type StageKey = "prescan" | "ocr" | "structure" | "decide";
export type StageStatus = "idle" | "running" | "done" | "error" | "blocked";

export const STAGE_ORDER: StageKey[] = [
  "prescan",
  "ocr",
  "structure",
  "decide",
];

export const STAGE_LABEL: Record<StageKey, string> = {
  prescan: "Pre-scan",
  ocr: "OCR",
  structure: "Structure",
  decide: "Decide",
};

export interface PipelineState {
  document: DocumentDetail | null;
  prescan: QualityReport | null;
  ocr: OCRResult | null; // active engine's result
  ocrByEngine: Record<string, OCRResult>; // for comparison mode
  structure: StructuredResult | null;
  decision: DecisionResult | null;
  perStageStatus: Record<StageKey, StageStatus>;
  perStageTiming: Partial<Record<StageKey, number>>;
  activeEngine: OcrEngine;
  docType: DocType;
  ingesting: boolean;
  error: { stage: StageKey; message: string } | null;
}

const idleStatus = (): Record<StageKey, StageStatus> => ({
  prescan: "idle",
  ocr: "idle",
  structure: "idle",
  decide: "idle",
});

function initialState(): PipelineState {
  return {
    document: null,
    prescan: null,
    ocr: null,
    ocrByEngine: {},
    structure: null,
    decision: null,
    perStageStatus: idleStatus(),
    perStageTiming: {},
    activeEngine: "docling",
    docType: "invoice",
    ingesting: false,
    error: null,
  };
}

type Action =
  | { type: "RESET" }
  | { type: "SET_DOC_TYPE"; docType: DocType }
  | { type: "SET_ACTIVE_ENGINE"; engine: OcrEngine }
  | { type: "INGEST_START" }
  | { type: "INGEST_DONE"; document: DocumentDetail }
  | { type: "INGEST_ERROR" }
  | { type: "STAGE_START"; stage: StageKey }
  | { type: "STAGE_BLOCKED"; stages: StageKey[] }
  | { type: "STAGE_ERROR"; stage: StageKey; message: string }
  | { type: "PRESCAN_DONE"; result: QualityReport; timing: number }
  | {
      type: "OCR_DONE";
      result: OCRResult;
      engine: OcrEngine;
      setActive: boolean;
    }
  | { type: "STRUCTURE_DONE"; result: StructuredResult; timing: number }
  | { type: "DECIDE_DONE"; result: DecisionResult; timing: number };

function reducer(state: PipelineState, action: Action): PipelineState {
  switch (action.type) {
    case "RESET":
      return {
        ...initialState(),
        docType: state.docType,
        activeEngine: state.activeEngine,
      };
    case "SET_DOC_TYPE":
      return { ...state, docType: action.docType };
    case "SET_ACTIVE_ENGINE": {
      const cached = state.ocrByEngine[action.engine] ?? null;
      return {
        ...state,
        activeEngine: action.engine,
        ocr: cached ?? state.ocr,
        perStageTiming: cached
          ? { ...state.perStageTiming, ocr: cached.latency_ms }
          : state.perStageTiming,
      };
    }
    case "INGEST_START":
      return {
        ...initialState(),
        docType: state.docType,
        activeEngine: state.activeEngine,
        ingesting: true,
      };
    case "INGEST_DONE":
      return { ...state, ingesting: false, document: action.document };
    case "INGEST_ERROR":
      return { ...state, ingesting: false };
    case "STAGE_START":
      return {
        ...state,
        error: null,
        perStageStatus: { ...state.perStageStatus, [action.stage]: "running" },
      };
    case "STAGE_BLOCKED": {
      const next = { ...state.perStageStatus };
      for (const s of action.stages) next[s] = "blocked";
      return { ...state, perStageStatus: next };
    }
    case "STAGE_ERROR":
      return {
        ...state,
        perStageStatus: { ...state.perStageStatus, [action.stage]: "error" },
        error: { stage: action.stage, message: action.message },
      };
    case "PRESCAN_DONE":
      return {
        ...state,
        prescan: action.result,
        perStageStatus: { ...state.perStageStatus, prescan: "done" },
        perStageTiming: { ...state.perStageTiming, prescan: action.timing },
      };
    case "OCR_DONE":
      return {
        ...state,
        ocrByEngine: { ...state.ocrByEngine, [action.engine]: action.result },
        ocr: action.setActive ? action.result : state.ocr,
        perStageStatus: { ...state.perStageStatus, ocr: "done" },
        perStageTiming: action.setActive
          ? { ...state.perStageTiming, ocr: action.result.latency_ms }
          : state.perStageTiming,
      };
    case "STRUCTURE_DONE":
      return {
        ...state,
        structure: action.result,
        perStageStatus: { ...state.perStageStatus, structure: "done" },
        perStageTiming: { ...state.perStageTiming, structure: action.timing },
      };
    case "DECIDE_DONE":
      return {
        ...state,
        decision: action.result,
        perStageStatus: { ...state.perStageStatus, decide: "done" },
        perStageTiming: { ...state.perStageTiming, decide: action.timing },
      };
    default:
      return state;
  }
}

function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Unexpected error";
}

export interface UsePipeline extends PipelineState {
  setDocType: (t: DocType) => void;
  setActiveEngine: (e: OcrEngine) => void;
  ingestFile: (file: File) => Promise<void>;
  runStage: (stage: StageKey) => Promise<void>;
  runEngineComparison: () => Promise<void>;
  reset: () => void;
}

export function usePipeline(): UsePipeline {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);

  // Run a single stage against a known document id, returning success.
  const execStage = useCallback(
    async (
      docId: string,
      stage: StageKey,
      opts: { engine: OcrEngine; docType: DocType; setActive?: boolean },
    ): Promise<boolean> => {
      dispatch({ type: "STAGE_START", stage });
      try {
        if (stage === "prescan") {
          const t0 = performance.now();
          const result = await runPrescan(docId, { deskew: true, clean: true });
          dispatch({
            type: "PRESCAN_DONE",
            result,
            timing: Math.round(performance.now() - t0),
          });
        } else if (stage === "ocr") {
          const result = await runOcr(docId, opts.engine);
          dispatch({
            type: "OCR_DONE",
            result,
            engine: opts.engine,
            setActive: opts.setActive ?? true,
          });
        } else if (stage === "structure") {
          const result = await runStructure(docId, {
            docType: opts.docType,
            ocrEngine: opts.engine,
          });
          dispatch({
            type: "STRUCTURE_DONE",
            result,
            timing: result.latency_ms,
          });
        } else {
          const result = await runDecide(docId);
          dispatch({ type: "DECIDE_DONE", result, timing: result.latency_ms });
        }
        return true;
      } catch (e) {
        const message = errMessage(e);
        dispatch({ type: "STAGE_ERROR", stage, message });
        toast.error(`${STAGE_LABEL[stage]} failed`, { description: message });
        return false;
      }
    },
    [],
  );

  // Sequential auto-run; downstream stages are marked blocked on first failure.
  const runAll = useCallback(
    async (docId: string, engine: OcrEngine, docType: DocType) => {
      for (let i = 0; i < STAGE_ORDER.length; i++) {
        const stage = STAGE_ORDER[i];
        const ok = await execStage(docId, stage, {
          engine,
          docType,
          setActive: true,
        });
        if (!ok) {
          dispatch({ type: "STAGE_BLOCKED", stages: STAGE_ORDER.slice(i + 1) });
          return;
        }
      }
    },
    [execStage],
  );

  const ingestFile = useCallback(
    async (file: File) => {
      dispatch({ type: "INGEST_START" });
      const engine = state.activeEngine;
      const docType = state.docType;
      let doc: DocumentDetail;
      try {
        doc = await uploadDocument(file, docType);
      } catch (e) {
        dispatch({ type: "INGEST_ERROR" });
        toast.error("Upload failed", { description: errMessage(e) });
        return;
      }
      dispatch({ type: "INGEST_DONE", document: doc });
      await runAll(doc.id, engine, docType);
    },
    [state.activeEngine, state.docType, runAll],
  );

  const runStage = useCallback(
    async (stage: StageKey) => {
      if (!state.document) return;
      await execStage(state.document.id, stage, {
        engine: state.activeEngine,
        docType: state.docType,
        setActive: true,
      });
    },
    [state.document, state.activeEngine, state.docType, execStage],
  );

  // Run OCR for both engines so the comparison view has qwen-vl + docling.
  const runEngineComparison = useCallback(async () => {
    if (!state.document) return;
    const engines: OcrEngine[] = ["docling", "qwen-vl"];
    for (const engine of engines) {
      if (state.ocrByEngine[engine]) continue;
      await execStage(state.document.id, "ocr", {
        engine,
        docType: state.docType,
        setActive: engine === state.activeEngine,
      });
    }
  }, [
    state.document,
    state.docType,
    state.activeEngine,
    state.ocrByEngine,
    execStage,
  ]);

  const setDocType = useCallback(
    (t: DocType) => dispatch({ type: "SET_DOC_TYPE", docType: t }),
    [],
  );
  const setActiveEngine = useCallback(
    (e: OcrEngine) => dispatch({ type: "SET_ACTIVE_ENGINE", engine: e }),
    [],
  );
  const reset = useCallback(() => dispatch({ type: "RESET" }), []);

  return useMemo(
    () => ({
      ...state,
      setDocType,
      setActiveEngine,
      ingestFile,
      runStage,
      runEngineComparison,
      reset,
    }),
    [
      state,
      setDocType,
      setActiveEngine,
      ingestFile,
      runStage,
      runEngineComparison,
      reset,
    ],
  );
}
