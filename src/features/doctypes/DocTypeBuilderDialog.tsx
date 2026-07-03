// Create/edit dialog for a configurable document type. Holds a structured,
// DocTypeCreate-shaped form in state and assembles the exact payload the backend
// expects on save: extraction_definition.name & rule_definition.name are forced
// to the type name, core_paths is rebuilt from is_core fields, each field's `cls`
// is derived via pascalCase, and citation_paths is mirrored onto rule_definition.
import { createElement, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Toggle } from "@/components/ui/toggle";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, createDocType, updateDocType } from "@/lib/api";
import { LUCIDE_ICON_OPTIONS } from "@/lib/icon-utils";
import type {
  DocTypeResponse,
  DocTypeUpdate,
  ExtractionDefinition,
  FieldDef,
  RuleDef,
  RuleDefinition,
} from "@/lib/doc-type-schema";
import { useEngines } from "@/features/upload/useEngines";
import { FieldListEditor } from "./FieldListEditor";
import { RuleListEditor } from "./RuleListEditor";
import { buildDocTypePayload } from "./payload";

// Sentinel Select value for "no preference"; Radix Select disallows an empty
// string item value, so we map this to a null preferred_ocr_engine.
const DEFAULT_ENGINE = "__default__";

// Structured editing shape. The backend stores extraction/rule definitions as
// opaque dicts (Record<string, unknown> on the wire), but the builder needs them
// typed, so we cast on the way in and serialize back to the DTO on save.
interface BuilderState {
  name: string;
  label: string;
  icon: string;
  extraction_definition: ExtractionDefinition;
  rule_definition: RuleDefinition;
  preferred_ocr_engine: string | null;
  ocr_fallback_engines: string[];
}

function blankState(): BuilderState {
  return {
    name: "",
    label: "",
    icon: "",
    extraction_definition: {
      name: "",
      fields: [],
      core_paths: [],
      prompt: "",
      examples: [],
    },
    rule_definition: { name: "", rules: [], citation_paths: [] },
    preferred_ocr_engine: null,
    ocr_fallback_engines: [],
  };
}

function stateFromResponse(t: DocTypeResponse): BuilderState {
  // Deep copy so edits never mutate the cached response object.
  const extraction = structuredClone(
    t.extraction_definition,
  ) as unknown as ExtractionDefinition;
  const rules = structuredClone(
    t.rule_definition,
  ) as unknown as RuleDefinition;
  return {
    name: t.name,
    label: t.label,
    icon: t.icon ?? "",
    extraction_definition: {
      name: extraction.name ?? t.name,
      fields: extraction.fields ?? [],
      core_paths: extraction.core_paths ?? [],
      prompt: extraction.prompt ?? "",
      examples: extraction.examples ?? [],
    },
    rule_definition: {
      name: rules.name ?? t.name,
      rules: rules.rules ?? [],
      citation_paths: rules.citation_paths ?? [],
    },
    // Existing types created before OCR routing simply lack these — default to
    // the system engine (null) and no fallbacks.
    preferred_ocr_engine: t.preferred_ocr_engine ?? null,
    ocr_fallback_engines: t.ocr_fallback_engines ?? [],
  };
}

// Citation is opt-OUT, defaulting to all fields. When editing an existing type,
// a field starts UNCHECKED (excluded) only when no stored citation path covers
// it — "covered" meaning a stored path equals the field name or is one of its
// dotted leaves (e.g. `parties.0` / `termination_clause.text` cover `parties` /
// `termination_clause`).
function excludedFromResponse(t: DocTypeResponse): string[] {
  const extraction = t.extraction_definition as unknown as ExtractionDefinition;
  const fields = extraction.fields ?? [];
  const stored = t.citation_paths ?? [];
  return fields
    .map((f) => f.name)
    .filter(
      (name) =>
        !stored.some((p) => p === name || p.startsWith(`${name}.`)),
    );
}

