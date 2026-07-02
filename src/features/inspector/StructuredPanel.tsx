import { useState } from "react";
import { CornerDownRight, Pencil, GitCompare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { formatPct, formatMoney, isMoneyField } from "@/lib/format";
import {
  buildFieldTree,
  displayValue,
  flattenLeaves,
  isFieldValue,
  type FieldLeaf,
} from "@/lib/fields";
import type { FieldValue, StructuredResult } from "@/lib/types";
import { fileUrl } from "@/lib/api";

export function ConfidencePill({ value }: { value: number }) {
  return (
    <span
      className={cn(
        "rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium",
        value >= 0.8
          ? "bg-approve/10 text-approve"
          : value >= 0.5
            ? "bg-review-muted text-review-foreground"
            : "bg-flag/10 text-flag",
      )}
    >
      {formatPct(value)}
    </span>
  );
}

/** Green = value as the model extracted it; amber = corrected by a reviewer. */
function StatusDot({ edited }: { edited?: boolean }) {
  return (
    <span
      className={cn(
        "size-2 shrink-0 rounded-full",
        edited ? "bg-review" : "bg-approve",
      )}
      title={edited ? "edited by reviewer" : "as extracted"}
    />
  );
}

function ColorSwatch({ color }: { color?: string }) {
  return (
    <span
      className="size-2.5 shrink-0 rounded-[3px]"
      style={{ backgroundColor: color ?? "var(--color-muted-foreground)" }}
      title={color ? "source highlighted on the page" : "no source location"}
    />
  );
}

/** Format a field's value, applying currency to money-like numeric fields. */
function formatFieldValue(
  fv: FieldValue,
  label: string,
  currency: string | null,
): string {
  if (typeof fv.value === "number" && currency && isMoneyField(label)) {
    return formatMoney(fv.value, currency);
  }
  return displayValue(fv.value);
}

/**
 * A value that can be corrected in place. Shows the (optionally currency-formatted)
 * value with a pencil on hover; editing swaps in a raw-text input. Enter/blur saves,
 * Esc cancels. An edited value is badged and keeps its original in the tooltip.
 */
function EditableValue({
  fv,
  path,
  label,
  currency,
  onEdit,
  compact,
}: {
  fv: FieldValue;
  path: string;
  label: string;
  currency: string | null;
  onEdit: (path: string, value: string | null) => void;
  compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const start = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDraft(fv.value == null ? "" : String(fv.value));
    setEditing(true);
  };
  const commit = () => {
    setEditing(false);
    const raw = draft.trim();
    const prev = fv.value == null ? "" : String(fv.value);
    if (raw !== prev) onEdit(path, raw === "" ? null : raw);
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") setEditing(false);
        }}
        className="w-full max-w-full rounded-md border border-ring bg-background px-2 py-1 font-mono text-sm outline-none ring-3 ring-ring/40"
      />
    );
  }

  return (
    <div className="group/val flex items-start gap-1.5">
      <span
        className={cn(
          "min-w-0 font-mono break-words",
          compact ? "text-xs" : "text-sm",
          fv.value === null
            ? "text-muted-foreground/60 italic"
            : "text-foreground",
        )}
      >
        {formatFieldValue(fv, label, currency)}
      </span>
      {fv.edited && (
        <span
          className="mt-0.5 shrink-0 rounded-full bg-review-muted px-1.5 py-0.5 text-[10px] font-medium text-review-foreground"
          title={`Edited — original: ${displayValue(fv.original_value ?? null)}`}
        >
          edited
        </span>
      )}
      <button
        type="button"
        onClick={start}
        title="Edit value"
        className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity group-hover/val:opacity-100 hover:bg-muted hover:text-foreground"
      >
        <Pencil className="size-3" />
      </button>
    </div>
  );
}

/** Small mono badge with a spreadsheet source cell, e.g. `Invoice!B2`. */
function CellRefBadge({ cellRef }: { cellRef: string }) {
  return (
    <span
      className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] font-medium text-muted-foreground"
      title="source cell"
    >
      {cellRef}
    </span>
  );
}

