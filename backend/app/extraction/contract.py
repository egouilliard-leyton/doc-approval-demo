"""Contract extraction, expressed declaratively and interpreted into a DocTypeSpec.

The prompt, few-shot examples, and field shape that used to be hand-written here now
live in ``CONTRACT_DEFINITION``; :func:`~app.extraction.definition.build_spec` turns it
into the same :class:`DocTypeSpec` the rest of the pipeline consumes.
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

# Use the exact prompt the hand-written spec carried (copied verbatim).
PROMPT = """\
Extract approval-relevant fields from this contract. Use these extraction classes:
party (one per signatory/organization), effective_date, term, renewal_clause,
termination_clause (with attribute notice_period), governing_law, total_value,
liability_cap, signature (one per executed signature), and key_date (with attribute
label, e.g. "renewal" or "expiry").

Rules:
- Use the exact verbatim text from the source for each extraction_text (do not
  paraphrase) so each field can be traced back to its location.
- Only extract a field if it actually appears in the text. Do NOT infer, guess, or
  fabricate. If a field is absent, simply emit no extraction for it.\
"""


CONTRACT_DEFINITION = DocTypeDefinition(
    name="contract",
    prompt=PROMPT,
    core_paths=["parties", "effective_date", "term", "governing_law"],
    fields=[
        FieldDef(name="parties", kind="list_scalar", cls="party", coerce="text", dedup=True),
        FieldDef(name="effective_date", kind="scalar", cls="effective_date", coerce="text"),
        FieldDef(name="term", kind="scalar", cls="term", coerce="text"),
        FieldDef(name="renewal_clause", kind="scalar", cls="renewal_clause", coerce="text"),
        FieldDef(
            name="termination_clause",
            kind="composite",
            cls="termination_clause",
            sub_fields=[
                SubFieldDef(name="text", source="span", coerce="text"),
                SubFieldDef(name="notice_period", source="attribute", coerce="text"),
            ],
        ),
        FieldDef(name="governing_law", kind="scalar", cls="governing_law", coerce="text"),
        FieldDef(name="total_value", kind="scalar", cls="total_value", coerce="number"),
        FieldDef(name="liability_cap", kind="scalar", cls="liability_cap", coerce="number"),
        FieldDef(name="signatures_present", kind="presence", cls="signature"),
        # Spatially-detected signature crops (YOLOv8 post-pass over the page images).
        # ``cls="signature_visual"`` is distinct from the text ``signature`` class so the
        # LLM never populates it; the structuring post-pass fills it from the detector.
        FieldDef(name="signatures", kind="signature", cls="signature_visual"),
        FieldDef(name="key_dates", kind="list_scalar", cls="key_date", coerce="text", dedup=True),
    ],
    examples=[
        ExampleData(
            text=(
                "MASTER SERVICES AGREEMENT between Acme Corp and Beta LLC.\n"
                "Effective Date: 2024-01-01. Term: 24 months.\n"
                "This Agreement renews automatically for successive 12-month terms.\n"
                "Either party may terminate on 60 days written notice.\n"
                "Governing law: State of Delaware. Total contract value: $250,000.\n"
                "Liability cap: $50,000.\n"
                "Signed: Jane Roe (Acme Corp), John Doe (Beta LLC)."
            ),
            extractions=[
                ExampleExtraction(cls="party", text="Acme Corp"),
                ExampleExtraction(cls="party", text="Beta LLC"),
                ExampleExtraction(cls="effective_date", text="2024-01-01"),
                ExampleExtraction(cls="term", text="24 months"),
                ExampleExtraction(
                    cls="renewal_clause",
                    text="renews automatically for successive 12-month terms",
                ),
                ExampleExtraction(
                    cls="termination_clause",
                    text="Either party may terminate on 60 days written notice",
                    attributes={"notice_period": "60 days"},
                ),
                ExampleExtraction(cls="governing_law", text="State of Delaware"),
                ExampleExtraction(cls="total_value", text="$250,000"),
                ExampleExtraction(cls="liability_cap", text="$50,000"),
                ExampleExtraction(cls="signature", text="Jane Roe"),
                ExampleExtraction(cls="signature", text="John Doe"),
            ],
        ),
        ExampleData(
            # Omits liability cap + signatures -> teaches the model to leave them out.
            text=(
                "Consulting Agreement dated 2023-09-15 by and between Globex and Initech.\n"
                "Initial term of one year, governed by the laws of England and Wales.\n"
                "Renewal date: 2024-09-15."
            ),
            extractions=[
                ExampleExtraction(cls="party", text="Globex"),
                ExampleExtraction(cls="party", text="Initech"),
                ExampleExtraction(cls="effective_date", text="2023-09-15"),
                ExampleExtraction(cls="term", text="one year"),
                ExampleExtraction(cls="governing_law", text="England and Wales"),
                ExampleExtraction(
                    cls="key_date",
                    text="2024-09-15",
                    attributes={"label": "renewal"},
                ),
            ],
        ),
    ],
)


SPEC = build_spec(CONTRACT_DEFINITION)
