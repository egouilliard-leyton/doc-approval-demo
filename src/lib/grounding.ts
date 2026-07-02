// Hover-to-highlight: resolve a structured field path through grounding_map to the
// OCRBlock bbox(es) whose text overlaps the grounded snippet/offsets, so we can draw
// a box on the rasterized page image.
import type { Alignment, Grounding, OCRBlock, OCRResult } from "@/lib/types";

/** A rectangle in page-natural pixel space, top-left origin. */
export interface HighlightRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A 0-indexed cell coordinate within a sheet (spreadsheet grounding). */
export interface CellRef {
  row: number;
  col: number;
}

export interface FieldHighlight {
  page: number;
  rects: HighlightRect[];
  alignment: Alignment | null;
}

export interface FieldCells {
  page: number; // 1-based sheet index
  cells: CellRef[];
  alignment: Alignment | null;
}

/**
 * Whitespace/case-tolerant normalization for fuzzy containment matching, aware of
 * markdown/table scaffolding. Applied symmetrically to both a snippet and a block's
 * text, so `.includes()` stays symmetric only if the two sides collapse identically.
 *
 * Ordering matters: all scaffolding (separator rows, pipe delimiters, stray punctuation)
 * is turned into or stripped to boundaries BEFORE a single final whitespace-collapse.
 * Collapsing whitespace first would leave orphaned double-spaces once a pipe wrapped in
 * spaces (`"| $85.00 |"`) is stripped, breaking containment against a single-spaced
 * plain-text block. Separator runs (`---`) become a space so a `| --- |` row collapses
 * away, but single hyphens are preserved so identifiers (`PO-9911`, `#INV-3337`) survive.
 */
export function normalizeForMatch(s: string): string {
  return s
    .toLowerCase()
    .replace(/-{2,}/g, " ") // markdown separator runs -> boundary (keep single hyphens)
    .replace(/\|/g, " ") // table delimiters -> word boundary, not glued values
    .replace(/[^\w .,/$%@-]/g, "") // drop stray punctuation (#, :, *) symmetrically
    .replace(/\s+/g, " ") // collapse whitespace LAST, after scaffolding is gone
    .trim();
}

