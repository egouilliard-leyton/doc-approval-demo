// A shared, dumb spreadsheet grid used by both the mapping UI (click-to-bind) and
// the computed preview. Mirrors inspector/GridViewer.tsx (sticky row/col headers,
// sheet-tab buttons, a truncation banner) but adds MERGE-AWARENESS: a merged range
// renders as a single cell spanning its rows/cols via rowSpan/colSpan, and the
// covered cells are skipped — so a click anywhere on a merge resolves to the merge's
// top-left anchor address. It renders one sheet at a time; the active sheet + tabs
// are controlled by the parent.
import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { colToLetters } from "@/lib/grounding";
import { formatCellValue } from "@/features/templates/formatCell";
import type { SpreadsheetCell } from "@/lib/types";

/** The minimal per-sheet shape the grid renders (shared by mapping + preview). */
export interface GridSheet {
  name: string;
  max_row: number;
  max_col: number;
  merges: string[]; // A1-style ranges, e.g. "A1:B2"
  cells: SpreadsheetCell[];
}

/** One cell highlight: a colour and an optional short label shown in the corner. */
export interface CellHighlight {
  color: string;
  label?: string;
}

// The read caps the backend applies (see spreadsheet.read_template_grid); a sheet at
// the cap is (advisorily) shown as truncated for display.
const MAX_ROWS = 500;
const MAX_COLS = 60;

/** Parse an A1 address into 1-based {row, col}. Returns null if malformed. */
function parseAddress(addr: string): { row: number; col: number } | null {
  const m = /^([A-Za-z]+)(\d+)$/.exec(addr);
  if (!m) return null;
  let col = 0;
  for (const ch of m[1].toUpperCase()) col = col * 26 + (ch.charCodeAt(0) - 64);
  return { row: parseInt(m[2], 10), col };
}

interface MergeInfo {
  // Anchor (top-left) "r:c" -> its span; covered non-anchor cells are hidden.
  anchors: Map<string, { rowSpan: number; colSpan: number }>;
  covered: Set<string>;
}

function parseMerges(merges: string[]): MergeInfo {
  const anchors = new Map<string, { rowSpan: number; colSpan: number }>();
  const covered = new Set<string>();
  for (const range of merges) {
    const [a, b] = range.split(":");
    const start = parseAddress(a ?? "");
    const end = parseAddress(b ?? a ?? "");
    if (!start || !end) continue;
    const r0 = Math.min(start.row, end.row);
    const r1 = Math.max(start.row, end.row);
    const c0 = Math.min(start.col, end.col);
    const c1 = Math.max(start.col, end.col);
    anchors.set(`${r0}:${c0}`, { rowSpan: r1 - r0 + 1, colSpan: c1 - c0 + 1 });
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        if (r === r0 && c === c0) continue;
        covered.add(`${r}:${c}`);
      }
    }
  }
  return { anchors, covered };
}

export function SpreadsheetGridTable({
  grid,
  sheetNames,
  activeSheet,
  onSheetChange,
  onCellClick,
  highlightedCells,
  loading = false,
  emptyLabel = "This sheet is empty.",
}: {
  grid: GridSheet | null;
  sheetNames: string[];
  activeSheet: string;
  onSheetChange: (name: string) => void;
  /** Click resolves to the merge's top-left anchor address (a merge is one <td>). */
  onCellClick?: (sheet: string, address: string) => void;
  /** address (A1) -> highlight, for the active sheet only. */
  highlightedCells?: Map<string, CellHighlight>;
  loading?: boolean;
  emptyLabel?: string;
}) {
  const merges = useMemo(() => parseMerges(grid?.merges ?? []), [grid?.merges]);
  const cellByPos = useMemo(() => {
    const map = new Map<string, SpreadsheetCell>();
    for (const c of grid?.cells ?? []) map.set(`${c.row}:${c.col}`, c);
    return map;
  }, [grid?.cells]);

  const nRows = grid?.max_row ?? 0;
  const nCols = grid?.max_col ?? 0;
  const truncated = nRows >= MAX_ROWS || nCols >= MAX_COLS;
  const clickable = Boolean(onCellClick);

  return (
    <div className="flex h-full min-w-0 flex-col gap-3">
      <div className="relative max-h-[65vh] min-h-[16rem] flex-1 overflow-auto rounded-xl border bg-muted/40">
        {loading ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            Loading sheet…
          </div>
        ) : !grid || nRows === 0 || nCols === 0 ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            {emptyLabel}
          </div>
        ) : (
          <table className="border-collapse text-xs tabular-nums">
            <thead>
              <tr>
                <th className="sticky top-0 left-0 z-20 border bg-muted px-2 py-1" />
                {Array.from({ length: nCols }, (_, c) => (
                  <th
                    key={c}
                    className="sticky top-0 z-10 border bg-muted px-2 py-1 font-medium text-muted-foreground"
                  >
                    {colToLetters(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: nRows }, (_, ri) => {
                const r = ri + 1;
                return (
                  <tr key={r}>
                    <th className="sticky left-0 z-10 border bg-muted px-2 py-1 text-right font-normal text-muted-foreground">
                      {r}
                    </th>
                    {Array.from({ length: nCols }, (_, ci) => {
                      const c = ci + 1;
                      const key = `${r}:${c}`;
                      if (merges.covered.has(key)) return null; // spanned by an anchor
                      const span = merges.anchors.get(key);
                      const cell = cellByPos.get(key);
                      // Numeric cells are rendered through their Excel number_format
                      // so the preview matches the export; text/formulas pass through.
                      const text = cell
                        ? formatCellValue(cell.value, cell.number_format)
                        : "";
                      const address = `${colToLetters(ci)}${r}`;
                      const hl = highlightedCells?.get(address);
                      return (
                        <td
                          key={c}
                          rowSpan={span?.rowSpan}
                          colSpan={span?.colSpan}
                          title={text || undefined}
                          onClick={
                            clickable
                              ? () => onCellClick?.(activeSheet, address)
                              : undefined
                          }
                          className={cn(
                            "relative max-w-[16rem] truncate border px-2 py-1",
                            clickable && "cursor-pointer hover:bg-brand/10",
                            cell?.is_formula && !cell.computed && "text-muted-foreground italic",
                          )}
                          style={
                            hl
                              ? {
                                  backgroundColor: `${hl.color}26`,
                                  outline: `2px solid ${hl.color}`,
                                  outlineOffset: "-1px",
                                }
                              : undefined
                          }
                        >
                          {text}
                          {hl?.label && (
                            <span
                              className="ml-1 rounded px-1 text-[10px] font-medium text-white"
                              style={{ backgroundColor: hl.color }}
                            >
                              {hl.label}
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {truncated && (
        <p className="text-xs text-amber-600">
          Large sheet truncated for display (first {MAX_ROWS} rows × {MAX_COLS}{" "}
          columns).
        </p>
      )}

      {sheetNames.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {sheetNames.map((name) => (
            <button
              key={name}
              onClick={() => onSheetChange(name)}
              className={cn(
                "shrink-0 rounded-md border-2 px-3 py-1.5 text-xs font-medium transition-colors",
                name === activeSheet
                  ? "border-brand text-foreground"
                  : "border-transparent bg-muted/50 text-muted-foreground hover:border-border",
              )}
            >
              {name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
