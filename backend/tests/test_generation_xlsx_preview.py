"""Spreadsheet preview tests: LibreOffice recompute + cache + degrading fallback.

The LibreOffice round-trip / cache tests skip when ``soffice`` is absent; the fallback and
raw-formula-grid tests are pure openpyxl and always run. No network.
"""

from __future__ import annotations

import shutil
from types import SimpleNamespace
from unittest import mock

import pytest

from app import storage
from app.config import settings
from app.models import _new_id
from app.pipeline.generation import (
    convert_to_pdf,
    fill_spreadsheet,
    read_computed_grid,
    recompute_workbook,
)
from app.pipeline.generation import xlsx_preview

from .generation_fixtures import make_xlsx_template

_HAS_SOFFICE = shutil.which("soffice") is not None
_skip_no_lo = pytest.mark.skipif(not _HAS_SOFFICE, reason="LibreOffice (soffice) not installed")


def _fv(value):
    return {"value": value, "confidence": 0.9, "grounding": None}


_FIELDS = {
    "line_items": [
        {"desc": _fv("Widget"), "qty": _fv(2), "unit_price": _fv(50.0), "amount": _fv(100.0)},
    ],
}

# A table binding whose fill leaves the D4 `=B4*C4` formula computable (2*50 -> 100).
_CELL_MAP = {
    "scalars": [],
    "tables": [
        {
            "sheet": "Invoice",
            "list_path": "line_items",
            "anchor_cell": "A4",
            "row_mode": "fill_next_empty_row",
            "columns": [
                {"order": 0, "col": "B", "field_path": "qty"},
                {"order": 1, "col": "C", "field_path": "unit_price"},
            ],
        }
    ],
}


def _filled_bytes(tid: str) -> bytes:
    storage.save_template_source(tid, ".xlsx", make_xlsx_template())
    tmpl = SimpleNamespace(id=tid, source_ext=".xlsx", cell_map=_CELL_MAP)
    return fill_spreadsheet(tmpl, _FIELDS).content


# --- LibreOffice recompute (gated on soffice) ---------------------------------


@_skip_no_lo
def test_recompute_roundtrip_computes_formulas():
    tid = _new_id()
    try:
        content = _filled_bytes(tid)
        result = recompute_workbook(tid, content)
        assert result.computed is True
        assert result.warnings == []

        sheets = read_computed_grid(result.xlsx_bytes)
        by_addr = {c.address: c for s in sheets for c in s.cells}
        # =B4*C4 with B4=2, C4=50 -> 100, now a computed value (not a formula string).
        assert by_addr["D4"].value == "100"
        assert by_addr["D4"].computed is True
        assert all(s.computed for s in sheets)
    finally:
        storage.delete_template_dir(tid)


@_skip_no_lo
def test_recompute_cache_hit_skips_second_subprocess():
    tid = _new_id()
    try:
        content = _filled_bytes(tid)
        # Spy on the real soffice runner; the cache short-circuits it on the 2nd call.
        with mock.patch.object(
            xlsx_preview, "_run_soffice", wraps=xlsx_preview._run_soffice
        ) as spy:
            first = recompute_workbook(tid, content)
            assert first.computed is True and first.cache_hit is False
            assert spy.call_count == 1

            second = recompute_workbook(tid, content)
            assert second.computed is True and second.cache_hit is True
            assert spy.call_count == 1  # no second soffice invocation
        assert first.xlsx_bytes == second.xlsx_bytes
    finally:
        storage.delete_template_dir(tid)


@_skip_no_lo
def test_convert_to_pdf_produces_pdf_bytes():
    tid = _new_id()
    try:
        content = _filled_bytes(tid)
        pdf = convert_to_pdf(content)
        assert pdf.startswith(b"%PDF")
    finally:
        storage.delete_template_dir(tid)


# --- degrading fallback (no soffice needed) -----------------------------------


def test_recompute_bogus_soffice_degrades_without_raising(monkeypatch):
    """A missing/bogus soffice binary yields computed=False + a warning, never raises."""
    monkeypatch.setattr(settings, "xlsx_soffice_path", "/nonexistent/definitely-not-soffice")
    tid = _new_id()
    try:
        content = _filled_bytes(tid)
        result = recompute_workbook(tid, content)
        assert result.computed is False
        assert result.xlsx_bytes == content  # the uncomputed filled bytes come back
        assert result.warnings and any("recompute unavailable" in w for w in result.warnings)
    finally:
        storage.delete_template_dir(tid)


def test_read_computed_grid_flags_uncomputed_formulas():
    """Reading UNcomputed bytes flags formula cells computed=False with their raw formula."""
    tid = _new_id()
    try:
        content = _filled_bytes(tid)  # never sent through LibreOffice
        sheets = read_computed_grid(content)
        by_addr = {c.address: c for s in sheets for c in s.cells}
        # The =B4*C4 formula has no cached result, so it shows raw + computed=False.
        assert by_addr["D4"].is_formula is True
        assert by_addr["D4"].computed is False
        assert by_addr["D4"].value == "=B4*C4"
        # A sheet with any uncomputed formula is itself flagged not-computed.
        assert any(s.computed is False for s in sheets)
    finally:
        storage.delete_template_dir(tid)


def test_convert_to_pdf_bogus_soffice_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "xlsx_soffice_path", "/nonexistent/definitely-not-soffice")
    tid = _new_id()
    try:
        content = _filled_bytes(tid)
        assert convert_to_pdf(content) == b""
    finally:
        storage.delete_template_dir(tid)
