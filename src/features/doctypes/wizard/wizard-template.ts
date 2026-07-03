// The fixed starting point for the "Create with AI" wizard. Opening the wizard is NOT
// an AI turn: the right-column spec preview is pre-seeded with this always-the-same
// markdown template, and the left column shows these always-the-same first questions.
// Only once the user answers and hits Send does the assistant get involved — it receives
// this template as the "Current Spec" and folds the answers into it. Keep the template's
// section structure aligned with the `updated_spec_markdown` contract the backend
// assistant emits (see backend/app/pipeline/doctype_assistant.py) so the first real turn
// edits a spec it already recognises.

/** The always-the-same clarifying questions shown when the wizard first opens. */
export const INITIAL_QUESTIONS: string[] = [
  "What kind of document is this, and what should approving it achieve? (e.g. vendor invoices we approve for payment)",
  "What are the key fields to pull out of it? (e.g. invoice number, vendor, line items, total)",
  "What rules should decide approval? (e.g. line items must sum to the total, a PO number is required, amount under a threshold)",
];

/** The always-the-same spec skeleton pre-loaded into the preview pane on open. */
export const INITIAL_SPEC_TEMPLATE = `# New Document Type Specification

## 1. Purpose
_Describe the document type and what approving it should achieve._

## 2. Fields to Extract
| Field | Kind | Coerce | Core | cls | Notes |
|-------|------|--------|------|-----|-------|
| _e.g. invoice_no_ | scalar | text | yes | InvoiceNo | The document's unique identifier |

## 3. Approval Rules
| Rule | Kind | Severity | Params | Rationale |
|------|------|----------|--------|-----------|
| _e.g. total_present_ | presence | hard | field_path: total | The total is required to approve |

## 4. Citation Paths
- _List the fields worth citing in a decision._

## 5. Open Questions / Assumptions
- _Anything still to decide goes here._
`;
