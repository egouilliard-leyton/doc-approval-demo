// The rich-HTML WYSIWYG editor. Wraps TipTap with a shadcn-styled toolbar and
// the two custom placeholder nodes (field / signature). `editor.getHTML()` is
// the exact markup persisted and later bound by the backend, so the storage and
// the DOM are identical.
import { useEffect, useState } from "react";
import {
  Bold,
  Eye,
  Heading1,
  Heading2,
  Italic,
  List,
  ListOrdered,
  PenLine,
  Redo2,
  Undo2,
} from "lucide-react";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { cn } from "@/lib/utils";
import type { FieldTokenAttributes } from "@/features/templates/editor/fieldTokenExtension";
import { FieldToken } from "@/features/templates/editor/fieldTokenExtension";
import { SignatureToken } from "@/features/templates/editor/signatureTokenExtension";

/** Imperative surface the palette uses to insert placeholders at the cursor. */
export interface TemplateEditorApi {
  insertFieldToken: (attrs: FieldTokenAttributes) => void;
  insertSignatureToken: () => void;
}

export function TemplateEditor({
  html,
  css,
  previewHtml,
  onChange,
  editorRef,
  editable = true,
}: {
  html: string;
  css?: string;
  // The exact HTML the generator will use (the persisted body). Preview renders
  // THIS + css, not editor.getHTML() — TipTap's schema flattens complex markup
  // (divs/classes/tables), so its serialization can't be trusted for the look.
  previewHtml?: string;
  onChange: (html: string) => void;
  editorRef?: (api: TemplateEditorApi) => void;
  editable?: boolean;
}) {
  // "edit" shows the structural WYSIWYG with placeholder chips; "preview" renders
  // the exact html + template CSS in an isolated iframe, so it looks like the
  // generated document (placeholders show their labels, styled in place).
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  const editor = useEditor({
    extensions: [StarterKit, FieldToken, SignatureToken],
    content: html,
    editable,
    // Client-only SPA, but this avoids a first-paint hydration warning.
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class:
          "tiptap min-h-[24rem] px-4 py-3 focus:outline-none text-sm leading-relaxed",
      },
    },
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
  });

  // Toggle editability without a remount (e.g. lock the editor while the agent
  // is streaming an edit into it).
  useEffect(() => {
    if (editor) editor.setEditable(editable);
  }, [editor, editable]);

  // Expose the imperative insert commands to the parent once the editor exists.
  useEffect(() => {
    if (!editor || !editorRef) return;
    editorRef({
      insertFieldToken: (attrs) =>
        editor.chain().focus().insertFieldToken(attrs).run(),
      insertSignatureToken: () =>
        editor.chain().focus().insertSignatureToken().run(),
    });
  }, [editor, editorRef]);

  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e?.isActive("bold") ?? false,
      italic: e?.isActive("italic") ?? false,
      h1: e?.isActive("heading", { level: 1 }) ?? false,
      h2: e?.isActive("heading", { level: 2 }) ?? false,
      bullet: e?.isActive("bulletList") ?? false,
      ordered: e?.isActive("orderedList") ?? false,
      canUndo: e?.can().undo() ?? false,
      canRedo: e?.can().redo() ?? false,
    }),
  });

  if (!editor) {
    return (
      <div className="h-96 rounded-xl border bg-muted/30 animate-pulse" />
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border bg-background">
      <div className="flex flex-wrap items-center gap-1 border-b bg-muted/30 px-2 py-1.5">
        {mode === "edit" && (
        <>
        <Toggle
          size="sm"
          aria-label="Bold"
          pressed={state?.bold ?? false}
          onPressedChange={() => editor.chain().focus().toggleBold().run()}
        >
          <Bold />
        </Toggle>
        <Toggle
          size="sm"
          aria-label="Italic"
          pressed={state?.italic ?? false}
          onPressedChange={() => editor.chain().focus().toggleItalic().run()}
        >
          <Italic />
        </Toggle>

        <span className="mx-1 h-5 w-px bg-border" />

        <Toggle
          size="sm"
          aria-label="Heading 1"
          pressed={state?.h1 ?? false}
          onPressedChange={() =>
            editor.chain().focus().toggleHeading({ level: 1 }).run()
          }
        >
          <Heading1 />
        </Toggle>
        <Toggle
          size="sm"
          aria-label="Heading 2"
          pressed={state?.h2 ?? false}
          onPressedChange={() =>
            editor.chain().focus().toggleHeading({ level: 2 }).run()
          }
        >
          <Heading2 />
        </Toggle>

        <span className="mx-1 h-5 w-px bg-border" />

        <Toggle
          size="sm"
          aria-label="Bullet list"
          pressed={state?.bullet ?? false}
          onPressedChange={() =>
            editor.chain().focus().toggleBulletList().run()
          }
        >
          <List />
        </Toggle>
        <Toggle
          size="sm"
          aria-label="Ordered list"
          pressed={state?.ordered ?? false}
          onPressedChange={() =>
            editor.chain().focus().toggleOrderedList().run()
          }
        >
          <ListOrdered />
        </Toggle>

        <span className="mx-1 h-5 w-px bg-border" />

        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Undo"
          disabled={!(state?.canUndo ?? false)}
          onClick={() => editor.chain().focus().undo().run()}
        >
          <Undo2 />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Redo"
          disabled={!(state?.canRedo ?? false)}
          onClick={() => editor.chain().focus().redo().run()}
        >
          <Redo2 />
        </Button>
        </>
        )}

        {/* Edit / Preview switch — Preview shows the styled, generated look. */}
        <div className="ml-auto flex items-center gap-0.5 rounded-lg border bg-background p-0.5">
          <Button
            type="button"
            variant={mode === "edit" ? "secondary" : "ghost"}
            size="sm"
            className="h-7 gap-1.5 px-2.5"
            onClick={() => setMode("edit")}
          >
            <PenLine className="size-3.5" /> Edit
          </Button>
          <Button
            type="button"
            variant={mode === "preview" ? "secondary" : "ghost"}
            size="sm"
            className="h-7 gap-1.5 px-2.5"
            onClick={() => setMode("preview")}
          >
            <Eye className="size-3.5" /> Preview
          </Button>
        </div>
      </div>

      <div className="max-h-[36rem] overflow-y-auto bg-muted/20">
        <div className={cn(mode === "edit" ? "block" : "hidden")}>
          <EditorContent editor={editor} />
        </div>
        {mode === "preview" && (
          <iframe
            title="Template preview"
            sandbox=""
            className="h-[36rem] w-full border-0 bg-white"
            // Render the real template HTML (preserved on load and by the AI
            // agent), NOT editor.getHTML() — TipTap's schema flattens complex
            // markup (divs/classes/tables) so its serialization loses the layout.
            srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0}${
              css ?? ""
            }</style></head><body>${previewHtml ?? html}</body></html>`}
          />
        )}
      </div>
    </div>
  );
}
