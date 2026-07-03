// Maps each fillable PDF form field to an extracted document field. Seeds a
// local, editable copy of `form_field_map`; "AI suggest" fills it from the LLM
// and "Save mapping" persists it back through updateTemplate.
import { useEffect, useMemo, useState } from "react";
import { Loader2, PenLine, Save, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ApiError,
  getTemplateCatalogue,
  suggestTemplateMapping,
  updateTemplate,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  FieldCatalogueEntry,
  FormFieldMapEntry,
  TemplateDetail,
  TemplateFormField,
} from "@/lib/types";

// Radix Select forbids an empty item value, so "no mapping" gets a sentinel.
const NONE = "__none__";

// Seed a full, editable map: every field has an entry, signature fields are
// marked so they persist correctly even if the user never touches them.
function seedMap(template: TemplateDetail): Record<string, FormFieldMapEntry> {
  const out: Record<string, FormFieldMapEntry> = {};
  for (const field of template.form_fields) {
    const existing = template.form_field_map[field.name];
    if (field.kind === "signature") {
      out[field.name] = { field_path: null, is_signature: true };
    } else if (existing) {
      out[field.name] = {
        field_path: existing.field_path ?? null,
        is_signature: false,
        source: existing.source,
        confidence: existing.confidence,
      };
    } else {
      out[field.name] = { field_path: null, is_signature: false };
    }
  }
  return out;
}

function KindBadge({ kind }: { kind: TemplateFormField["kind"] }) {
  return (
    <Badge variant="outline" className="font-mono text-[10px] capitalize">
      {kind}
    </Badge>
  );
}

export function FormFieldMappingTable({
  template,
  onChange,
}: {
  template: TemplateDetail;
  onChange: (t: TemplateDetail) => void;
}) {
  const [catalogue, setCatalogue] = useState<FieldCatalogueEntry[]>([]);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  // Local editable copy — seeded once from the template's persisted map.
  const [map, setMap] = useState<Record<string, FormFieldMapEntry>>(() =>
    seedMap(template),
  );
  const [suggesting, setSuggesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getTemplateCatalogue(template.id);
        if (!cancelled) setCatalogue(data);
      } catch (e) {
        if (!cancelled)
          setCatalogueError(
            e instanceof ApiError ? e.message : "Could not load fields.",
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [template.id]);

  const labelForPath = useMemo(() => {
    const byPath = new Map(catalogue.map((c) => [c.path, c.label]));
    return (path: string | null): string =>
      path ? (byPath.get(path) ?? path) : "— none —";
  }, [catalogue]);

  const setFieldPath = (name: string, value: string) => {
    setMap((prev) => ({
      ...prev,
      [name]: {
        field_path: value === NONE ? null : value,
        is_signature: false,
      },
    }));
  };

  const handleSuggest = async () => {
    setSuggesting(true);
    try {
      const res = await suggestTemplateMapping(template.id);
      setMap((prev) => {
        const next = { ...prev };
        for (const [name, s] of Object.entries(res.suggestions)) {
          // Never overwrite a signature slot with a plain field mapping.
          if (next[name]?.is_signature) continue;
          next[name] = {
            field_path: s.field_path,
            is_signature: s.is_signature,
            source: s.source,
            confidence: s.confidence,
          };
        }
        return next;
      });
      toast.success("Mapping suggested", {
        description: `via ${res.provider_used}`,
      });
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Could not suggest a mapping.";
      toast.error("Suggestion failed", { description: msg });
    } finally {
      setSuggesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await updateTemplate(template.id, {
        form_field_map: map,
      });
      onChange(updated);
      toast.success("Mapping saved");
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Could not save the mapping.";
      toast.error("Save failed", { description: msg });
    } finally {
      setSaving(false);
    }
  };

  const busy = suggesting || saving;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-sm font-medium">Field mapping</h2>
          <p className="text-xs text-muted-foreground">
            Map each PDF field to an extracted field, or let AI propose a start.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void handleSuggest()}
          >
            {suggesting ? (
              <Loader2 className="animate-spin" />
            ) : (
              <Sparkles className="text-brand" />
            )}
            AI suggest
          </Button>
          <Button size="sm" disabled={busy} onClick={() => void handleSave()}>
            {saving ? <Loader2 className="animate-spin" /> : <Save />}
            Save mapping
          </Button>
        </div>
      </div>

      {catalogueError && (
        <p className="text-xs text-flag">{catalogueError}</p>
      )}

      <div className="rounded-xl border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>PDF field</TableHead>
              <TableHead>Mapped to</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {template.form_fields.map((field) => {
              const entry = map[field.name];
              const isSignature = field.kind === "signature";
              return (
                <TableRow key={field.name} className="align-top">
                  <TableCell className="whitespace-normal">
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <span
                          className="font-mono text-sm font-medium"
                          title={field.name}
                        >
                          {field.name}
                        </span>
                        <KindBadge kind={field.kind} />
                      </div>
                      {field.nearby_label && (
                        <span className="text-xs text-muted-foreground">
                          {field.nearby_label}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    {isSignature ? (
                      <Badge
                        variant="outline"
                        className="border-brand/40 text-brand"
                      >
                        <PenLine className="size-3" />
                        Signature (stamped at generate)
                      </Badge>
                    ) : (
                      <Select
                        value={entry?.field_path ?? NONE}
                        onValueChange={(v) => setFieldPath(field.name, v)}
                      >
                        <SelectTrigger
                          size="sm"
                          className={cn(
                            "w-full max-w-xs",
                            !entry?.field_path && "text-muted-foreground",
                          )}
                        >
                          <SelectValue>
                            {labelForPath(entry?.field_path ?? null)}
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NONE}>— none —</SelectItem>
                          {catalogue.map((c) => (
                            <SelectItem key={c.path} value={c.path}>
                              {c.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
