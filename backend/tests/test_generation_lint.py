"""Phase 5 (polish): the pure placeholder<->doc-type consistency lint. Fully offline."""

from app.models import DocType, TemplateMode
from app.pipeline.generation import lint_template


def test_rich_html_all_valid_paths_no_orphans():
    html = (
        '<p><span data-field="vendor">Vendor</span> '
        '<span data-field="total">Total</span></p>'
    )
    r = lint_template(TemplateMode.rich_html, DocType.invoice, html, {})
    assert r.orphaned_paths == []
    assert r.total_count == 2
    assert r.bound_count == 2


def test_rich_html_unknown_path_is_orphaned():
    html = (
        '<p><span data-field="vendor">Vendor</span> '
        '<span data-field="bogus.path">X</span> '
        '<span data-field="bogus.path">X again</span></p>'
    )
    r = lint_template(TemplateMode.rich_html, DocType.invoice, html, {})
    # Deduped in the advisory list, but the two occurrences are reflected in the counts.
    assert r.orphaned_paths == ["bogus.path"]
    assert r.total_count == 3
    assert r.bound_count == 1


def test_form_fill_signature_not_counted_unknown_is_orphaned():
    field_map = {
        "vendor_name": {"field_path": "vendor", "is_signature": False},
        "sig": {"field_path": None, "is_signature": True},
        "unmapped": {"field_path": None, "is_signature": False},  # not a reference
        "weird": {"field_path": "nope.field", "is_signature": False},
    }
    r = lint_template(TemplateMode.form_fill, DocType.invoice, None, field_map)
    assert r.orphaned_paths == ["nope.field"]
    assert r.total_count == 2  # vendor + nope.field (signature + unmapped excluded)
    assert r.bound_count == 1


def test_empty_body_no_crash_zero_counts():
    r = lint_template(TemplateMode.rich_html, DocType.contract, None, {})
    assert r.orphaned_paths == []
    assert r.total_count == 0
    assert r.bound_count == 0