export function DocTypeBuilderDialog({
  open,
  onClose,
  editingType,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  editingType?: DocTypeResponse;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<BuilderState>(() =>
    editingType ? stateFromResponse(editingType) : blankState(),
  );
  // UI-only opt-out set: field names the user unchecked in "Cited fields". Never
  // sent to the API — the effective citation list is derived from it on save.
  const [citationExcluded, setCitationExcluded] = useState<string[]>(() =>
    editingType ? excludedFromResponse(editingType) : [],
  );
  const [saving, setSaving] = useState(false);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const { engines } = useEngines();

  // Toggle an engine in/out of the ordered fallback list (append keeps order).
  const toggleFallback = (key: string, on: boolean) =>
    setForm((f) => ({
      ...f,
      ocr_fallback_engines: on
        ? [...f.ocr_fallback_engines, key]
        : f.ocr_fallback_engines.filter((k) => k !== key),
    }));

  const setExtraction = (patch: Partial<ExtractionDefinition>) =>
    setForm((f) => ({
      ...f,
      extraction_definition: { ...f.extraction_definition, ...patch },
    }));

  const setFields = (fields: FieldDef[]) => setExtraction({ fields });
  const setRules = (rules: RuleDef[]) =>
    setForm((f) => ({
      ...f,
      rule_definition: { ...f.rule_definition, rules },
    }));

  // Toggling a box flips a field between cited (checked) and excluded.
  const toggleCited = (name: string, cited: boolean) =>
    setCitationExcluded((ex) =>
      cited ? ex.filter((n) => n !== name) : [...ex, name],
    );

  async function handleSave() {
    setFormErrors([]);
    setSaving(true);
    try {
      // Assemble the canonical payload (derives `cls`, core_paths, mirrors
      // citation_paths and forces the definition names) in one pure step.
      const built = buildDocTypePayload(form, citationExcluded);

      if (editingType) {
        const payload: DocTypeUpdate = {
          label: built.label,
          icon: built.icon,
          extraction_definition: built.extraction_definition,
          rule_definition: built.rule_definition,
          citation_paths: built.citation_paths,
          preferred_ocr_engine: built.preferred_ocr_engine,
          ocr_fallback_engines: built.ocr_fallback_engines,
        };
        await updateDocType(editingType.name, payload);
      } else {
        await createDocType(built);
      }

      toast.success("Doc type saved");
      onSaved();
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setFormErrors(e.message.split("; ").filter(Boolean));
      } else if (e instanceof ApiError && e.status === 403) {
        toast.error("Built-in types are read-only");
      } else {
        toast.error("Save failed", {
          description: e instanceof ApiError ? e.message : String(e),
        });
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {editingType ? `Edit ${editingType.label}` : "Create document type"}
          </DialogTitle>
          <DialogDescription>
            Define how this document type is extracted and validated.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="info">
          <TabsList>
            <TabsTrigger value="info">Info</TabsTrigger>
            <TabsTrigger value="fields">Fields</TabsTrigger>
            <TabsTrigger value="rules">Rules</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
          </TabsList>

          <TabsContent value="info" className="space-y-4 pt-2">
            <div className="space-y-1">
              <Label>Name</Label>
              <Input
                value={form.name}
                disabled={!!editingType}
                placeholder="purchase_order"
                onChange={(e) =>
                  setForm((f) => ({ ...f, name: e.target.value }))
                }
              />
              <p className="text-xs text-muted-foreground">
                Lowercase identifier. Cannot be changed after creation.
              </p>
            </div>
            <div className="space-y-1">
              <Label>Label</Label>
              <Input
                value={form.label}
                placeholder="Purchase Order"
                onChange={(e) =>
                  setForm((f) => ({ ...f, label: e.target.value }))
                }
              />
            </div>
            <div className="space-y-1">
              <Label>Icon</Label>
              <Select
                value={form.icon || undefined}
                onValueChange={(v) => setForm((f) => ({ ...f, icon: v }))}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Choose an icon" />
                </SelectTrigger>
                <SelectContent>
                  {LUCIDE_ICON_OPTIONS.map(({ name, Icon }) => (
                    <SelectItem key={name} value={name}>
                      <span className="flex items-center gap-2">
                        {createElement(Icon, { className: "size-4" })}
                        {name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </TabsContent>

          <TabsContent value="fields" className="pt-2">
            <FieldListEditor
              fields={form.extraction_definition.fields}
              onChange={setFields}
            />
          </TabsContent>

          <TabsContent value="rules" className="pt-2">
            <RuleListEditor
              fields={form.extraction_definition.fields}
              rules={form.rule_definition.rules}
              onChange={setRules}
            />
          </TabsContent>

          <TabsContent value="advanced" className="space-y-4 pt-2">
            <div className="space-y-2">
              <Label>Cited fields</Label>
              {form.extraction_definition.fields.length === 0 ? (
                <p className="text-xs text-muted-foreground">Add fields first.</p>
              ) : (
                <>
                  <div className="flex flex-wrap gap-2">
                    {form.extraction_definition.fields.map((field, i) => (
                      <Toggle
                        key={i}
                        variant="outline"
                        pressed={!citationExcluded.includes(field.name)}
                        onPressedChange={(pressed) =>
                          toggleCited(field.name, pressed)
                        }
                        aria-label={`Cite ${field.name || "field"}`}
                      >
                        {field.name || "(unnamed)"}
                      </Toggle>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    All fields are cited by default. Uncheck a field to exclude
                    it.
                  </p>
                </>
              )}
            </div>

            <div className="space-y-1">
              <Label>Extraction prompt (optional)</Label>
              <Textarea
                value={form.extraction_definition.prompt}
                placeholder="Optional guidance for the extraction model…"
                onChange={(e) => setExtraction({ prompt: e.target.value })}
              />
            </div>

            <div className="space-y-1">
              <Label>Preferred OCR engine</Label>
              <Select
                value={form.preferred_ocr_engine ?? DEFAULT_ENGINE}
                onValueChange={(v) =>
                  setForm((f) => ({
                    ...f,
                    preferred_ocr_engine: v === DEFAULT_ENGINE ? null : v,
                  }))
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="— (default) —" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT_ENGINE}>— (default) —</SelectItem>
                  {engines.map((e) => (
                    <SelectItem key={e.key} value={e.key}>
                      {e.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                OCR engine to try first for this type. Default uses the system
                engine chosen at upload.
              </p>
            </div>

            <div className="space-y-2">
              <Label>Fallback engines</Label>
              {engines.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No engines available.
                </p>
              ) : (
                <>
                  <div className="flex flex-wrap gap-2">
                    {engines.map((e) => (
                      <Toggle
                        key={e.key}
                        variant="outline"
                        pressed={form.ocr_fallback_engines.includes(e.key)}
                        onPressedChange={(pressed) =>
                          toggleFallback(e.key, pressed)
                        }
                        aria-label={`Fallback to ${e.label}`}
                      >
                        {e.label}
                      </Toggle>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Tried in order if the preferred engine fails. None selected
                    means no fallback.
                  </p>
                </>
              )}
            </div>
          </TabsContent>
        </Tabs>

        {formErrors.length > 0 && (
          <ul className="list-disc space-y-1 rounded-lg border border-destructive/40 bg-destructive/5 px-5 py-2 text-sm text-destructive">
            {formErrors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
