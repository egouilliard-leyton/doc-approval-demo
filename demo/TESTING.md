# Testing the Templates / document-generation feature

This is a hands-on walkthrough of everything that was built. It takes ~10 minutes.

---

## 1. Where the automated tests are

All backend tests live in **`backend/tests/`**. The ones for this feature:

| File | What it covers |
|------|----------------|
| `test_templates.py` | Template CRUD, revisions, **restore**, placeholder **lint** |
| `test_generation_forms.py` | AcroForm enumeration, field catalogue, value flattening |
| `test_generation_mapper.py` | AI/heuristic field mapping (form-fill) |
| `test_generation_fill.py` | Fill a PDF form + stamp a signature |
| `test_generation_convert.py` | DOCX/PDF → editable HTML |
| `test_generation_binder.py` | Bind `{{placeholders}}` to extracted values |
| `test_generation_render.py` | HTML → PDF (WeasyPrint) + DOCX (html4docx) |
| `test_generation_rich.py` | Rich-HTML generate, multi-format output |
| `test_authoring_agent.py` | The streaming AI authoring agent (SSE) + tools |
| `test_generation_rasterize.py` / `test_generation_qa_vision.py` / `test_generation_qa.py` | The vision **Fidelity** QA loop |
| `test_generation_lint.py` | Placeholder ↔ doc-type consistency check |
| `test_smoke_e2e.py` | **End-to-end**: both generation journeys, top to bottom |

Run them (fully offline — no API key needed):

```bash
cd backend
uv run --no-sync pytest -q            # all 122 tests
uv run --no-sync pytest tests/test_smoke_e2e.py -v   # just the two headline journeys
```

Everything is real except the LLM/vision calls, which use deterministic mocks — WeasyPrint
renders actual PDFs and pypdfium2 rasterizes them for real inside the tests.

---

## 2. Launch the app to click through it yourself

```bash
./demo/run-demo.sh
```

Then open **http://localhost:5188** (use `localhost`, **not** `127.0.0.1` — the backend's CORS
is pinned to the `localhost` origin).

- **No API key** → the AI features (AI edit, Fidelity) return canned but realistic responses, so
  every screen is clickable and the whole flow works offline.
- **Real AI** → stop it, then relaunch with your key for genuine AI edits + vision checks:
  ```bash
  OPENROUTER_API_KEY=sk-or-... ./demo/run-demo.sh
  ```

Two test documents are in **`demo/`**:
- `demo/invoice-template.docx` — a formatted invoice → for the **rich-HTML** flow.
- `demo/expense-form.pdf` — a fillable PDF form → for the **form-fill** flow.

---

## Step 0 — Give it a processed document to fill from (do this once)

Generating fills a template from a **document you've already extracted**, so first create one:

1. On the top nav, you start on **Documents**.
2. Drag **`backend/samples/invoice-clean.pdf`** onto the dropzone (pick **Invoice**).
3. Let the pipeline run (pre-scan → OCR → structure → decide). It ends at a decision.
   *(With mock AI this is instant; it just needs to reach "structured/decided".)*

That document now shows up in the Generate picker later.

---

## Test A — Form-fill mode (upload a fillable PDF → map → generate)

1. Top nav → **Templates** → **New template** → choose **Invoice** → name it "Expense Form" → **Start blank**.
2. Open it. Drag **`demo/expense-form.pdf`** onto the source dropzone.
   → It detects the PDF's form fields and switches to **Form-fill** mode, showing a mapping table.
3. Click **AI suggest** → it auto-maps `vendor_name → Vendor`, `total_amount → Total`, `currency → Currency`
   (it leaves the `approved` checkbox unmapped — that's correct, nothing extracted matches it).
4. Click **Save mapping**.
5. Under **Generate**, pick the **invoice-clean.pdf** document from Step 0 → **Generate PDF**.
6. Click **Open PDF** → the form comes back filled with the extracted values. ✅

---

## Test B — Rich-HTML mode + AI edit + Fidelity + History (the full story)

1. Templates → **New template** → **Invoice** → name it "Invoice Letter" → **Start blank** → open it.
2. Drag **`demo/invoice-template.docx`** onto the source dropzone.
   → It **converts the DOCX to an editable HTML template** and **auto-runs the Fidelity check**,
     jumping to the **Fidelity** tab showing "self-review" + any drift it noticed. That's the
     *"upload an example → AI validates the format → shows it"* flow.
3. Go to the editor (main pane). Click into the text, then in the **Insert field** tab click
   **Vendor** (and **Total** if you like) to drop placeholder chips where the cursor is.
4. Click **Save template**.
5. **AI edit tab** — type an instruction and hit send. Try:

   > **make the invoice title navy, right-align the totals, and use a serif font for the body**

   → the agent streams its reply and **edits the template live** (with a real key it does exactly
     what you asked; with the mock it applies a fixed restyle so you can see the mechanism).
6. **Fidelity tab** → optionally pick the invoice document → **Run validation**
   → you get a verdict, a side-by-side (your example vs the rendered template), and a
     severity-coded checklist. Click **Send fixes to AI editor** to hand issues back to the agent.
7. **History tab** → every edit is listed → click **Restore** on an earlier one → the editor rolls
   back (and the restore is itself undoable — it appears as a new history entry).
8. Under **Generate**, pick the invoice document, toggle **PDF** and **DOCX**, **Generate** →
   **Open PDF** / **Open DOCX** → both come out filled with the vendor/total from the document. ✅

---

## What to say to the AI editor (more ideas)

Once you're in the **AI edit** tab of a rich-HTML template (with a real OpenRouter key):

- "Make the header a navy banner with white text."
- "Put the line items in a bordered table and right-align the amounts."
- "Add a bold 11pt 'Thank you for your business' line at the bottom in grey."
- "Insert a placeholder for the invoice number under the title."
- "Increase the bullet spacing and use a serif font throughout."

Each instruction is applied to the live HTML and saved as a revision you can roll back.
