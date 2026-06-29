import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Skeleton } from "@/components/ui/skeleton";
import { resolveDocTypeIcon } from "@/lib/icon-utils";
import type { DocTypeResponse } from "@/lib/doc-type-schema";

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
          <ToggleGroupItem key={dt.name} value={dt.name} aria-label={dt.label}>
            <Icon className="size-4" />
            {dt.label}
          </ToggleGroupItem>
        );
      })}
    </ToggleGroup>
  );
}
