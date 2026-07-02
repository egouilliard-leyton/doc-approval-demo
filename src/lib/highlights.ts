// Color-coded source regions: resolve every grounded field to a box on the page,
// group fields that share the same physical region (e.g. all values read out of one
// table share that table's bbox), and assign each distinct region a stable color.
// The page overlay and the structured panel both read from this so a box's color
// matches its field entry, and clicking a field can jump to its region.
import {
  cellsForField,
  rectsForField,
  type CellRef,
  type HighlightRect,
} from "@/lib/grounding";
import type { Grounding, OCRResult } from "@/lib/types";

// Distinct, readable-on-white hues, cycled by region order.
export const HIGHLIGHT_PALETTE = [
  "#2563eb", // blue
  "#dc2626", // red
  "#16a34a", // green
  "#d97706", // amber
  "#7c3aed", // violet
  "#db2777", // pink
  "#0891b2", // cyan
  "#ca8a04", // yellow
  "#ea580c", // orange
  "#4f46e5", // indigo
  "#0d9488", // teal
  "#9333ea", // purple
];

export interface DocRegion {
  key: string;
  color: string;
  page: number;
  rects: HighlightRect[]; // image mode: pixel boxes on the page
  cells?: CellRef[]; // spreadsheet mode: grid cells to highlight
  paths: string[]; // field paths whose source is this region
}

export interface Highlights {
  regions: DocRegion[];
  colorByPath: Record<string, string>;
  pageByPath: Record<string, number>;
  regionKeyByPath: Record<string, string>;
}

const round = (n: number) => Math.round(n);

function rectKey(page: number, r: HighlightRect): string {
  return `${page}:${round(r.x)}:${round(r.y)}:${round(r.width)}:${round(r.height)}`;
}

/**
 * Resolve every entry in the grounding map to its page region and assign colors.
 * Fields resolving to the same rect (e.g. several values from one table) collapse
 * into one region sharing a color; each new region takes the next palette color.
 */
export function buildHighlights(
  groundingMap: Record<string, Grounding>,
  ocr: OCRResult | null,
): Highlights {
  const regions: DocRegion[] = [];
  const byKey = new Map<string, DocRegion>();
  const colorByPath: Record<string, string> = {};
  const pageByPath: Record<string, number> = {};
  const regionKeyByPath: Record<string, string> = {};

  if (!ocr) return { regions, colorByPath, pageByPath, regionKeyByPath };

  // Spreadsheet OCR encodes cell coordinates in each block's bbox, so it highlights
  // grid cells (GridViewer) rather than pixel boxes on a page image (PageViewer).
  const spreadsheet = ocr.engine_name === "spreadsheet";

  for (const path of Object.keys(groundingMap)) {
    let page: number;
    let key: string;
    let rects: HighlightRect[] = [];
    let cells: CellRef[] | undefined;

    if (spreadsheet) {
      const fc = cellsForField(path, groundingMap, ocr);
      if (!fc || fc.cells.length === 0) continue;
      page = fc.page;
      cells = fc.cells;
      // Key by the first cell so distinct fields over the same cell merge.
      key = `${page}:c${fc.cells[0].col}:r${fc.cells[0].row}`;
    } else {
      const fh = rectsForField(path, groundingMap, ocr);
      if (!fh || fh.rects.length === 0) continue;
      page = fh.page;
      rects = fh.rects;
      // Key the region by its first rect so distinct fields over the same box merge.
      key = rectKey(fh.page, fh.rects[0]);
    }

    let region = byKey.get(key);
    if (!region) {
      region = {
        key,
        color: HIGHLIGHT_PALETTE[regions.length % HIGHLIGHT_PALETTE.length],
        page,
        rects,
        cells,
        paths: [],
      };
      byKey.set(key, region);
      regions.push(region);
    }
    region.paths.push(path);
    colorByPath[path] = region.color;
    pageByPath[path] = page;
    regionKeyByPath[path] = key;
  }

  return { regions, colorByPath, pageByPath, regionKeyByPath };
}
