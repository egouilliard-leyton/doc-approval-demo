// Click-to-bind mapping UI for a spreadsheet template. Left: the shared grid with
// bound cells highlighted. Right rail: a Scalars section (pick a catalogue field,
// optional suffix for numbers, then click a cell to bind) and a Tables section (pick
// a list field, click its anchor cell, choose + order columns, and a row-fill mode).
// The whole cell_map is persisted via PUT /templates/{id}.
import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Crosshair,
  Loader2,
  Plus,
  Table2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group";
import {
  ApiError,
  getListCatalogue,
  getSpreadsheetCells,
  getTemplateCatalogue,
  updateTemplate,
} from "@/lib/api";
import type {
  FieldCatalogueEntry,
  FieldListCatalogueEntry,
  SpreadsheetGrid,
  SpreadsheetMapping,
  SpreadsheetTableBinding,
  TemplateDetail,
} from "@/lib/types";
import { SpreadsheetGridTable } from "@/features/templates/SpreadsheetGridTable";
import type {
  CellHighlight,
  GridSheet,
} from "@/features/templates/SpreadsheetGridTable";

const SCALAR_COLOR = "#7c3aed"; // violet — scalar bindings
const TABLE_COLOR = "#0891b2"; // cyan — table anchors

// What the next grid click will do: place a scalar binding, or place a table anchor.
type Arm =
  | { kind: "scalar"; field_path: string; suffix: string | null }
  | { kind: "table-anchor"; tableIndex: number }
  | null;

function emptyMapping(m: SpreadsheetMapping | undefined | null): SpreadsheetMapping {
  return { scalars: m?.scalars ?? [], tables: m?.tables ?? [] };
}

