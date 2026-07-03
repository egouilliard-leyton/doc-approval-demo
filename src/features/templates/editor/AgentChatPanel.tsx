// The "AI edit" tab beside the editor. A minimal chat surface that streams a
// turn of the authoring agent over SSE: assistant prose arrives as `token`
// deltas, tool calls surface as inline status rows, and `html`/`css` events push
// the agent's live edit back up to the editor (already persisted server-side as
// a revision). Lives in a ~18rem right rail, so it stays deliberately compact.
import { useEffect, useRef, useState } from "react";
import { Loader2, Send, Square } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ApiError, streamAgent } from "@/lib/api";
import type { AgentChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

/** An inline "editing… / done" status row for a single tool invocation. */
interface ToolActivity {
  id: number;
  toolName: string;
  status: "running" | "ok" | "failed";
  detail?: string;
}

export function AgentChatPanel({
  templateId,
  onHtml,
  onCss,
  onStreamingChange,
}: {
  templateId: string;
  onHtml: (html: string, revisionId?: string) => void;
  onCss: (css: string, revisionId?: string) => void;
  onStreamingChange: (streaming: boolean) => void;
}) {
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [toolActivity, setToolActivity] = useState<ToolActivity[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const toolIdRef = useRef(0);

  // Keep the transcript pinned to the latest content as tokens stream in.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, toolActivity]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleSend = async () => {
    const message = input.trim();
    if (!message || streaming) return;

    const history = messages;
    setInput("");
    setToolActivity([]);
    // Push the user turn plus an empty assistant turn to stream tokens into.
    setMessages((prev) => [
      ...prev,
      { role: "user", content: message },
      { role: "assistant", content: "" },
    ]);

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setStreaming(true);
    onStreamingChange(true);

    const appendAssistant = (text: string) =>
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, content: last.content + text };
        }
        return next;
      });

    try {
      for await (const ev of streamAgent(
        templateId,
        { message, history },
        ctrl.signal,
      )) {
        switch (ev.type) {
          case "token":
            if (ev.text) appendAssistant(ev.text);
            break;
          case "tool_call": {
            const id = ++toolIdRef.current;
            setToolActivity((prev) => [
              ...prev,
              {
                id,
                toolName: ev.tool_name ?? "tool",
                status: "running",
              },
            ]);
            break;
          }
          case "tool_result":
            // Mark the most recent running row for this tool as done/failed.
            setToolActivity((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].status === "running") {
                  next[i] = {
                    ...next[i],
                    status: ev.ok === false ? "failed" : "ok",
                    detail: ev.ok === false ? ev.detail : undefined,
                  };
                  break;
                }
              }
              return next;
            });
            break;
          case "html":
            if (ev.html != null) onHtml(ev.html, ev.revision_id);
            break;
          case "css":
            if (ev.css != null) onCss(ev.css, ev.revision_id);
            break;
          case "error":
            toast.error("Agent error", { description: ev.message });
            if (ev.message) appendAssistant(`\n\n⚠️ ${ev.message}`);
            break;
          case "done":
            break;
        }
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        // User stopped the stream — leave the partial transcript as-is.
      } else {
        const msg =
          e instanceof ApiError ? e.message : "The agent request failed.";
        toast.error("Agent error", { description: msg });
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
      onStreamingChange(false);
    }
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="space-y-1">
        <h2 className="text-sm font-medium">AI edit</h2>
        <p className="text-xs text-muted-foreground">
          Ask the agent to rewrite copy, restyle, or restructure — it edits the
          template live and saves a revision.
        </p>
      </div>

      <ScrollArea className="min-h-0 flex-1 rounded-xl border">
        <div
          ref={scrollRef}
          className="flex max-h-[28rem] flex-col gap-2 overflow-y-auto p-3"
        >
          {messages.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">
              Try “make the header bolder” or “add a footer with the total”.
            </p>
          ) : (
            messages.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "max-w-[85%] rounded-lg px-2.5 py-1.5 text-xs leading-relaxed whitespace-pre-wrap",
                  m.role === "user"
                    ? "self-end bg-primary text-primary-foreground"
                    : "self-start bg-muted text-foreground",
                )}
              >
                {m.content ||
                  (streaming && i === messages.length - 1 ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : null)}
              </div>
            ))
          )}

          {toolActivity.map((t) => (
            <div
              key={t.id}
              className={cn(
                "self-start font-mono text-[11px]",
                t.status === "failed" ? "text-flag" : "text-muted-foreground",
              )}
            >
              {t.status === "running"
                ? `✎ editing… ${t.toolName}`
                : t.status === "ok"
                  ? `✓ ${t.toolName}`
                  : `✗ ${t.toolName}${t.detail ? ` — ${t.detail}` : ""}`}
            </div>
          ))}
        </div>
      </ScrollArea>

      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void handleSend();
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask the agent to edit…"
          disabled={streaming}
        />
        {streaming ? (
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            aria-label="Stop"
            onClick={() => abortRef.current?.abort()}
          >
            <Square />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon-sm"
            aria-label="Send"
            disabled={!input.trim()}
          >
            <Send />
          </Button>
        )}
      </form>
    </div>
  );
}
