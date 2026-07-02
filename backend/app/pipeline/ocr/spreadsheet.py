"""Spreadsheet "OCR" engine: parse CSV/XLSX grids into the normalized OCR shape.

A spreadsheet has no page image, so this engine bypasses rasterization entirely. It
reads the parsed grid written at ingest (``data/<doc_id>/sheets.json``) and emits one
:class:`OCRPage` per sheet where each non-empty cell becomes an :class:`OCRBlock` whose
``bbox`` encodes the cell's **grid coordinates** ``(col, row, col+1, row+1)`` rather than
pixels. The frontend ``GridViewer`` reads those coordinates to highlight the source cell;
everything downstream (structuring, grounding-by-str.find, confidence, rules, decision)
is unchanged because the sheet is also emitted as :class:`OCRTable` markdown, which the
structuring stage already folds into the extractor text.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from app import storage
from app.models import Document, DocumentStatus
from app.schemas import OCRBlock, OCRPage, OCRResult, OCRTable

from .base import OCREngine

# Cell values are exact source data (no recognition), so grounded fields shouldn't be
# penalized on OCR confidence — treat every cell as fully confident.
_CELL_CONFIDENCE = 1.0


def _rows_to_markdown(rows: list[list[str]]) -> str:
    """Render a sheet's rows as a GFM table (first row treated as the header)."""
    if not rows:
        return ""
    n_cols = max((len(r) for r in rows), default=0)
    if n_cols == 0:
        return ""

    def fmt(row: list[str]) -> str:
        cells = [
            (row[i] if i < len(row) else "").replace("|", "\\|").replace("\n", " ")
            for i in range(n_cols)
        ]
        return "| " + " | ".join(cells) + " |"

    lines = [fmt(rows[0]), "| " + " | ".join(["---"] * n_cols) + " |"]
    lines.extend(fmt(r) for r in rows[1:])
    return "\n".join(lines)


class SpreadsheetEngine(OCREngine):
    """Turns a parsed CSV/XLSX workbook into a normalized :class:`OCRResult`.

    Overrides :meth:`run` (the base reads page PNGs, which spreadsheets don't have).
    """

    name = "spreadsheet"
    version = "1.0"

    def _ocr_pages(self, doc_id: str, pages: list[Path]) -> tuple[list[OCRPage], list[str]]:
        # Not used: run() is overridden. Kept to satisfy the abstract base.
        raise NotImplementedError("SpreadsheetEngine overrides run(); _ocr_pages is unused.")

    def warm(self) -> None:  # no local models to load
        return None

    def run(self, doc: Document) -> OCRResult:
        """Build one OCRPage per sheet from the parsed ``sheets.json`` grid."""
        start = perf_counter()
        sheets = self._load_sheets(doc.id)

        pages: list[OCRPage] = []
        warnings: list[str] = []
        for index, sheet in enumerate(sheets, start=1):
            rows: list[list[str]] = sheet.get("rows", [])
            blocks: list[OCRBlock] = []
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    if value == "":
                        continue  # only non-empty cells are grounding targets
                    blocks.append(
                        OCRBlock(
                            page=index,
                            text=value,
                            # bbox = cell grid coords (col, row, col+1, row+1), NOT pixels.
                            bbox=(float(c), float(r), float(c + 1), float(r + 1)),
                            confidence=_CELL_CONFIDENCE,
                            label="cell",
                        )
                    )

            markdown = _rows_to_markdown(rows)
            n_cols = max((len(r) for r in rows), default=0)
            tables = (
                [OCRTable(page=index, n_rows=len(rows), n_cols=n_cols, markdown=markdown, confidence=_CELL_CONFIDENCE)]
                if markdown
                else []
            )
            # Keep the sheet out of page.text (like Docling): the structuring stage folds
            # the table markdown into the extractor text, so cell values still ground.
            pages.append(OCRPage(page=index, text="", blocks=blocks, tables=tables))

            name = sheet.get("name", f"Sheet{index}")
            if sheet.get("truncated_rows"):
                warnings.append(f"sheet '{name}' truncated to the first {storage.MAX_SHEET_ROWS} rows")
            if sheet.get("truncated_cols"):
                warnings.append(f"sheet '{name}' truncated to the first {storage.MAX_SHEET_COLS} columns")

        latency_ms = int((perf_counter() - start) * 1000)
        all_confs = [b.confidence for p in pages for b in p.blocks if b.confidence is not None]
        for page in pages:
            confs = [b.confidence for b in page.blocks if b.confidence is not None]
            page.char_count = len(page.text)
            page.avg_confidence = round(sum(confs) / len(confs), 4) if confs else None

        return OCRResult(
            document_id=doc.id,
            status=DocumentStatus.ocr_done,
            engine_name=self.name,
            engine_version=self.version,
            device=self.device,
            full_text="\n\n".join(p.text for p in pages),
            pages=pages,
            avg_confidence=round(sum(all_confs) / len(all_confs), 4) if all_confs else None,
            table_count=sum(len(p.tables) for p in pages),
            latency_ms=latency_ms,
            warnings=warnings,
        )

    @staticmethod
    def _load_sheets(doc_id: str) -> list[dict]:
        """Load the parsed grid written at ingest; empty list if it's missing/unreadable."""
        path = storage.sheets_json_path(doc_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []
