// Live spec preview, with two right-panel modes. In "markdown" mode it renders the
// running spec markdown (GitHub-flavored) inside a scroll area, with an Annotate
// button in the header once there's a spec. While an annotate session is live the
// panel flips to "iframe" mode and embeds the Plannotator URL so the user can mark
// up the spec in place; a small status line sits beneath the header.
import { useMemo } from "react";
import { Highlighter, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

interface SpecPanelProps {
  specMarkdown: string;
  loading: boolean;
  rightPanelMode: "markdown" | "iframe";
  sessionUrl?: string | null;
  annotating?: boolean;
  hasAnnotated?: boolean;
  onAnnotate: () => void;
}

export function SpecPanel({
  specMarkdown,
  loading,
  rightPanelMode,
  sessionUrl,
  annotating,
  hasAnnotated,
  onAnnotate,
}: SpecPanelProps) {
  const rendered = useMemo(
    () =>
      specMarkdown.trim() ? (
        <div
          className={[
            "space-y-3 text-sm",
            "[&_h1]:text-lg [&_h1]:font-semibold",
            "[&_h2]:text-base [&_h2]:font-semibold [&_h2]:mt-4",
            "[&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-3",
            "[&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5",
            "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs",
            "[&_table]:w-full [&_table]:border-collapse [&_table]:text-xs",
            "[&_th]:border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-medium",
            "[&_td]:border [&_td]:px-2 [&_td]:py-1",
            "[&_a]:text-brand [&_a]:underline",
          ].join(" ")}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {specMarkdown}
          </ReactMarkdown>
        </div>
      ) : null,
    [specMarkdown],
  );

  const canAnnotate =
    rightPanelMode === "markdown" && !loading && specMarkdown.trim() !== "";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-4 py-2 text-sm font-medium">
        <span>Specification</span>
        {canAnnotate && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onAnnotate}
            disabled={annotating}
          >
            {annotating ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Highlighter className="size-3.5" />
            )}
            {hasAnnotated ? "Re-annotate" : "Annotate"}
          </Button>
        )}
      </div>

      {rightPanelMode === "iframe" && sessionUrl ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <p className="flex items-center gap-1.5 border-b bg-muted/30 px-4 py-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Waiting for your annotation…
          </p>
          <iframe
            src={sessionUrl}
            className="flex-1 w-full rounded-lg border-0"
            title="Annotate spec"
          />
        </div>
      ) : (
        <ScrollArea className="min-h-0 flex-1">
          <div className="p-4">
            {rendered ?? (
              <p className="text-sm text-muted-foreground">
                The spec will appear here as the conversation progresses.
              </p>
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
