import { describe, expect, it } from "vitest";
import {
  blocksForGrounding,
  cellRefsForFields,
  cellsForField,
  colToLetters,
  normalizeForMatch,
  rectsForField,
} from "@/lib/grounding";
import { buildHighlights } from "@/lib/highlights";
import type { Grounding, OCRBlock, OCRResult } from "@/lib/types";

function cellBlock(text: string, col: number, row: number): OCRBlock {
  return {
    page: 1,
    text,
    bbox: [col, row, col + 1, row + 1], // SpreadsheetEngine encoding
    confidence: 1,
    label: "cell",
  };
}

/** An image-mode OCR block: a real pixel bbox on the rasterized page. */
function imageBlock(text: string, bbox: [number, number, number, number]): OCRBlock {
  return { page: 1, text, bbox, confidence: 1, label: "text" };
}

/** A one-page image-mode OCR result carrying plain-text blocks (pixel bboxes). */
function imageOcr(blocks: OCRBlock[]): OCRResult {
  return {
    document_id: "d",
    status: "ocr_done",
    engine_name: "qwen-vl",
    engine_version: "1.0",
    device: "cpu",
    full_text: blocks.map((b) => b.text).join("\n"),
    pages: [
      { page: 1, text: blocks.map((b) => b.text).join("\n"), blocks, tables: [], avg_confidence: 1, char_count: 0, markdown_url: null },
    ],
    avg_confidence: 1,
    table_count: 0,
    latency_ms: 0,
    warnings: [],
  };
}

function spreadsheetOcr(blocks: OCRBlock[]): OCRResult {
  return {
    document_id: "d",
    status: "ocr_done",
    engine_name: "spreadsheet",
    engine_version: "1.0",
    device: "cpu",
    full_text: "",
    pages: [
      { page: 1, text: "", blocks, tables: [], avg_confidence: 1, char_count: 0, markdown_url: null },
    ],
    avg_confidence: 1,
    table_count: 1,
    latency_ms: 0,
    warnings: [],
  };
}

const grounded = (snippet: string): Grounding => ({
  page: 1,
  char_start: null,
  char_end: null,
  snippet,
  alignment: "exact",
});

describe("colToLetters", () => {
  it("maps column indices to spreadsheet letters", () => {
    expect(colToLetters(0)).toBe("A");
    expect(colToLetters(25)).toBe("Z");
    expect(colToLetters(26)).toBe("AA");
    expect(colToLetters(27)).toBe("AB");
  });
});

describe("cellsForField", () => {
  it("reads a matched block's bbox as (col,row) grid coords", () => {
    const ocr = spreadsheetOcr([cellBlock("Acme", 0, 1), cellBlock("1234.56", 1, 2)]);
    const fc = cellsForField("total", { total: grounded("1234.56") }, ocr);
    expect(fc).toEqual({ page: 1, cells: [{ row: 2, col: 1 }], alignment: "exact" });
  });

  it("returns null for ungrounded fields", () => {
    const ocr = spreadsheetOcr([cellBlock("Acme", 0, 0)]);
    const g: Grounding = { page: null, char_start: null, char_end: null, snippet: null, alignment: "ungrounded" };
    expect(cellsForField("x", { x: g }, ocr)).toBeNull();
  });
});

describe("cellRefsForFields", () => {
  it("labels each grounded field with its A1 source cell + sheet name", () => {
    const ocr = spreadsheetOcr([cellBlock("Globex", 0, 1), cellBlock("1320.00", 3, 13)]);
    const refs = cellRefsForFields(
      { vendor: grounded("Globex"), total: grounded("1320.00") },
      ocr,
      ["Invoice"],
    );
    expect(refs.vendor).toBe("Invoice!A2");
    expect(refs.total).toBe("Invoice!D14");
  });

  it("falls back to a bare A1 when the sheet name is unknown", () => {
    const ocr = spreadsheetOcr([cellBlock("Globex", 1, 0)]);
    const refs = cellRefsForFields({ vendor: grounded("Globex") }, ocr, []);
    expect(refs.vendor).toBe("B1");
  });
});

describe("buildHighlights (spreadsheet mode)", () => {
  it("produces cell regions and a color per path", () => {
    const ocr = spreadsheetOcr([cellBlock("Acme", 0, 1), cellBlock("1234.56", 1, 2)]);
    const hl = buildHighlights(
      { vendor: grounded("Acme"), total: grounded("1234.56") },
      ocr,
    );
    expect(hl.regions).toHaveLength(2);
    expect(hl.regions.every((r) => r.cells && r.cells.length === 1)).toBe(true);
    expect(hl.pageByPath.total).toBe(1);
    expect(hl.colorByPath.vendor).toBeDefined();
    expect(hl.colorByPath.vendor).not.toBe(hl.colorByPath.total);
  });
});

describe("normalizeForMatch", () => {
  it("re-anchors a scaffolded table row to its plain value cell", () => {
    // Before the ordering fix, the pipes wrapped in spaces left orphaned double
    // spaces after the punctuation strip, so containment broke both ways.
    const snippet = normalizeForMatch("| 1.00 | Web Design | $85.00 | 0.00% |");
    const block = normalizeForMatch("$85.00");
    expect(snippet.includes(block)).toBe(true);
  });

  it("strips a leading # symmetrically so an id matches its bare form", () => {
    expect(normalizeForMatch("#INV-3337")).toBe(normalizeForMatch("INV-3337"));
  });

  it("keeps single hyphens but collapses markdown separator runs", () => {
    // Real identifiers survive; a `| --- | --- |` separator row collapses to nothing.
    expect(normalizeForMatch("PO-9911")).toBe("po-9911");
    expect(normalizeForMatch("| --- | --- |").trim()).toBe("");
  });
});

describe("rectsForField (spatial bbox fast path)", () => {
  it("draws a grounding's own pixel bbox directly, with no OCR result needed", () => {
    const g: Grounding = {
      page: 2,
      char_start: null,
      char_end: null,
      snippet: null,
      alignment: "exact",
      bbox: [10, 20, 110, 80],
      image_url: "/files/d/signatures/page-002-sig-00.png",
    };
    // Passing ocr=null proves the fast path skips OCR-block matching entirely.
    const hl = rectsForField("signatures.0", { "signatures.0": g }, null);
    expect(hl).toEqual({
      page: 2,
      rects: [{ x: 10, y: 20, width: 100, height: 60 }],
      alignment: "exact",
    });
  });
});

describe("blocksForGrounding (image mode)", () => {
  it("resolves a scaffolded pipe-delimited row to its plain-text value block", () => {
    const ocr = imageOcr([
      imageBlock("Web Design", [10, 10, 90, 20]),
      imageBlock("$85.00", [100, 10, 140, 20]),
    ]);
    const g = grounded("| 1.00 | Web Design | $85.00 | 0.00% |");
    const hits = blocksForGrounding(g, ocr);
    const texts = hits.map((b) => b.text);
    expect(texts).toContain("$85.00");
  });
});
