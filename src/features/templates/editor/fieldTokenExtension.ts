// A TipTap atom inline node representing a bound field placeholder. It serializes
// to exactly the markup the backend binds at generation time:
//   <span data-field="line_items.0.amount" data-field-kind="number">Amount</span>
// so `editor.getHTML()` is byte-for-byte what gets persisted and later filled.
import { mergeAttributes, Node } from "@tiptap/core";

export interface FieldTokenAttributes {
  path: string;
  label: string;
  kind: string | null;
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    fieldToken: {
      /** Insert a field placeholder, replacing the current selection if any. */
      insertFieldToken: (attrs: FieldTokenAttributes) => ReturnType;
    };
  }
}

export const FieldToken = Node.create({
  name: "fieldToken",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      path: {
        default: "",
        parseHTML: (el) => el.getAttribute("data-field") ?? "",
        // `path` is emitted as data-field by renderHTML, not here.
        renderHTML: () => ({}),
      },
      kind: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-field-kind"),
        renderHTML: () => ({}),
      },
      label: {
        default: "",
        // The visible text is the node's rendered child, not an attribute.
        parseHTML: (el) => el.textContent ?? "",
        renderHTML: () => ({}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-field]" }];
  },

  renderHTML({ node }) {
    const attrs: Record<string, string> = {
      "data-field": String(node.attrs.path ?? ""),
    };
    if (node.attrs.kind) attrs["data-field-kind"] = String(node.attrs.kind);
    return ["span", mergeAttributes(attrs), String(node.attrs.label ?? "")];
  },

  addCommands() {
    return {
      insertFieldToken:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: {
              path: attrs.path,
              label: attrs.label || attrs.path,
              kind: attrs.kind ?? null,
            },
          }),
    };
  },
});
