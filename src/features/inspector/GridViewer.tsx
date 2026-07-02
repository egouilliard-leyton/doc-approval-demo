import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { getSheets } from "@/lib/api";
import { colToLetters } from "@/lib/grounding";
import type { DocRegion } from "@/lib/highlights";
import type { Sheet } from "@/lib/types";

/** Per-cell highlight resolved from the regions covering the active sheet. */
interface CellHit {
  color: string;
  selected: boolean;
  active: boolean;
}

export function GridViewer({
  docId,
  page,
  regions,
  selectedKey,
  hoveredKey,
  flashTick,
  onPageChange,
}: {
  docId: string;
  page: number; // 1-based sheet index
  regions: DocRegion[]; // all sheets; filtered to `page` here
  selectedKey: string | null;
  hoveredKey: string | null;
  flashTick: number;
  onPageChange: (page: number) => void;
}) {
  // Keyed by docId so a stale fetch (or the previous doc's data) never shows for the
  // current doc, without a synchronous reset in the effect body.
  const [loaded, setLoaded] = useState<{ docId: string; sheets: Sheet[] } | null>(
    null,
  );
  const [failed, setFailed] = useState<string | null>(null);
  const selectedCellRef = useRef<HTMLTableCellElement>(null);

  useEffect(() => {
    let cancelled = false;
    getSheets(docId)
      .then((s) => {
        if (!cancelled) setLoaded({ docId, sheets: s });
      })
      .catch(() => {
        if (!cancelled) setFailed(docId);
      });
    return () => {
      cancelled = true;
    };
  }, [docId]);

  const sheets = loaded?.docId === docId ? loaded.sheets : null;
  const error = failed === docId ? "Could not load the spreadsheet." : null;

  // Bring the selected cell into view when the selection (or its replay) changes.
  useLayoutEffect(() => {
    selectedCellRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
      inline: "center",
    });
  }, [selectedKey, flashTick, page]);

  // "row:col" -> highlight for cells on the active sheet.
  const cellHits = useMemo(() => {
    const map = new Map<string, CellHit>();
    for (const region of regions) {
      if (region.page !== page || !region.cells) continue;
      const selected = region.key === selectedKey;
      const active = selected || region.key === hoveredKey;
      for (const c of region.cells) {
        const key = `${c.row}:${c.col}`;
        // Selected/active wins if multiple regions touch the same cell.
        const prev = map.get(key);
        if (!prev || (active && !prev.active)) {
          map.set(key, { color: region.color, selected, active });
        }
      }
    }
    return map;
  }, [regions, page, selectedKey, hoveredKey]);

  const sheet = sheets?.[page - 1];
  const nCols = useMemo(
    () => (sheet ? sheet.rows.reduce((m, r) => Math.max(m, r.length), 0) : 0),
    [sheet],
  );

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="relative flex-1 overflow-auto rounded-xl border bg-muted/40">
        {error ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            {error}
          </div>
        ) : !sheets ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            Loading spreadsheet…
          </div>
        ) : !sheet || sheet.rows.length === 0 ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            This sheet is empty.
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
              {sheet.rows.map((row, r) => (
                <tr key={r}>
                  <th className="sticky left-0 z-10 border bg-muted px-2 py-1 text-right font-normal text-muted-foreground">
                    {r + 1}
                  </th>
                  {Array.from({ length: nCols }, (_, c) => {
                    const hit = cellHits.get(`${r}:${c}`);
                    return (
                      <td
                        key={c}
                        ref={hit?.selected ? selectedCellRef : undefined}
                        className={cn(
                          "max-w-[16rem] truncate border px-2 py-1",
                          hit?.selected && "hl-flash",
                        )}
                        title={c < row.length ? row[c] : undefined}
                        style={
                          hit
                            ? {
                                backgroundColor: `${hit.color}${hit.active ? "33" : "1f"}`,
                                outline: `${hit.selected ? 2 : 1}px solid ${hit.color}`,
                                outlineOffset: "-1px",
                              }
                            : undefined
                        }
                      >
                        {c < row.length ? row[c] : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {sheet && (sheet.truncated_rows || sheet.truncated_cols) && (
        <p className="text-xs text-amber-600">
          Large sheet truncated for display
          {sheet.truncated_rows ? " (rows)" : ""}
          {sheet.truncated_cols ? " (columns)" : ""}.
        </p>
      )}

      {sheets && sheets.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {sheets.map((s, i) => (
            <button
              key={i}
              onClick={() => onPageChange(i + 1)}
              className={cn(
                "shrink-0 rounded-md border-2 px-3 py-1.5 text-xs font-medium transition-colors",
                i + 1 === page
                  ? "border-brand text-foreground"
                  : "border-transparent bg-muted/50 text-muted-foreground hover:border-border",
              )}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
