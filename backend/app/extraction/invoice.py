"""Invoice extraction, expressed declaratively and interpreted into a DocTypeSpec.

The prompt, few-shot examples, and field shape that used to be hand-written here now
live in ``INVOICE_DEFINITION``; :func:`~app.extraction.definition.build_spec` turns it
into the same :class:`DocTypeSpec` the rest of the pipeline consumes.
"""

from __future__ import annotations

import typing

from .definition import (
    DocTypeDefinition,
    ExampleData,
    ExampleExtraction,
    FieldDef,
    SubFieldDef,
    build_spec,
)

# Use the exact prompt the hand-written spec carried (copied verbatim).
PROMPT = """\
Extract approval-relevant fields from this invoice. Use these extraction classes:
vendor, invoice_no, po_number, invoice_date, due_date, subtotal, tax, total,
currency, payment_terms, bank_details, and line_item (one per row, with attributes
desc, qty, unit_price, amount).

Rules:
- Use the exact verbatim text from the source for each extraction_text (do not
  paraphrase or reformat) so each field can be traced back to its location.
- Fields often appear inside Markdown tables, not prose: a two-column label/value
  table (e.g. "| Invoice Number | INV-3337 |" -> invoice_no "INV-3337"), a totals
  table ("| Total | $93.50 |"), or a line-item table with a header row. Read values
  out of table cells just as you would from running text.
- Only extract a field if it actually appears in the text. Do NOT infer, guess, or
  fabricate. If a field is absent, simply emit no extraction for it.
- Emit dates and amounts as they appear in the document.\
"""


