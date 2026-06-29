// Editor for an extraction definition's `fields` list. Renders each field as a
// card (name, kind, coerce, core toggle, delete) with an indented sub-field
// section for composite/list_composite kinds. The owning dialog derives each
// field's `cls` (via pascalCase) at save time, so `cls` is never shown here.
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toggle } from "@/components/ui/toggle";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  FieldCoerce,
  FieldDef,
  FieldKind,
  SubFieldDef,
  SubFieldSource,
} from "@/lib/doc-type-schema";

// Mirrors backend `_pascal` (backend/app/extraction/definition.py ~line 111):
// PascalCase each underscore-separated segment (Python str.capitalize() upcases
// the first char AND lowercases the rest), then drop exactly ONE trailing "s".
// Smoke tests (verified byte-for-byte against the backend):
//   pascalCase("line_items")          === "LineItem"
//   pascalCase("termination_clause")  === "TerminationClause"
//   pascalCase("address")             === "Addres"     (single trailing s dropped)
//   pascalCase("total")               === "Total"
//   pascalCase("PARTIES")             === "Partie"      (rest lowercased, then -s)
//   pascalCase("")                    === ""
// Co-located with the field editor by design (the builder derives `cls` via this).
// eslint-disable-next-line react-refresh/only-export-components
export function pascalCase(name: string): string {
  const pascal = name
    .split("_")
    .map((part) =>
      part ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : "",
    )
    .join("");
  return pascal.endsWith("s") ? pascal.slice(0, -1) : pascal;
}

const FIELD_KINDS: { value: FieldKind; label: string }[] = [
  { value: "scalar", label: "Scalar" },
  { value: "presence", label: "Presence" },
  { value: "list_scalar", label: "List (scalar)" },
  { value: "composite", label: "Composite" },
  { value: "list_composite", label: "List (composite)" },
];

const COERCE_OPTIONS: { value: FieldCoerce; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
];

const SUBFIELD_SOURCES: { value: SubFieldSource; label: string }[] = [
  { value: "span", label: "Span" },
  { value: "attribute", label: "Attribute" },
];

const COMPOSITE_KINDS: FieldKind[] = ["composite", "list_composite"];

function blankField(): FieldDef {
  return {
    name: "",
    kind: "scalar",
    cls: "",
    coerce: "text",
    is_core: false,
    sub_fields: [],
  };
}

function blankSubField(): SubFieldDef {
  return { name: "", source: "span", coerce: "text" };
}

export function FieldListEditor({
  fields,
  onChange,
}: {
  fields: FieldDef[];
  onChange: (fields: FieldDef[]) => void;
}) {
  const updateField = (index: number, patch: Partial<FieldDef>) => {
    onChange(fields.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  };

  const removeField = (index: number) => {
    onChange(fields.filter((_, i) => i !== index));
  };

  const updateSubFields = (index: number, sub_fields: SubFieldDef[]) => {
    updateField(index, { sub_fields });
  };

  return (
    <div className="space-y-3">
      {fields.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No fields yet. Add one below.
        </p>
      )}

      {fields.map((field, i) => {
        const isComposite = COMPOSITE_KINDS.includes(field.kind);
        return (
          <div key={i} className="space-y-2 rounded-lg border p-3">
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-40 flex-1 space-y-1">
                <Label className="text-xs text-muted-foreground">Name</Label>
                <Input
                  value={field.name}
                  placeholder="field_name"
                  onChange={(e) => updateField(i, { name: e.target.value })}
                />
              </div>

              <div className="w-36 space-y-1">
                <Label className="text-xs text-muted-foreground">Kind</Label>
                <Select
                  value={field.kind}
                  onValueChange={(v) => updateField(i, { kind: v as FieldKind })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FIELD_KINDS.map((k) => (
                      <SelectItem key={k.value} value={k.value}>
                        {k.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {field.kind !== "presence" && (
                <div className="w-28 space-y-1">
                  <Label className="text-xs text-muted-foreground">
                    Coerce
                  </Label>
                  <Select
                    value={field.coerce}
                    onValueChange={(v) =>
                      updateField(i, { coerce: v as FieldCoerce })
                    }
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {COERCE_OPTIONS.map((c) => (
                        <SelectItem key={c.value} value={c.value}>
                          {c.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              <Toggle
                variant="outline"
                pressed={field.is_core}
                onPressedChange={(pressed) =>
                  updateField(i, { is_core: pressed })
                }
                aria-label="Core field"
              >
                Core
              </Toggle>

              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Delete field"
                onClick={() => removeField(i)}
              >
                <Trash2 />
              </Button>
            </div>

            {isComposite && (
              <div className="space-y-2 border-l pl-4">
                {field.sub_fields.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No sub-fields yet.
                  </p>
                )}
                {field.sub_fields.map((sub, j) => (
                  <div key={j} className="flex flex-wrap items-end gap-2">
                    <div className="min-w-32 flex-1 space-y-1">
                      <Label className="text-xs text-muted-foreground">
                        Sub-field
                      </Label>
                      <Input
                        value={sub.name}
                        placeholder="sub_name"
                        onChange={(e) =>
                          updateSubFields(
                            i,
                            field.sub_fields.map((s, k) =>
                              k === j ? { ...s, name: e.target.value } : s,
                            ),
                          )
                        }
                      />
                    </div>
                    <div className="w-32 space-y-1">
                      <Label className="text-xs text-muted-foreground">
                        Source
                      </Label>
                      <Select
                        value={sub.source}
                        onValueChange={(v) =>
                          updateSubFields(
                            i,
                            field.sub_fields.map((s, k) =>
                              k === j
                                ? { ...s, source: v as SubFieldSource }
                                : s,
                            ),
                          )
                        }
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {SUBFIELD_SOURCES.map((s) => (
                            <SelectItem key={s.value} value={s.value}>
                              {s.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="w-28 space-y-1">
                      <Label className="text-xs text-muted-foreground">
                        Coerce
                      </Label>
                      <Select
                        value={sub.coerce}
                        onValueChange={(v) =>
                          updateSubFields(
                            i,
                            field.sub_fields.map((s, k) =>
                              k === j ? { ...s, coerce: v as FieldCoerce } : s,
                            ),
                          )
                        }
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {COERCE_OPTIONS.map((c) => (
                            <SelectItem key={c.value} value={c.value}>
                              {c.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label="Delete sub-field"
                      onClick={() =>
                        updateSubFields(
                          i,
                          field.sub_fields.filter((_, k) => k !== j),
                        )
                      }
                    >
                      <Trash2 />
                    </Button>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    updateSubFields(i, [...field.sub_fields, blankSubField()])
                  }
                >
                  <Plus className="size-3.5" />
                  Add sub-field
                </Button>
              </div>
            )}
          </div>
        );
      })}

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onChange([...fields, blankField()])}
      >
        <Plus className="size-3.5" />
        Add field
      </Button>
    </div>
  );
}
