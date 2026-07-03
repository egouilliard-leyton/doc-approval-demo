"""The wizard's system prompt derives its field/rule catalogue from the live dataclasses.

These tests are the drift guard: if someone adds a rule primitive or field kind, it must
show up in the wizard prompt automatically. They assert the generated reference covers
EVERY serializable rule kind and EVERY field kind — so the wizard can never silently fall
behind ``serialization.validate_custom_*`` again (the exact failure this replaced).
"""

from __future__ import annotations

from typing import get_args, get_type_hints

from app.extraction.definition import FieldDef
from app.pipeline.doctype_assistant import _SYSTEM_PROMPT
from app.pipeline.doctype_schema_reference import build_schema_reference
from app.rules.expression import _HELPERS
from app.rules.formats import FORMAT_KEYS
from app.serialization import _KIND_MAP


def test_reference_covers_every_rule_kind() -> None:
    ref = build_schema_reference()
    for kind in _KIND_MAP.values():
        assert f'"{kind}"' in ref, f"rule kind {kind!r} missing from the wizard prompt"


def test_reference_covers_every_field_kind() -> None:
    ref = build_schema_reference()
    for kind in get_args(get_type_hints(FieldDef)["kind"]):
        assert f'"{kind}"' in ref, f"field kind {kind!r} missing from the wizard prompt"


def test_reference_lists_format_keys_and_dsl_helpers() -> None:
    ref = build_schema_reference()
    for fmt in FORMAT_KEYS:
        assert fmt in ref, f"format {fmt!r} missing from the wizard prompt"
    for helper in _HELPERS:
        assert f"`{helper}`" in ref, f"DSL helper {helper!r} missing from the wizard prompt"


def test_system_prompt_embeds_the_reference() -> None:
    # The prompt must actually carry the derived catalogue, not just the static frame.
    assert build_schema_reference() in _SYSTEM_PROMPT
    assert "signature" in _SYSTEM_PROMPT  # the newest field kind, absent in the old prompt
