"""Phase 2 (rich-HTML) Wave 1: bind flattened field values into a template's HTML body.

A rich-HTML template carries placeholder markers in its body — ``<span data-field="path">``
for a text value and ``<img data-signature>`` for the signature stamp. :func:`bind_html`
walks those markers with BeautifulSoup and fills each from a document's flattened values
(the dotted-path map produced by :func:`app.pipeline.generation.values.flatten_field_values`).
A path that is missing or ``None`` renders empty and is recorded as skipped rather than
guessed; the signature image is inlined as a base64 data URI or the placeholder removed.
Binding never raises on a bad path — every decision is recorded in the :class:`BindOutcome`.
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass, field as dc_field


@dataclass
class BindOutcome:
    """Result of :func:`bind_html`: the filled body plus which paths took / were skipped."""

    html: str
    filled: list[str] = dc_field(default_factory=list)
    skipped: list[str] = dc_field(default_factory=list)
    signature_stamped: bool = False
    warnings: list[str] = dc_field(default_factory=list)


def bind_html(
    html_body: str,
    flat_values: dict[str, object],
    signature_bytes: bytes | None,
) -> BindOutcome:
    """Fill ``span[data-field]`` placeholders + the ``img[data-signature]`` stamp.

    ``flat_values`` maps dotted paths to extracted scalars. Each ``span[data-field="path"]``
    gets its text set to ``str(value)`` when the path resolves to a non-``None`` value (added
    to ``filled``); otherwise its text is cleared and the path recorded in ``skipped``. Each
    ``img[data-signature]`` becomes a base64 PNG data URI when ``signature_bytes`` is supplied
    (setting ``signature_stamped``), else the ``<img>`` is removed.
    """
    from bs4 import BeautifulSoup  # lazy: optional docgen dep

    outcome = BindOutcome(html=html_body)
    soup = BeautifulSoup(html_body, "html.parser")

    for span in soup.select("span[data-field]"):
        path = span.get("data-field") or ""
        value = flat_values.get(path)
        if path in flat_values and value is not None:
            span.string = str(value)
            outcome.filled.append(path)
        else:
            span.string = ""  # never guess a missing/None value
            outcome.skipped.append(path)

    for img in soup.select("img[data-signature]"):
        if signature_bytes:
            encoded = base64.b64encode(signature_bytes).decode("ascii")
            img["src"] = f"data:image/png;base64,{encoded}"
            outcome.signature_stamped = True
        else:
            img.decompose()  # no signature supplied -> drop the placeholder image

    outcome.html = str(soup)
    return outcome


def render_field_placeholder(path: str, label: str, kind: str | None) -> str:
    """Build a ``span[data-field]`` placeholder marker for the editor / bind contract.

    Returns exactly ``<span data-field="{path}" data-field-kind="{kind}">{label}</span>`` with
    ``path``/``kind`` escaped for attribute safety and ``label`` HTML-escaped; the ``data-field-kind``
    attribute is omitted entirely when ``kind is None``. Mirrors the frontend field-token markup and
    is parseable by :func:`bind_html`'s ``span[data-field]`` selector.
    """
    kind_attr = f' data-field-kind="{html.escape(kind, quote=True)}"' if kind is not None else ""
    return (
        f'<span data-field="{html.escape(path, quote=True)}"{kind_attr}>'
        f"{html.escape(label)}</span>"
    )
