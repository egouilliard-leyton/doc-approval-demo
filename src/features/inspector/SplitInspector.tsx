import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, editStructureField, getSheets } from "@/lib/api";
import { buildHighlights } from "@/lib/highlights";
import { cellRefsForFields } from "@/lib/grounding";
import { isSpreadsheet } from "@/lib/doc-status";
import type { InspectorTab } from "@/lib/route";
import { usePipelineContext } from "@/features/pipeline/PipelineContext";
import { useEngines } from "@/features/upload/useEngines";
import { PageViewer } from "@/features/inspector/PageViewer";
import { GridViewer } from "@/features/inspector/GridViewer";
import { OcrTextPanel } from "@/features/inspector/OcrTextPanel";
import { StructuredPanel } from "@/features/inspector/StructuredPanel";
import { CorrectionsDialog } from "@/features/inspector/CorrectionsDialog";
import { EngineComparison } from "@/features/inspector/EngineComparison";
import { DecisionCard } from "@/features/decision/DecisionCard";

function Pending({ label }: { label: string }) {
  return (
    <div className="space-y-3 p-1">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-2/3" />
      <p className="pt-2 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return (
    <div className="flex h-40 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
      {label}
    </div>
  );
}

export function SplitInspector({
  focus,
  tab: tabProp,
  onTabChange,
}: {
  /** Case drill-down: jump to a field/page once the structure is ready (additive; no-op when omitted). */
  focus?: { field?: string; page?: number } | null;
  /** Controlled active tab (URL-driven in the workspace); omit to use local state. */
  tab?: InspectorTab;
  onTabChange?: (t: InspectorTab) => void;
} = {}) {
  const {
    document,
    ocr,
    ocrByEngine,
    structure,
    decision,
    perStageStatus,
    runEngineComparison,
    runOcrEngine,
    updateStructure,
  } = usePipelineContext();
  const { engines } = useEngines();

  const [hoveredField, setHoveredField] = useState<string | null>(null);
  const [selectedField, setSelectedField] = useState<string | null>(null);
  const [activePage, setActivePage] = useState(1);
  const [flashTick, setFlashTick] = useState(0);
  const [correctionsOpen, setCorrectionsOpen] = useState(false);
  // Controlled-or-local tab: the workspace drives it from the URL; drill-down
  // callers omit the props and fall back to this local state (unchanged behavior).
  const [localTab, setLocalTab] = useState<InspectorTab>("structured");
  const tab = tabProp ?? localTab;
  const setTab = onTabChange ?? setLocalTab;

  // Resolve every grounded field to a color-coded page region once per result.
  const highlights = useMemo(
    () => buildHighlights(structure?.grounding_map ?? {}, ocr),
    [structure, ocr],
  );

  // For spreadsheets: fetch sheet names so grounded fields can show an A1 source
  // cell (e.g. "Invoice!B2"). Keyed by doc id so a stale fetch never mislabels.
  const docId = document?.id ?? null;
  const isSheet = document ? isSpreadsheet(document.mime) : false;
  const [sheetNamesState, setSheetNamesState] = useState<{
    docId: string;
    names: string[];
  } | null>(null);
  useEffect(() => {
    if (!docId || !isSheet) return;
    let cancelled = false;
    getSheets(docId)
      .then((s) => {
        if (!cancelled) setSheetNamesState({ docId, names: s.map((x) => x.name) });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [docId, isSheet]);
  const cellRefByPath = useMemo(() => {
    if (!isSheet) return {};
    const names =
      sheetNamesState?.docId === docId ? sheetNamesState.names : [];
    return cellRefsForFields(structure?.grounding_map ?? {}, ocr, names);
  }, [isSheet, docId, sheetNamesState, structure, ocr]);

  // Clicking a field: jump to its page, then scroll to + flash its box.
  const selectField = useCallback(
    (path: string) => {
      setSelectedField(path);
      const page = highlights.pageByPath[path];
      if (page) setActivePage(page);
      setFlashTick((t) => t + 1);
    },
    [highlights],
  );

  // Case drill-down focus: once the structure (and thus highlights) is ready, jump
  // to the requested field (flashing its box) or page. Primitives in the deps keep
  // this from re-firing on a fresh `focus` object identity every render.
  const focusField = focus?.field ?? null;
  const focusPage = focus?.page ?? null;
  useEffect(() => {
    if (!structure) return;
    if (!focusField && !focusPage) return;
    // Defer to the next frame so the jump/flash lands after the structure has
    // rendered (and to keep setState out of the effect body).
    const raf = requestAnimationFrame(() => {
      if (focusField) selectField(focusField);
      else if (focusPage) setActivePage(focusPage);
    });
    return () => cancelAnimationFrame(raf);
  }, [focusField, focusPage, structure, selectField]);

  const editField = useCallback(
    async (path: string, value: string | null) => {
      if (!document) return;
      try {
        const updated = await editStructureField(document.id, { path, value });
        updateStructure(updated);
        toast.success("Field updated");
      } catch (e) {
        toast.error("Could not update field", {
          description: e instanceof ApiError ? e.message : String(e),
        });
      }
    },
    [document, updateStructure],
  );

  if (!document) return null;

  const spreadsheet = isSpreadsheet(document.mime);
  // Compare is hidden for spreadsheets — coerce a stale/URL "compare" to structured.
  const clampTab = spreadsheet && tab === "compare" ? "structured" : tab;
  const displayPage = activePage;
  const selectedKey = selectedField
    ? (highlights.regionKeyByPath[selectedField] ?? null)
    : null;
  const hoveredKey = hoveredField
    ? (highlights.regionKeyByPath[hoveredField] ?? null)
    : null;

  return (
    <div className="grid flex-1 gap-4 lg:grid-cols-2">
      {/* Left: source document */}
      <div className="min-h-0 min-w-0">
        {spreadsheet ? (
          <GridViewer
            docId={document.id}
            page={displayPage}
            regions={highlights.regions}
            selectedKey={selectedKey}
            hoveredKey={hoveredKey}
            flashTick={flashTick}
            onPageChange={setActivePage}
          />
        ) : (
          <PageViewer
            pages={document.pages}
            page={displayPage}
            regions={highlights.regions}
            selectedKey={selectedKey}
            hoveredKey={hoveredKey}
            flashTick={flashTick}
            onPageChange={setActivePage}
          />
        )}
      </div>

      {/* Right: inspector tabs */}
      <div className="flex min-h-0 min-w-0 flex-col">
        <Tabs
          value={clampTab}
          onValueChange={(v) => setTab(v as InspectorTab)}
          className="flex min-h-0 flex-1 flex-col"
        >
          <TabsList>
            <TabsTrigger value="ocr">OCR text</TabsTrigger>
            <TabsTrigger value="structured">Structured</TabsTrigger>
            <TabsTrigger value="decision">Decision</TabsTrigger>
            {/* Spreadsheets always use the single native engine — nothing to compare. */}
            {!spreadsheet && <TabsTrigger value="compare">Compare</TabsTrigger>}
          </TabsList>

          <TabsContent value="ocr" className="min-h-0 flex-1">
            {ocr ? (
              <OcrTextPanel ocr={ocr} page={displayPage} />
            ) : perStageStatus.ocr === "running" ? (
              <Pending label="Running OCR…" />
            ) : (
              <Empty label="OCR has not run yet." />
            )}
          </TabsContent>

          <TabsContent value="structured" className="min-h-0 flex-1">
            {structure ? (
              <StructuredPanel
                structure={structure}
                colorByPath={highlights.colorByPath}
                cellRefByPath={cellRefByPath}
                spreadsheet={spreadsheet}
                selectedPath={selectedField}
                onSelectField={selectField}
                onHoverField={setHoveredField}
                onEditField={editField}
                onReviewEdits={() => setCorrectionsOpen(true)}
              />
            ) : perStageStatus.structure === "running" ? (
              <Pending label="Structuring with LangExtract…" />
            ) : (
              <Empty label="Structuring has not run yet." />
            )}
          </TabsContent>

          <TabsContent
            value="decision"
            className="min-h-0 flex-1 overflow-auto"
          >
            {decision ? (
              <DecisionCard decision={decision} />
            ) : perStageStatus.decide === "running" ? (
              <Pending label="Agent is deciding…" />
            ) : (
              <Empty label="No decision yet." />
            )}
          </TabsContent>

          <TabsContent value="compare" className="min-h-0 flex-1">
            <EngineComparison
              engines={engines}
              ocrByEngine={ocrByEngine}
              page={displayPage}
              onRunAll={runEngineComparison}
              onRunEngine={runOcrEngine}
              running={perStageStatus.ocr === "running"}
            />
          </TabsContent>
        </Tabs>
      </div>

      <CorrectionsDialog
        open={correctionsOpen}
        onClose={() => setCorrectionsOpen(false)}
        pages={document.pages}
        structure={structure}
        highlights={highlights}
        spreadsheet={spreadsheet}
      />
    </div>
  );
}
