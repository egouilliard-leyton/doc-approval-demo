"""Offline fixtures for the Phase 1 (form-fill) generation tests.

``make_fillable_pdf`` builds a small AcroForm PDF in-memory with reportlab so the
enumeration + source-upload paths can be exercised without any sample asset or network.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def make_fillable_pdf() -> bytes:
    """A one-page AcroForm PDF: two text fields, a checkbox, a dropdown, a signature.

    The last text field is literally named ``Signature`` so the name-based override to
    ``kind="signature"`` is covered.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    form = c.acroForm

    c.drawString(50, 700, "Vendor:")
    form.textfield(name="vendor_name", x=140, y=692, width=220, height=18)

    c.drawString(50, 660, "Total:")
    form.textfield(name="total_amount", x=140, y=652, width=220, height=18)

    c.drawString(50, 620, "Approved:")
    form.checkbox(name="approved", x=140, y=616, size=16)

    c.drawString(50, 580, "Currency:")
    form.choice(
        name="currency",
        value="USD",
        x=140,
        y=572,
        width=120,
        height=18,
        options=["USD", "EUR", "GBP"],
    )

    c.drawString(50, 540, "Signature:")
    form.textfield(name="Signature", x=140, y=532, width=220, height=18)

    c.save()
    return buf.getvalue()


def make_plain_pdf() -> bytes:
    """A one-page PDF with no AcroForm (drives the ``rich_html`` fallback path)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(50, 700, "Just some prose, no form fields here.")
    c.save()
    return buf.getvalue()