function rectFromBlock(b: OCRBlock): HighlightRect {
  const [x0, y0, x1, y1] = b.bbox;
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

/**
 * Blocks on the grounded page whose text overlaps the grounding. Primary match
 * is normalized snippet/text containment (a snippet may span several blocks);
 * the fallback walks blocks by accumulated text length to cover the char range.
 */
export function blocksForGrounding(g: Grounding, ocr: OCRResult): OCRBlock[] {
  if (g.page == null) return [];
  const page = ocr.pages.find((p) => p.page === g.page);
  if (!page) return [];

  // Primary: snippet-based containment.
  const snippet = g.snippet ? normalizeForMatch(g.snippet) : "";
  if (snippet.length >= 2) {
    const hits = page.blocks.filter((b) => {
      const t = normalizeForMatch(b.text);
      if (!t) return false;
      return t.includes(snippet) || snippet.includes(t);
    });
    if (hits.length) return hits;
  }

  // Fallback: walk blocks accumulating page-local char offsets and intersect
  // with [char_start, char_end). Offsets index OCRResult.full_text, so rebase
  // to this page by subtracting the page's start offset within full_text.
  if (g.char_start != null && g.char_end != null) {
    const pageStart = pageStartOffset(ocr, g.page);
    if (pageStart != null) {
      const localStart = g.char_start - pageStart;
      const localEnd = g.char_end - pageStart;
      const hits: OCRBlock[] = [];
      let cursor = 0;
      for (const b of page.blocks) {
        const bStart = cursor;
        const bEnd = cursor + b.text.length;
        if (bStart < localEnd && bEnd > localStart) hits.push(b);
        cursor = bEnd + 1; // blocks joined by a separator char
      }
      if (hits.length) return hits;
    }
  }
  return [];
}

/**
 * Rect for a field grounded to a table cell (invoice no, totals, dates), which
 * has no text block. Highlights the whole containing table's bbox: match the
 * grounded snippet against each table's markdown on the grounded page.
 */
export function tableRectForGrounding(
  g: Grounding,
  ocr: OCRResult,
): HighlightRect | null {
  if (g.page == null) return null;
  const page = ocr.pages.find((p) => p.page === g.page);
  if (!page) return null;
  const snippet = g.snippet ? normalizeForMatch(g.snippet) : "";
  if (snippet.length < 2) return null;
  for (const t of page.tables) {
    if (!t.bbox || !t.markdown) continue;
    if (normalizeForMatch(t.markdown).includes(snippet)) {
      const [x0, y0, x1, y1] = t.bbox;
      return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
    }
  }
  return null;
}

/** Start offset of `page` within OCRResult.full_text ("\n\n".join of page texts). */
function pageStartOffset(ocr: OCRResult, page: number): number | null {
  let offset = 0;
  for (const p of ocr.pages) {
    if (p.page === page) return offset;
    offset += p.text.length + 2; // "\n\n" joiner
  }
  return null;
}

/** Resolve a field path to its source rectangles (in natural pixel space). */
export function rectsForField(
  fieldPath: string,
  groundingMap: Record<string, Grounding>,
  ocr: OCRResult | null,
): FieldHighlight | null {
  const g = groundingMap[fieldPath];
  if (!g || g.page == null || g.alignment === "ungrounded") return null;
  // Fast path: a spatially-grounded field (the signature post-pass) carries its own
  // pixel bbox — draw it directly, with no OCR-block matching and no OCR result needed.
  if (g.bbox) {
    const [x0, y0, x1, y1] = g.bbox;
    const rect: HighlightRect = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
    return { page: g.page, rects: [rect], alignment: g.alignment };
  }
  if (!ocr) return null;
  const blocks = blocksForGrounding(g, ocr);
  if (blocks.length) {
    return {
      page: g.page,
      rects: blocks.map(rectFromBlock),
      alignment: g.alignment,
    };
  }
  // No text block matched — the field likely came from a table cell (invoice no,
  // dates, totals). Highlight the containing table's region instead.
  const tableRect = tableRectForGrounding(g, ocr);
  if (tableRect) {
    return { page: g.page, rects: [tableRect], alignment: g.alignment };
  }
  return null;
}

/**
 * Resolve a field path to its source cell(s) for the spreadsheet grid. Reuses the
 * same block matching as the image path, but reads each matched block's bbox as
 * grid coordinates `(col, row, col+1, row+1)` (SpreadsheetEngine encoding) rather
 * than pixels.
 */
export function cellsForField(
  fieldPath: string,
  groundingMap: Record<string, Grounding>,
  ocr: OCRResult | null,
): FieldCells | null {
  if (!ocr) return null;
  const g = groundingMap[fieldPath];
  if (!g || g.page == null || g.alignment === "ungrounded") return null;
  const blocks = blocksForGrounding(g, ocr);
  if (!blocks.length) return null;
  const cells = blocks.map((b) => ({
    col: Math.round(b.bbox[0]),
    row: Math.round(b.bbox[1]),
  }));
  return { page: g.page, cells, alignment: g.alignment };
}

/** Column index (0-based) to spreadsheet letters: 0->A, 25->Z, 26->AA. */
export function colToLetters(col: number): string {
  let n = col;
  let out = "";
  do {
    out = String.fromCharCode(65 + (n % 26)) + out;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return out;
}

/**
 * A1 source reference per field path for the spreadsheet inspector, e.g.
 * `Invoice!B2` (or just `B2` when the sheet name is unknown). Uses the first
 * matched cell of each grounded field.
 */
export function cellRefsForFields(
  groundingMap: Record<string, Grounding>,
  ocr: OCRResult | null,
  sheetNames: string[] = [],
): Record<string, string> {
  const out: Record<string, string> = {};
  if (!ocr) return out;
  for (const path of Object.keys(groundingMap)) {
    const fc = cellsForField(path, groundingMap, ocr);
    if (!fc || fc.cells.length === 0) continue;
    const c = fc.cells[0];
    const a1 = `${colToLetters(c.col)}${c.row + 1}`;
    const name = sheetNames[fc.page - 1];
    out[path] = name ? `${name}!${a1}` : a1;
  }
  return out;
}

/** Scale natural-pixel rects to the rendered <img> CSS size. */
export function scaleRects(
  rects: HighlightRect[],
  natural: { width: number; height: number },
  displayed: { width: number; height: number },
): HighlightRect[] {
  if (!natural.width || !natural.height) return [];
  const sx = displayed.width / natural.width;
  const sy = displayed.height / natural.height;
  return rects.map((r) => ({
    x: r.x * sx,
    y: r.y * sy,
    width: r.width * sx,
    height: r.height * sy,
  }));
}
