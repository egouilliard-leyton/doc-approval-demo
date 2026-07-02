"""Delivery-note extraction, expressed declaratively and interpreted into a DocTypeSpec.

Mirrors :mod:`app.extraction.invoice`: the prompt, few-shot example, and field shape live
in ``DELIVERY_NOTE_DEFINITION`` and :func:`~app.extraction.definition.build_spec` turns it
into the same :class:`DocTypeSpec` the rest of the pipeline consumes. A delivery note is the
"received" side of an AP 3-way match: it records what actually arrived (received quantities
per line), so it rounds out the four-document match as a completeness-only member.
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
Extract approval-relevant fields from this delivery note. Use these extraction classes:
delivery_note_no, delivery_date, vendor, and line_item (one per row, with attributes desc,
qty — the received quantity).

Rules:
- Use the exact verbatim text from the source for each extraction_text (do not
  paraphrase or reformat) so each field can be traced back to its location.
- Fields often appear inside Markdown tables, not prose: a two-column label/value table
  (e.g. "| Delivery Note | DN-8891 |") or a line-item table with a header row. Read values
  out of table cells just as you would from running text.
- Only extract a field if it actually appears in the text. Do NOT infer, guess, or
  fabricate. If a field is absent, simply emit no extraction for it.
- Emit dates as they appear in the document.\
"""


DELIVERY_NOTE_DEFINITION = DocTypeDefinition(
    name="delivery_note",
    prompt=PROMPT,
    core_paths=["delivery_note_no", "delivery_date", "vendor", "line_items"],
    fields=[
        FieldDef(name="delivery_note_no", kind="scalar", cls="delivery_note_no", coerce="text"),
        FieldDef(name="delivery_date", kind="scalar", cls="delivery_date", coerce="text"),
        FieldDef(name="vendor", kind="scalar", cls="vendor", coerce="text"),
        FieldDef(
            name="line_items",
            kind="list_composite",
            cls="line_item",
            sub_fields=[
                SubFieldDef(name="desc", source="attribute", coerce="text"),
                SubFieldDef(name="qty", source="attribute", coerce="number"),
            ],
        ),
    ],
    examples=[
        ExampleData(
            text=(
                "Acme Supplies Inc.\n"
                "Delivery Note DN-8891   Delivered: 2024-03-05\n"
                "Received: 10 x Widget"
            ),
            extractions=[
                ExampleExtraction(cls="delivery_note_no", text="DN-8891"),
                ExampleExtraction(cls="delivery_date", text="2024-03-05"),
                ExampleExtraction(cls="vendor", text="Acme Supplies Inc."),
                ExampleExtraction(
                    cls="line_item",
                    text="Received: 10 x Widget",
                    attributes={"desc": "Widget", "qty": "10"},
                ),
            ],
        ),
    ],
)


SPEC = build_spec(DELIVERY_NOTE_DEFINITION)
