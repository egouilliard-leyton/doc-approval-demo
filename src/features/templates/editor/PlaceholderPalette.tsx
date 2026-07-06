// The insert palette that sits beside the editor. Lists every extractable field
// from the template's catalogue; clicking one inserts a bound placeholder at the
// cursor. A dedicated button inserts a signature-image target.
import { useEffect, useMemo, useState } from "react";
import { PenLine, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ApiError, getTemplateCatalogue } from "@/lib/api";
import type { FieldCatalogueEntry } from "@/lib/types";

export function PlaceholderPalette({
  templateId,
  onInsertField,
  onInsertSignature,
}: {
  templateId: string;
  onInsertField: (entry: FieldCatalogueEntry) => void;
  onInsertSignature: () => void;
}) {
  const [catalogue, setCatalogue] = useState<FieldCatalogueEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await getTemplateCatalogue(templateId);
        if (!cancelled) setCatalogue(data);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "Could not load fields.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return catalogue;
    return catalogue.filter(
      (c) =>
        c.label.toLowerCase().includes(q) || c.path.toLowerCase().includes(q),
    );
  }, [catalogue, query]);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="space-y-1">
        <h2 className="text-sm font-medium">Insert field</h2>
        <p className="text-xs text-muted-foreground">
          Click a field to drop a placeholder at the cursor. It's bound at
          generation time.
        </p>
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="justify-start"
        onClick={onInsertSignature}
      >
        <PenLine className="text-brand" />
        Signature image
      </Button>

      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search fields…"
          className="pl-8"
        />
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-12 rounded-lg bg-muted/50 animate-pulse" />
          ))}
        </div>
      ) : error ? (
        <p className="text-xs text-flag">{error}</p>
      ) : filtered.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          {catalogue.length === 0
            ? "No extractable fields for this document type."
            : "No fields match your search."}
        </p>
      ) : (
        <ScrollArea className="min-h-0 flex-1 rounded-xl border">
          <ul className="divide-y">
            {filtered.map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  onClick={() => onInsertField(entry)}
                  className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left transition-colors hover:bg-muted/60"
                >
                  <div className="flex w-full items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">
                      {entry.label}
                    </span>
                    <Badge
                      variant="outline"
                      className="shrink-0 font-mono text-[10px] capitalize"
                    >
                      {entry.kind}
                    </Badge>
                  </div>
                  <span
                    className="truncate font-mono text-[11px] text-muted-foreground"
                    title={entry.path}
                  >
                    {entry.path}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </ScrollArea>
      )}
    </div>
  );
}
