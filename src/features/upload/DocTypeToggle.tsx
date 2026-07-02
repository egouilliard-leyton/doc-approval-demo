import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";
import { Skeleton } from "@/components/ui/skeleton";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import type { DocTypeResponse } from "@/lib/doc-type-schema";

// Beyond this many types the pill toggles get cramped, so we switch to a
// searchable dropdown that scales to any number of custom doc types. Matches
// EngineSelect's threshold so both pickers behave identically.
const PILL_LIMIT = 2;

export function DocTypeToggle({
  value,
  onChange,
  docTypes,
  loading,
  disabled,
}: {
  value: string;
  onChange: (t: string) => void;
  docTypes: DocTypeResponse[];
  loading: boolean;
  disabled?: boolean;
}) {
  if (loading) {
    return <Skeleton className="h-9 w-full rounded-lg" />;
  }

  if (docTypes.length > PILL_LIMIT) {
    const options: ComboboxOption[] = docTypes.map((dt) => ({
      value: dt.name,
      label: dt.label || dt.name,
    }));
    return (
      <Combobox
        value={value}
        onChange={onChange}
        options={options}
        placeholder="Select a document type…"
        searchPlaceholder="Search types…"
        emptyText="No types match."
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
      onValueChange={(v) => v && onChange(v)}
      className="w-full *:flex-1"
    >
      {docTypes.map((dt) => {
        const Icon = resolveDocTypeIcon(dt.name, dt.icon);
        return (
          <ToggleGroupItem
            key={dt.name}
            value={dt.name}
            aria-label={dt.label || dt.name}
          >
            <Icon className="size-4" />
            {dt.label || dt.name}
          </ToggleGroupItem>
        );
      })}
    </ToggleGroup>
  );
}
