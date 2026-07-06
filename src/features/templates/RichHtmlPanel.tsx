// Orchestrates the rich-HTML authoring flow: an optional source upload (DOCX/PDF
// → editable HTML), the WYSIWYG editor + insert palette, a Save action, and the
// shared Generate panel below. The editor's HTML is what gets persisted and later
// bound by the backend.
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, updateTemplate } from "@/lib/api";
import type { FieldCatalogueEntry, TemplateDetail } from "@/lib/types";
import { GeneratePanel } from "@/features/templates/GeneratePanel";
import { SourceUploadPanel } from "@/features/templates/SourceUploadPanel";
import type { TemplateEditorApi } from "@/features/templates/editor/TemplateEditor";
import { TemplateEditor } from "@/features/templates/editor/TemplateEditor";
import { PlaceholderPalette } from "@/features/templates/editor/PlaceholderPalette";
import { AgentChatPanel } from "@/features/templates/editor/AgentChatPanel";
import { FidelityPanel } from "@/features/templates/editor/FidelityPanel";
import { HistoryPanel } from "@/features/templates/editor/HistoryPanel";

const BLANK = "<p></p>";

export function RichHtmlPanel({
  template,
  onChange,
}: {
  template: TemplateDetail;
  onChange: (t: TemplateDetail) => void;
}) {
  const [html, setHtml] = useState(template.html_body ?? BLANK);
  const [css, setCss] = useState(template.css ?? "");
  const [saving, setSaving] = useState(false);
  // True while the authoring agent is streaming an edit — locks the editor so
  // the user's keystrokes don't fight the agent's live changes.
  const [streaming, setStreaming] = useState(false);
  // Force the editor to remount only when a *new* persisted body arrives
  // (e.g. right after a source upload converts a DOCX into HTML).
  const [editorKey, setEditorKey] = useState(0);
  // The right-rail tabs are controlled so an upload can flip to "Fidelity" and a
  // fidelity handoff can flip to "AI edit".
  const [activeTab, setActiveTab] = useState("insert");
  // Bumped after a source upload to trigger a one-shot auto-validation.
  const [autoRunKey, setAutoRunKey] = useState(0);
  // A fidelity → agent handoff, passed into AgentChatPanel. The monotonic nonce
  // makes a repeated identical instruction still fire (dedup by event, not text).
  const [pendingAgentMessage, setPendingAgentMessage] =
    useState<{ text: string; nonce: number }>();
  const seededRef = useRef(template.html_body);
  const seededCssRef = useRef(template.css);
  const apiRef = useRef<TemplateEditorApi | null>(null);
  // Whether the editor holds edits not yet reflected in the last-seeded (i.e.
  // persisted) body/css. Derived in an effect rather than during render so we
  // can read the seed refs without tripping the react-hooks/refs lint rule.
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  useEffect(() => {
    setHasUnsavedChanges(
      html !== (seededRef.current ?? BLANK) ||
        css !== (seededCssRef.current ?? ""),
    );
  }, [html, css, template]);

  useEffect(() => {
    if (template.html_body !== seededRef.current) {
      seededRef.current = template.html_body;
      setHtml(template.html_body ?? BLANK);
      setEditorKey((k) => k + 1);
    }
    // Re-seed the stylesheet too — e.g. a source upload converts a DOCX and
    // persists a baseline CSS. Without this, the next Save would send the stale
    // empty css and wipe the backend-generated stylesheet.
    if (template.css !== seededCssRef.current) {
      seededCssRef.current = template.css;
      setCss(template.css ?? "");
    }
  }, [template.html_body, template.css]);

  const handleEditorReady = useCallback((api: TemplateEditorApi) => {
    apiRef.current = api;
  }, []);

  const handleInsertField = useCallback((entry: FieldCatalogueEntry) => {
    apiRef.current?.insertFieldToken({
      path: entry.path,
      label: entry.label,
      kind: entry.kind,
    });
  }, []);

  const handleInsertSignature = useCallback(() => {
    apiRef.current?.insertSignatureToken();
  }, []);

  // The agent already persisted its edit server-side (creating a revision), so
  // the incoming html/css is authoritative-and-saved. Keep the seeds in sync so
  // a later Save doesn't fight it, and bump editorKey to remount TipTap — it
  // only picks up new content on mount.
  const handleAgentHtml = useCallback((next: string) => {
    seededRef.current = next;
    setHtml(next);
    setEditorKey((k) => k + 1);
    toast.success("Applied agent edit");
  }, []);

  const handleAgentCss = useCallback((next: string) => {
    seededCssRef.current = next;
    setCss(next);
  }, []);

  // A source upload that yields a converted rich template (html_body present)
  // flips to the Fidelity tab and bumps the auto-run key so validation fires
  // immediately, surfacing the side-by-side + verdict.
  const handleUploaded = useCallback(
    (t: TemplateDetail) => {
      onChange(t);
      if (t.html_body) {
        setActiveTab("fidelity");
        setAutoRunKey((k) => k + 1);
      }
    },
    [onChange],
  );

  // Fidelity → agent handoff: stash the composed instruction and switch to the
  // "AI edit" tab, where AgentChatPanel auto-sends it.
  const handleSendToAgent = useCallback((message: string) => {
    setPendingAgentMessage((prev) => ({ text: message, nonce: (prev?.nonce ?? 0) + 1 }));
    setActiveTab("agent");
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await updateTemplate(template.id, {
        html_body: html,
        css,
      });
      // Keep the seeds in sync so persisting doesn't trigger a remount/re-seed.
      seededRef.current = updated.html_body;
      seededCssRef.current = updated.css;
      onChange(updated);
      toast.success("Template saved");
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Could not save the template.";
      toast.error("Save failed", { description: msg });
    } finally {
      setSaving(false);
    }
  };

  // Hide the "start from a document" card once there's a source, a persisted
  // body, OR the user has typed anything into the blank editor locally — so the
  // card dismisses on first keystroke without waiting for a Save.
  const showUpload =
    !template.source_file_id && html === BLANK && !template.html_body;

  return (
    <div className="space-y-6">
      {showUpload && (
        <Card>
          <CardHeader>
            <CardTitle>Start from a document</CardTitle>
            <CardDescription>
              Upload a DOCX or PDF to convert into an editable template — or just
              start typing in the editor below.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <SourceUploadPanel
              templateId={template.id}
              onUploaded={handleUploaded}
            />
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        <div className="sticky top-14 z-10 -mx-6 flex flex-wrap items-center justify-between gap-3 border-b bg-background/95 px-6 py-3 backdrop-blur">
          <div className="space-y-1">
            <h2 className="text-sm font-medium">Design your template</h2>
            <p className="text-xs text-muted-foreground">
              Write freely and drop in field placeholders — they're bound from an
              extracted document at generate time.
            </p>
          </div>
          <Button size="sm" disabled={saving} onClick={() => void handleSave()}>
            {saving ? <Loader2 className="animate-spin" /> : <Save />}
            Save template
          </Button>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
          <TemplateEditor
            key={editorKey}
            html={html}
            css={css}
            previewHtml={template.html_body ?? html}
            onChange={setHtml}
            editorRef={handleEditorReady}
            editable={!streaming}
          />
          <Tabs
            value={activeTab}
            onValueChange={setActiveTab}
            className="min-h-0"
          >
            <TabsList className="w-full">
              <TabsTrigger value="insert">Insert field</TabsTrigger>
              <TabsTrigger value="agent">AI edit</TabsTrigger>
              <TabsTrigger value="fidelity">Fidelity</TabsTrigger>
              <TabsTrigger value="history">History</TabsTrigger>
            </TabsList>
            <TabsContent value="insert" className="min-h-0">
              <PlaceholderPalette
                templateId={template.id}
                onInsertField={handleInsertField}
                onInsertSignature={handleInsertSignature}
              />
            </TabsContent>
            {/* forceMount keeps these panels mounted so a handoff (fidelity →
                agent) and the post-upload auto-validate fire on prop change
                rather than being swallowed by a fresh mount that re-inits their
                "already handled" refs. */}
            <TabsContent
              value="agent"
              forceMount
              className="min-h-0 data-[state=inactive]:hidden"
            >
              <AgentChatPanel
                templateId={template.id}
                onHtml={handleAgentHtml}
                onCss={handleAgentCss}
                onStreamingChange={setStreaming}
                pendingMessage={pendingAgentMessage}
              />
            </TabsContent>
            <TabsContent
              value="fidelity"
              forceMount
              className="min-h-0 data-[state=inactive]:hidden"
            >
              <FidelityPanel
                template={template}
                onSendToAgent={handleSendToAgent}
                autoRunKey={autoRunKey}
              />
            </TabsContent>
            {/* NOT forceMounted: natural remount-on-activate refetches the latest
                revisions each time the tab is opened. */}
            <TabsContent value="history" className="min-h-0">
              <HistoryPanel
                templateId={template.id}
                hasUnsavedChanges={hasUnsavedChanges}
                onRestored={onChange}
              />
            </TabsContent>
          </Tabs>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Generate</CardTitle>
          <CardDescription>
            Fill this template from a processed {template.doc_type} and download
            the result.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <GeneratePanel template={template} />
        </CardContent>
      </Card>
    </div>
  );
}