export function SpreadsheetMappingGrid({
  template,
  onChange,
}: {
  template: TemplateDetail;
  onChange: (t: TemplateDetail) => void;
}) {
  const sheetNames = useMemo(
    () => template.spreadsheet_sheets.map((s) => s.name),
    [template.spreadsheet_sheets],
  );

  const [mapping, setMapping] = useState<SpreadsheetMapping>(() =>
    emptyMapping(template.cell_map),
  );
  const [catalogue, setCatalogue] = useState<FieldCatalogueEntry[]>([]);
  const [listCatalogue, setListCatalogue] = useState<FieldListCatalogueEntry[]>([]);
  const [activeSheet, setActiveSheet] = useState<string>(sheetNames[0] ?? "");
  const [grid, setGrid] = useState<SpreadsheetGrid | null>(null);
  const [gridLoading, setGridLoading] = useState(false);
  const [arm, setArm] = useState<Arm>(null);
  const [saving, setSaving] = useState(false);

  // Scalar picker state.
  const [scalarField, setScalarField] = useState<string>("");
  const [scalarSuffix, setScalarSuffix] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [cat, listCat] = await Promise.all([
          getTemplateCatalogue(template.id),
          getListCatalogue(template.id),
        ]);
        if (!cancelled) {
          setCatalogue(cat);
          setListCatalogue(listCat);
        }
      } catch (e) {
        if (!cancelled)
          toast.error("Could not load the field catalogue", {
            description: e instanceof ApiError ? e.message : String(e),
          });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [template.id]);

  // Fetch the active sheet's grid whenever it changes.
  useEffect(() => {
    if (!activeSheet) return;
    let cancelled = false;
    void (async () => {
      setGridLoading(true);
      try {
        const g = await getSpreadsheetCells(template.id, activeSheet);
        if (!cancelled) setGrid(g);
      } catch (e) {
        if (!cancelled)
          toast.error("Could not load the sheet", {
            description: e instanceof ApiError ? e.message : String(e),
          });
      } finally {
        if (!cancelled) setGridLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [template.id, activeSheet]);

  // Normalize the fetched grid (keyed by `sheet`) to the shared GridSheet shape.
  const gridSheet = useMemo<GridSheet | null>(
    () => (grid ? { ...grid, name: grid.sheet } : null),
    [grid],
  );

  const selectedScalarKind = useMemo(
    () => catalogue.find((c) => c.path === scalarField)?.kind,
    [catalogue, scalarField],
  );

  // Persist the mapping and reflect the canonical result back to the parent.
  async function save(next: SpreadsheetMapping) {
    setMapping(next);
    setSaving(true);
    try {
      const updated = await updateTemplate(template.id, { cell_map: next });
      onChange(updated);
      setMapping(emptyMapping(updated.cell_map));
    } catch (e) {
      toast.error("Could not save the mapping", {
        description: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setSaving(false);
    }
  }

  function handleCellClick(sheet: string, address: string) {
    if (!arm) return;
    if (arm.kind === "scalar") {
      const scalars = mapping.scalars.filter(
        (s) => !(s.sheet === sheet && s.cell === address),
      );
      scalars.push({
        sheet,
        cell: address,
        field_path: arm.field_path,
        suffix: arm.suffix,
        is_signature: false,
      });
      void save({ ...mapping, scalars });
    } else {
      const tables = mapping.tables.map((t, i) =>
        i === arm.tableIndex ? { ...t, sheet, anchor_cell: address } : t,
      );
      void save({ ...mapping, tables });
    }
    setArm(null);
  }

  // Highlights for the active sheet: scalar cells + table anchors.
  const highlightedCells = useMemo(() => {
    const map = new Map<string, CellHighlight>();
    for (const s of mapping.scalars) {
      if (s.sheet !== activeSheet) continue;
      map.set(s.cell, {
        color: SCALAR_COLOR,
        label: catalogue.find((c) => c.path === s.field_path)?.label,
      });
    }
    for (const t of mapping.tables) {
      if (t.sheet !== activeSheet || !t.anchor_cell) continue;
      map.set(t.anchor_cell, { color: TABLE_COLOR, label: t.list_path });
    }
    return map;
  }, [mapping, activeSheet, catalogue]);

  function armScalar() {
    if (!scalarField) return;
    setArm({
      kind: "scalar",
      field_path: scalarField,
      suffix: scalarSuffix.trim() || null,
    });
  }

  function removeScalar(idx: number) {
    void save({
      ...mapping,
      scalars: mapping.scalars.filter((_, i) => i !== idx),
    });
  }

  // --- tables ---------------------------------------------------------------

  const usedListPaths = useMemo(
    () => new Set(mapping.tables.map((t) => t.list_path)),
    [mapping.tables],
  );
  const availableLists = listCatalogue.filter((e) => !usedListPaths.has(e.list_path));

  function addTable(listPath: string) {
    const entry = listCatalogue.find((e) => e.list_path === listPath);
    if (!entry) return;
    const table: SpreadsheetTableBinding = {
      sheet: activeSheet,
      list_path: listPath,
      anchor_cell: "",
      row_mode: "fill_next_empty_row",
      columns: [],
    };
    void save({ ...mapping, tables: [...mapping.tables, table] });
  }

  function removeTable(idx: number) {
    void save({ ...mapping, tables: mapping.tables.filter((_, i) => i !== idx) });
  }

  function updateTable(idx: number, patch: Partial<SpreadsheetTableBinding>) {
    return mapping.tables.map((t, i) => (i === idx ? { ...t, ...patch } : t));
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0">
        <SpreadsheetGridTable
          grid={gridSheet}
          sheetNames={sheetNames}
          activeSheet={activeSheet}
          onSheetChange={setActiveSheet}
          onCellClick={handleCellClick}
          highlightedCells={highlightedCells}
          loading={gridLoading}
        />
      </div>

      <div className="space-y-6">
        {arm && (
          <div className="flex items-center gap-2 rounded-lg border border-brand/40 bg-brand/5 px-3 py-2 text-sm">
            <Crosshair className="size-4 shrink-0 text-brand" />
            <span className="flex-1">
              Click a cell to {arm.kind === "scalar" ? "bind the field" : "set the anchor"}.
            </span>
            <button
              className="text-muted-foreground hover:text-foreground"
              onClick={() => setArm(null)}
              aria-label="Cancel binding"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )}

        {/* Scalars ---------------------------------------------------------- */}
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">Scalar fields</h3>
            {saving && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
          </div>

          <div className="space-y-2 rounded-lg border p-3">
            <div className="space-y-1.5">
              <Label className="text-xs">Field</Label>
              <Select value={scalarField} onValueChange={setScalarField}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Pick a field…" />
                </SelectTrigger>
                <SelectContent>
                  {catalogue.map((c) => (
                    <SelectItem key={c.path} value={c.path}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {selectedScalarKind === "number" && (
              <div className="space-y-1.5">
                <Label className="text-xs">Suffix (optional, e.g. USD)</Label>
                <Input
                  value={scalarSuffix}
                  onChange={(e) => setScalarSuffix(e.target.value)}
                  placeholder="USD"
                  className="h-8"
                />
              </div>
            )}

            <Button
              size="sm"
              variant={arm?.kind === "scalar" ? "default" : "outline"}
              disabled={!scalarField}
              onClick={armScalar}
              className="w-full"
            >
              <Crosshair className="size-4" />
              Click a cell to bind
            </Button>
          </div>

          {mapping.scalars.length > 0 && (
            <ul className="space-y-1.5">
              {mapping.scalars.map((s, i) => (
                <li
                  key={`${s.sheet}!${s.cell}`}
                  className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm"
                >
                  <span
                    className="inline-block size-2.5 shrink-0 rounded-sm"
                    style={{ backgroundColor: SCALAR_COLOR }}
                  />
                  <span className="font-mono text-xs text-muted-foreground">
                    {s.sheet}!{s.cell}
                  </span>
                  <span className="min-w-0 flex-1 truncate">
                    {catalogue.find((c) => c.path === s.field_path)?.label ??
                      s.field_path}
                    {s.suffix ? (
                      <span className="text-muted-foreground"> · {s.suffix}</span>
                    ) : null}
                  </span>
                  <button
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => removeScalar(i)}
                    aria-label="Remove binding"
                  >
                    <X className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Tables ----------------------------------------------------------- */}
        <section className="space-y-3">
          <h3 className="text-sm font-semibold">Tables (repeating rows)</h3>

          {mapping.tables.map((table, ti) => {
            const entry = listCatalogue.find((e) => e.list_path === table.list_path);
            const cols = [...table.columns].sort((a, b) => a.order - b.order);
            const usedCols = new Set(cols.map((c) => c.field_path));
            const availableCols =
              entry?.columns.filter((c) => !usedCols.has(c.path)) ?? [];
            return (
              <div key={table.list_path} className="space-y-3 rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <Table2 className="size-4 text-muted-foreground" />
                  <span className="flex-1 text-sm font-medium">
                    {entry?.label ?? table.list_path}
                  </span>
                  <button
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => removeTable(ti)}
                    aria-label="Remove table"
                  >
                    <X className="size-3.5" />
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant={
                      arm?.kind === "table-anchor" && arm.tableIndex === ti
                        ? "default"
                        : "outline"
                    }
                    onClick={() => setArm({ kind: "table-anchor", tableIndex: ti })}
                  >
                    <Crosshair className="size-4" />
                    {table.anchor_cell ? "Change anchor" : "Pick anchor cell"}
                  </Button>
                  {table.anchor_cell && (
                    <Badge variant="outline" className="font-mono text-xs">
                      {table.sheet}!{table.anchor_cell}
                    </Badge>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs">Row mode</Label>
                  <ToggleGroup
                    type="single"
                    variant="outline"
                    value={table.row_mode}
                    onValueChange={(v) => {
                      if (v)
                        void save({
                          ...mapping,
                          tables: updateTable(ti, {
                            row_mode: v as SpreadsheetTableBinding["row_mode"],
                          }),
                        });
                    }}
                    className="justify-start"
                  >
                    <ToggleGroupItem value="fill_next_empty_row" className="text-xs">
                      Fill rows
                    </ToggleGroupItem>
                    <ToggleGroupItem value="insert_row" className="text-xs">
                      Insert rows
                    </ToggleGroupItem>
                  </ToggleGroup>
                  {table.row_mode === "insert_row" && (
                    <p className="text-xs text-muted-foreground">
                      Tip: totals below the table should use whole-column ranges like
                      =SUM(D:D); bounded ranges are auto-expanded where possible — verify in
                      the preview.
                    </p>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs">Columns (in write order)</Label>
                  {cols.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      No columns yet — add one below.
                    </p>
                  )}
                  {cols.map((col, ci) => {
                    const colLabel =
                      entry?.columns.find((c) => c.path === col.field_path)?.label ??
                      (col.field_path || entry?.label || "value");
                    return (
                      <div
                        key={col.field_path || "__self__"}
                        className="flex items-center gap-1.5"
                      >
                        <span className="min-w-0 flex-1 truncate text-xs">
                          {colLabel}
                        </span>
                        <Input
                          value={col.col}
                          onChange={(e) => {
                            const letter = e.target.value.toUpperCase().replace(/[^A-Z]/g, "");
                            setMapping({
                              ...mapping,
                              tables: updateTable(ti, {
                                columns: table.columns.map((c) =>
                                  c.field_path === col.field_path
                                    ? { ...c, col: letter }
                                    : c,
                                ),
                              }),
                            });
                          }}
                          onBlur={() => void save(mapping)}
                          placeholder="Col"
                          className="h-7 w-14 text-center font-mono text-xs"
                          aria-label="Target column letter"
                        />
                        <Input
                          value={col.suffix ?? ""}
                          onChange={(e) => {
                            setMapping({
                              ...mapping,
                              tables: updateTable(ti, {
                                columns: table.columns.map((c) =>
                                  c.field_path === col.field_path
                                    ? { ...c, suffix: e.target.value || null }
                                    : c,
                                ),
                              }),
                            });
                          }}
                          onBlur={() => void save(mapping)}
                          placeholder="Suffix"
                          className="h-7 w-16 text-xs"
                          aria-label="Optional suffix"
                        />
                        <button
                          className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                          disabled={ci === 0}
                          onClick={() => void save({ ...mapping, tables: reorder(mapping, ti, ci, -1) })}
                          aria-label="Move up"
                        >
                          <ArrowUp className="size-3.5" />
                        </button>
                        <button
                          className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                          disabled={ci === cols.length - 1}
                          onClick={() => void save({ ...mapping, tables: reorder(mapping, ti, ci, 1) })}
                          aria-label="Move down"
                        >
                          <ArrowDown className="size-3.5" />
                        </button>
                        <button
                          className="text-muted-foreground hover:text-foreground"
                          onClick={() =>
                            void save({
                              ...mapping,
                              tables: updateTable(ti, {
                                columns: table.columns.filter(
                                  (c) => c.field_path !== col.field_path,
                                ),
                              }),
                            })
                          }
                          aria-label="Remove column"
                        >
                          <X className="size-3.5" />
                        </button>
                      </div>
                    );
                  })}

                  {availableCols.length > 0 && (
                    <Select
                      value=""
                      onValueChange={(path) => {
                        const nextOrder =
                          cols.length > 0
                            ? Math.max(...cols.map((c) => c.order)) + 1
                            : 0;
                        void save({
                          ...mapping,
                          tables: updateTable(ti, {
                            columns: [
                              ...table.columns,
                              { order: nextOrder, col: "", field_path: path, suffix: null },
                            ],
                          }),
                        });
                      }}
                    >
                      <SelectTrigger className="h-8 w-full">
                        <SelectValue placeholder="Add a column…" />
                      </SelectTrigger>
                      <SelectContent>
                        {availableCols.map((c) => (
                          <SelectItem key={c.path || "__self__"} value={c.path}>
                            {c.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
              </div>
            );
          })}

          {availableLists.length > 0 && (
            <Select value="" onValueChange={addTable}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Add a table binding…" />
              </SelectTrigger>
              <SelectContent>
                {availableLists.map((e) => (
                  <SelectItem key={e.list_path} value={e.list_path}>
                    <Plus className="size-3.5" />
                    {e.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {listCatalogue.length === 0 && (
            <p className="text-xs text-muted-foreground">
              This document type has no repeating list fields.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

// Swap a column with its neighbour (dir -1 up / +1 down) and renumber `order`.
function reorder(
  mapping: SpreadsheetMapping,
  tableIndex: number,
  colIndex: number,
  dir: -1 | 1,
): SpreadsheetTableBinding[] {
  return mapping.tables.map((t, i) => {
    if (i !== tableIndex) return t;
    const cols = [...t.columns].sort((a, b) => a.order - b.order);
    const j = colIndex + dir;
    if (j < 0 || j >= cols.length) return t;
    [cols[colIndex], cols[j]] = [cols[j], cols[colIndex]];
    return { ...t, columns: cols.map((c, k) => ({ ...c, order: k })) };
  });
}
