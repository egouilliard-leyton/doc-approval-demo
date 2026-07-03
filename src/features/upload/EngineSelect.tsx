import { ScanText, Layers, Cloud, Wand2 } from "lucide-react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Skeleton } from "@/components/ui/skeleton";
import type { EngineInfo, OcrEngine } from "@/lib/types";

// Picker-only sentinel for "let the backend route by doc type". Distinct from any
// real engine key; the pipeline translates it to "omit the engine param" on the OCR
// call, then keys everything off the engine the backend actually picked. It must
// never reach a stage-results key or a URL as a literal string.
export const AUTO_ENGINE = "__auto__";

const AUTO_HINT = "Route by document type; falls back automatically.";

const KIND_ICON = { layout: Layers, vlm: ScanText, external: Cloud } as const;
const KIND_HINT = {
  layout: "Layout engine",
  vlm: "Vision model",
  external: "External document-AI service",
} as const;

// Beyond this many options the pill toggles get cramped (VLM labels are long),
// so we switch to a searchable dropdown that scales to any number of models. The
// Auto option counts toward the limit, so it's included in this comparison.
const PILL_LIMIT = 2;

export function EngineSelect({
  engines,
  loading,
  value,
  onChange,
  disabled,
}: {
  engines: EngineInfo[];
  loading?: boolean;
  value: OcrEngine;
  onChange: (e: OcrEngine) => void;
  disabled?: boolean;
}) {
  if (loading && engines.length === 0) {
    return <Skeleton className="h-8 w-full" />;
  }

  // The Auto option always leads the list; picking it omits the engine param so
  // the backend routes by the document's preferred engine (+ fallback chain).
  if (engines.length + 1 > PILL_LIMIT) {
    const options: ComboboxOption[] = [
      { value: AUTO_ENGINE, label: "Auto", hint: AUTO_HINT },
      ...engines.map((e) => ({
        value: e.key,
        label: e.label,
        hint: KIND_HINT[e.kind],
      })),
    ];
    return (
      <Combobox
        value={value}
        onChange={onChange}
        options={options}
        placeholder="Select an OCR engine…"
        searchPlaceholder="Search engines…"
        emptyText="No engines match."
        disabled={disabled}
      />
    );
  }

  return (
    <ToggleGroup
      type="single"
      variant="outline"
      spacing={0}
      value={value}
      disabled={disabled}
      onValueChange={(v) => v && onChange(v as OcrEngine)}
      className="w-full *:flex-1"
    >
      <ToggleGroupItem
        value={AUTO_ENGINE}
        aria-label="Auto — use doc-type routing"
        title={AUTO_HINT}
      >
        <Wand2 className="size-4" />
        Auto
      </ToggleGroupItem>
      {engines.map(({ key, label, kind }) => {
        const Icon = KIND_ICON[kind];
        return (
          <ToggleGroupItem key={key} value={key} aria-label={label}>
            <Icon className="size-4" />
            {label}
          </ToggleGroupItem>
        );
      })}
    </ToggleGroup>
  );
}
