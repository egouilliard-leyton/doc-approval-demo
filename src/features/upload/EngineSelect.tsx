import { ScanText, Layers } from "lucide-react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Skeleton } from "@/components/ui/skeleton";
import type { EngineInfo, OcrEngine } from "@/lib/types";

const KIND_ICON = { layout: Layers, vlm: ScanText } as const;
const KIND_HINT = { layout: "Layout engine", vlm: "Vision model" } as const;

// Beyond this many engines the pill toggles get cramped (VLM labels are long),
// so we switch to a searchable dropdown that scales to any number of models.
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

  if (engines.length > PILL_LIMIT) {
    const options: ComboboxOption[] = engines.map((e) => ({
      value: e.key,
      label: e.label,
      hint: KIND_HINT[e.kind],
    }));
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