INVOICE_DEFINITION = DocTypeDefinition(
    name="invoice",
    prompt=PROMPT,
    core_paths=["vendor", "invoice_no", "total", "line_items"],
    fields=[
        FieldDef(name="vendor", kind="scalar", cls="vendor", coerce="text"),
        FieldDef(name="invoice_no", kind="scalar", cls="invoice_no", coerce="text"),
        FieldDef(name="po_number", kind="scalar", cls="po_number", coerce="text"),
        FieldDef(name="invoice_date", kind="scalar", cls="invoice_date", coerce="text"),
        FieldDef(name="due_date", kind="scalar", cls="due_date", coerce="text"),
        FieldDef(
            name="line_items",
            kind="list_composite",
            cls="line_item",
            sub_fields=[
                SubFieldDef(name="desc", source="attribute", coerce="text"),
                SubFieldDef(name="qty", source="attribute", coerce="number"),
                SubFieldDef(name="unit_price", source="attribute", coerce="number"),
                SubFieldDef(name="amount", source="attribute", coerce="number"),
            ],
        ),
        FieldDef(name="subtotal", kind="scalar", cls="subtotal", coerce="number"),
        FieldDef(name="tax", kind="scalar", cls="tax", coerce="number"),
        FieldDef(name="total", kind="scalar", cls="total", coerce="number"),
        FieldDef(name="currency", kind="scalar", cls="currency", coerce="text"),
        FieldDef(name="payment_terms", kind="scalar", cls="payment_terms", coerce="text"),
        FieldDef(name="bank_details_present", kind="presence", cls="bank_details"),
    ],
    examples=[
        ExampleData(
            text=(
                "Acme Supplies Inc.\n"
                "Invoice #INV-2024-001   PO: PO-5567\n"
                "Date: 2024-03-01   Due: 2024-03-31\n"
                "10 x Widget @ 12.50 = 125.00\n"
                "Subtotal: 125.00  Tax: 10.00  Total: $135.00 USD\n"
                "Payment terms: Net 30\n"
                "Remit to IBAN GB29 NWBK 6016 1331 9268 19"
            ),
            extractions=[
                ExampleExtraction(cls="vendor", text="Acme Supplies Inc."),
                ExampleExtraction(cls="invoice_no", text="INV-2024-001"),
                ExampleExtraction(cls="po_number", text="PO-5567"),
                ExampleExtraction(cls="invoice_date", text="2024-03-01"),
                ExampleExtraction(cls="due_date", text="2024-03-31"),
                ExampleExtraction(
                    cls="line_item",
                    text="10 x Widget @ 12.50 = 125.00",
                    attributes={
                        "desc": "Widget",
                        "qty": "10",
                        "unit_price": "12.50",
                        "amount": "125.00",
                    },
                ),
                ExampleExtraction(cls="subtotal", text="125.00"),
                ExampleExtraction(cls="tax", text="10.00"),
                ExampleExtraction(cls="total", text="$135.00"),
                ExampleExtraction(cls="currency", text="USD"),
                ExampleExtraction(cls="payment_terms", text="Net 30"),
                ExampleExtraction(
                    cls="bank_details",
                    text="IBAN GB29 NWBK 6016 1331 9268 19",
                ),
            ],
        ),
        ExampleData(
            # Second example deliberately omits PO and bank details -> the model
            # learns to leave absent fields unextracted rather than invent them.
            text=(
                "Globex Ltd\n"
                "Invoice No: 7781   Issued 05/02/2024\n"
                "Consulting services .......... 2,000.00\n"
                "Total due: 2,000.00 EUR"
            ),
            extractions=[
                ExampleExtraction(cls="vendor", text="Globex Ltd"),
                ExampleExtraction(cls="invoice_no", text="7781"),
                ExampleExtraction(cls="invoice_date", text="05/02/2024"),
                ExampleExtraction(
                    cls="line_item",
                    text="Consulting services .......... 2,000.00",
                    attributes={"desc": "Consulting services", "amount": "2,000.00"},
                ),
                ExampleExtraction(cls="total", text="2,000.00"),
                ExampleExtraction(cls="currency", text="EUR"),
            ],
        ),
        ExampleData(
            # Third example is Markdown-table shaped — exactly what OCR engines
            # (Docling, VLMs) emit — so the model learns to read fields out of
            # two-column label/value tables and a line-item table, not just prose.
            text=(
                "Northwind Web Studio\n"
                "Bill To: Test Business\n"
                "| Hrs/Qty | Service | Rate/Price | Adjust |\n"
                "| --- | --- | --- | --- |\n"
                "| 1.00 | Web Design | $85.00 | 0.00% |\n"
                "| Sub Total | $85.00 |\n"
                "| Tax | $8.50 |\n"
                "| Total | $93.50 |\n"
                "| Invoice Number | INV-3337 |\n"
                "| PO Number | PO-9911 |\n"
                "| Invoice Date | January 25, 2016 |\n"
                "| Due Date | January 31, 2016 |\n"
                "| Total Due | $93.50 |\n"
                "Payment is due within 30 days\n"
                "ANZ Bank ACC #12341234 BSB #4321432"
            ),
            extractions=[
                ExampleExtraction(cls="vendor", text="Northwind Web Studio"),
                ExampleExtraction(cls="invoice_no", text="INV-3337"),
                ExampleExtraction(cls="po_number", text="PO-9911"),
                ExampleExtraction(cls="invoice_date", text="January 25, 2016"),
                ExampleExtraction(cls="due_date", text="January 31, 2016"),
                ExampleExtraction(
                    cls="line_item",
                    text="| 1.00 | Web Design | $85.00 | 0.00% |",
                    attributes={
                        "desc": "Web Design",
                        "qty": "1.00",
                        "unit_price": "$85.00",
                        "amount": "$85.00",
                    },
                ),
                ExampleExtraction(cls="subtotal", text="$85.00"),
                ExampleExtraction(cls="tax", text="$8.50"),
                ExampleExtraction(cls="total", text="$93.50"),
                ExampleExtraction(
                    cls="payment_terms", text="Payment is due within 30 days"
                ),
                ExampleExtraction(
                    cls="bank_details", text="ANZ Bank ACC #12341234 BSB #4321432"
                ),
            ],
        ),
    ],
)


SPEC = build_spec(INVOICE_DEFINITION)

# Re-export the synthesised line-item row model under its historical name so
# ``app.pipeline.structuring._backfill_from_tables`` can keep doing
# ``from app.extraction.invoice import LineItem`` and constructing it directly.
LineItem = typing.get_args(SPEC.field_model.model_fields["line_items"].annotation)[0]
