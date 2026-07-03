"""Purchase-order extraction, expressed declaratively and interpreted into a DocTypeSpec.

Mirrors :mod:`app.extraction.invoice`: the prompt, few-shot example, and field shape live
in ``PO_DEFINITION`` and :func:`~app.extraction.definition.build_spec` turns it into the
same :class:`DocTypeSpec` the rest of the pipeline consumes. A purchase order is the
"ordered" side of an AP 3-way match, so it carries the fields the reconciler lines up
against the invoice (``po_number``, ``vendor``, ``total``, and its line items).
"""

from __future__ import annotations

from .definition import (
    DocTypeDefinition,
    ExampleData,
    ExampleExtraction,
    FieldDef,
    SubFieldDef,
    build_spec,
)

PROMPT = """\
Extract approval-relevant fields from this purchase order. Use these extraction classes:
po_number, vendor, order_date, total, and line_item (one per row, with attributes desc,
qty, unit_price, amount).

Rules:
- Use the exact verbatim text from the source for each extraction_text (do not
  paraphrase or reformat) so each field can be traced back to its location.
- Fields often appear inside Markdown tables, not prose: a two-column label/value table
  (e.g. "| PO Number | PO-5567 |" -> po_number "PO-5567"), a totals table
  ("| Total | $1,234.56 |"), or a line-item table with a header row. Read values out of
  table cells just as you would from running text.
- Only extract a field if it actually appears in the text. Do NOT infer, guess, or
  fabricate. If a field is absent, simply emit no extraction for it.
- Emit dates and amounts as they appear in the document.\
"""


PO_DEFINITION = DocTypeDefinition(
    name="po",
    prompt=PROMPT,
    core_paths=["po_number", "vendor", "total", "line_items"],
    fields=[
        FieldDef(name="po_number", kind="scalar", cls="po_number", coerce="text"),
        FieldDef(name="vendor", kind="scalar", cls="vendor", coerce="text"),
        FieldDef(name="order_date", kind="scalar", cls="order_date", coerce="text"),
        FieldDef(name="total", kind="scalar", cls="total", coerce="number"),
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
    ],
    examples=[
        ExampleData(
            text=(
                "Acme Supplies Inc.\n"
                "Purchase Order PO-5567   Order Date: 2024-02-20\n"
                "10 x Widget @ 12.50 = 125.00\n"
                "Order Total: $135.00 USD"
            ),
            extractions=[
                ExampleExtraction(cls="po_number", text="PO-5567"),
                ExampleExtraction(cls="vendor", text="Acme Supplies Inc."),
                ExampleExtraction(cls="order_date", text="2024-02-20"),
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
                ExampleExtraction(cls="total", text="$135.00"),
            ],
        ),
    ],
)


SPEC = build_spec(PO_DEFINITION)