function Leaf({
  leaf,
  color,
  selected,
  currency,
  cellRef,
  onSelect,
  onHover,
  onEdit,
  indent,
}: {
  leaf: FieldLeaf;
  color?: string;
  selected: boolean;
  currency: string | null;
  cellRef?: string;
  onSelect: (path: string) => void;
  onHover: (path: string | null) => void;
  onEdit: (path: string, value: string | null) => void;
  indent?: boolean;
}) {
  const locatable = Boolean(color);
  return (
    <div
      onMouseEnter={() => locatable && onHover(leaf.path)}
      onMouseLeave={() => onHover(null)}
      onClick={() => locatable && onSelect(leaf.path)}
      style={selected ? { boxShadow: `inset 3px 0 0 0 ${color}` } : undefined}
      className={cn(
        "space-y-0.5 rounded-lg px-3 py-2 transition-colors",
        locatable ? "cursor-pointer hover:bg-muted/60" : "hover:bg-muted/40",
        selected && "bg-muted/70",
        indent && "ml-4",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {indent && (
            <CornerDownRight className="size-3 shrink-0 text-muted-foreground/50" />
          )}
          <ColorSwatch color={color} />
          <span className="truncate text-xs font-medium tracking-wide text-muted-foreground">
            {leaf.label}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {cellRef && <CellRefBadge cellRef={cellRef} />}
          <StatusDot edited={leaf.fv.edited} />
          {leaf.fv.value !== null && (
            <ConfidencePill value={leaf.fv.confidence} />
          )}
        </div>
      </div>
      <div className="pl-[18px]">
        <EditableValue
          fv={leaf.fv}
          path={leaf.path}
          label={leaf.label}
          currency={currency}
          onEdit={onEdit}
        />
        {leaf.fv.grounding?.image_url && (
          <img
            src={fileUrl(leaf.fv.grounding.image_url)}
            alt={`${leaf.label} crop`}
            className="mt-1.5 max-h-16 rounded border border-border bg-white object-contain"
          />
        )}
      </div>
    </div>
  );
}

export function StructuredPanel({
  structure,
  colorByPath,
  cellRefByPath,
  spreadsheet = false,
  selectedPath,
  onSelectField,
  onHoverField,
  onEditField,
  onReviewEdits,
}: {
  structure: StructuredResult;
  colorByPath: Record<string, string>;
  /** Field path -> A1 source cell (spreadsheets), shown as a badge on each field. */
  cellRefByPath?: Record<string, string>;
  /** Source is a spreadsheet grid rather than a page image (tweaks wording). */
  spreadsheet?: boolean;
  selectedPath: string | null;
  onSelectField: (path: string) => void;
  onHoverField: (path: string | null) => void;
  onEditField: (path: string, value: string | null) => void;
  onReviewEdits: () => void;
}) {
  const refs = cellRefByPath ?? {};
  const tree = buildFieldTree(structure.fields);
  const editedCount = flattenLeaves(tree).filter((l) => l.fv.edited).length;

  // Currency for money formatting — only when the doc actually extracted one.
  const currencyFv = structure.fields["currency"];
  const currency =
    isFieldValue(currencyFv) && typeof currencyFv.value === "string"
      ? currencyFv.value
      : null;

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary" className="font-mono">
          {structure.provider} · {structure.model}
        </Badge>
        <Badge
          variant="outline"
          className={cn(
            "font-mono",
            structure.extraction_confidence >= 0.6
              ? "text-approve"
              : "text-review",
          )}
        >
          extraction {formatPct(structure.extraction_confidence)}
        </Badge>
        {structure.fallback_used && (
          <Badge variant="outline">table fallback</Badge>
        )}
        {editedCount > 0 && (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto h-7 gap-1.5"
            onClick={onReviewEdits}
          >
            <GitCompare className="size-3.5" />
            Review edits ({editedCount})
          </Button>
        )}
      </div>

      {structure.provider === "mock" && (
        <div className="rounded-lg border border-review/40 bg-review-muted/30 p-2.5 text-xs text-review-foreground">
          Demo (mock) extraction — these are placeholder fields, not read from
          this document. Set an OpenRouter key and use the LangExtract provider
          for real extraction.
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        {spreadsheet
          ? "Each colored field is highlighted in the same color on the grid, with its source cell shown as a badge. Click a field to jump to its cell; hover and click the pencil to correct a value."
          : "Each colored field is boxed in the same color on the page. Click a field to jump to its source; hover and click the pencil to correct a value."}
      </p>

      <ScrollArea className="flex-1 rounded-xl border">
        <div className="divide-y">
          {tree.map((node) => {
            if (node.kind === "leaf") {
              return (
                <Leaf
                  key={node.path}
                  leaf={node}
                  color={colorByPath[node.path]}
                  selected={selectedPath === node.path}
                  currency={currency}
                  cellRef={refs[node.path]}
                  onSelect={onSelectField}
                  onHover={onHoverField}
                  onEdit={onEditField}
                />
              );
            }
            if (node.kind === "object") {
              return (
                <div key={node.path} className="py-1">
                  <div className="px-3 pt-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                    {node.label}
                  </div>
                  {node.children.map((c) => (
                    <Leaf
                      key={c.path}
                      leaf={c}
                      color={colorByPath[c.path]}
                      selected={selectedPath === c.path}
                      currency={currency}
                      cellRef={refs[c.path]}
                      onSelect={onSelectField}
                      onHover={onHoverField}
                      onEdit={onEditField}
                      indent
                    />
                  ))}
                </div>
              );
            }
            // list
            if (node.rows.length === 0) {
              return (
                <div key={node.path} className="space-y-2 px-3 py-3">
                  <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                    {node.label}
                  </div>
                  <p className="text-sm text-muted-foreground/60 italic">—</p>
                </div>
              );
            }
            if (node.variant === "scalars") {
              return (
                <div key={node.path} className="space-y-2 px-3 py-3">
                  <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                    {node.label}
                  </div>
                  <div className="space-y-0.5">
                    {node.rows.map((row) =>
                      row.map((leaf) => (
                        <Leaf
                          key={leaf.path}
                          leaf={leaf}
                          color={colorByPath[leaf.path]}
                          selected={selectedPath === leaf.path}
                          currency={currency}
                          cellRef={refs[leaf.path]}
                          onSelect={onSelectField}
                          onHover={onHoverField}
                          onEdit={onEditField}
                        />
                      )),
                    )}
                  </div>
                </div>
              );
            }
            // objects list -> a real table, color-accented + editable cells.
            return (
              <div key={node.path} className="space-y-2 px-3 py-3">
                <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  {node.label}
                </div>
                <div className="overflow-x-auto rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-1 p-0" />
                        {node.columns.map((c) => (
                          <TableHead
                            key={c}
                            className={cn(
                              "text-xs whitespace-nowrap",
                              c !== "desc" && "text-right",
                            )}
                          >
                            {c}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {node.rows.map((row, ri) => {
                        const rowPath = row.find(
                          (l) => colorByPath[l.path],
                        )?.path;
                        const color = rowPath ? colorByPath[rowPath] : undefined;
                        const selected = row.some(
                          (l) => l.path === selectedPath,
                        );
                        return (
                          <TableRow
                            key={ri}
                            title={rowPath ? refs[rowPath] : undefined}
                            onMouseEnter={() => rowPath && onHoverField(rowPath)}
                            onMouseLeave={() => onHoverField(null)}
                            onClick={() => rowPath && onSelectField(rowPath)}
                            className={cn(
                              rowPath && "cursor-pointer",
                              selected && "bg-muted/70",
                            )}
                          >
                            <TableCell
                              className="p-0"
                              style={{ backgroundColor: color }}
                            />
                            {row.map((leaf, ci) => (
                              <TableCell
                                key={leaf.path}
                                className={cn(
                                  node.columns[ci] === "desc"
                                    ? "min-w-40 max-w-64"
                                    : "text-right",
                                )}
                              >
                                <EditableValue
                                  fv={leaf.fv}
                                  path={leaf.path}
                                  label={node.columns[ci]}
                                  currency={currency}
                                  onEdit={onEditField}
                                  compact
                                />
                              </TableCell>
                            ))}
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
