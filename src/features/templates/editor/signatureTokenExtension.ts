// A TipTap atom inline node marking where a signature image should be stamped.
// It serializes to exactly `<img data-signature="true">` — the marker the backend
// swaps for the uploaded signature image at generation time. In-editor appearance
// (a small bordered placeholder box) is applied purely via a scoped CSS rule in
// index.css, so no styling attributes leak into the persisted HTML.
import { mergeAttributes, Node } from "@tiptap/core";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    signatureToken: {
      /** Insert a signature-image placeholder at the cursor. */
      insertSignatureToken: () => ReturnType;
    };
  }
}

export const SignatureToken = Node.create({
  name: "signatureToken",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  parseHTML() {
    return [{ tag: "img[data-signature]" }];
  },

  renderHTML() {
    return ["img", mergeAttributes({ "data-signature": "true" })];
  },

  addCommands() {
    return {
      insertSignatureToken:
        () =>
        ({ commands }) =>
          commands.insertContent({ type: this.name }),
    };
  },
});
