// A searchable single-select dropdown (Popover + filtered list). Our standard
// replacement for a long native <Select>: every dropdown gets type-to-filter.
// Styled to match SelectTrigger so it drops in next to existing selects.
import * as React from "react";
import { Popover as PopoverPrimitive } from "radix-ui";
import { CheckIcon, ChevronDownIcon, SearchIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface ComboboxOption {
  value: string;
  label: string;
  /** Optional extra text (e.g. a slug) folded into the search + shown muted. */
  hint?: string;
}

export function Combobox({
  value,
  onChange,
  options,
  placeholder = "Select…",
  searchPlaceholder = "Search…",
  emptyText = "No matches.",
  disabled,
  className,
  contentClassName,
}: {
  value: string;
  onChange: (value: string) => void;
  options: ComboboxOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
  contentClassName?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");

  const selected = options.find((o) => o.value === value);
  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) =>
      `${o.label} ${o.hint ?? ""} ${o.value}`.toLowerCase().includes(q),
    );
  }, [options, query]);

  // Reset the query each time the popover opens so it always starts fresh.
  React.useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger
        disabled={disabled}
        className={cn(
          "flex h-8 w-full items-center justify-between gap-1.5 rounded-lg border border-input bg-transparent py-2 pr-2 pl-2.5 text-sm transition-colors outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30 dark:hover:bg-input/50",
          !selected && "text-muted-foreground",
          className,
        )}
      >
        <span className="line-clamp-1 text-left">
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDownIcon className="pointer-events-none size-4 shrink-0 text-muted-foreground" />
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="start"
          sideOffset={4}
          className={cn(
            "z-50 w-(--radix-popover-trigger-width) origin-(--radix-popover-content-transform-origin) overflow-hidden rounded-lg bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
            contentClassName,
          )}
        >
          <div className="flex items-center gap-2 border-b px-2.5">
            <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={searchPlaceholder}
              className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div className="max-h-64 overflow-y-auto p-1">
            {filtered.length === 0 ? (
              <div className="px-2 py-6 text-center text-sm text-muted-foreground">
                {emptyText}
              </div>
            ) : (
              filtered.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => {
                    onChange(o.value);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-accent hover:text-accent-foreground focus-visible:bg-accent",
                    o.value === value && "bg-accent/50",
                  )}
                >
                  <CheckIcon
                    className={cn(
                      "size-4 shrink-0",
                      o.value === value ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-1">{o.label}</span>
                    {o.hint && (
                      <span className="line-clamp-1 font-mono text-xs text-muted-foreground">
                        {o.hint}
                      </span>
                    )}
                  </span>
                </button>
              ))
            )}
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
