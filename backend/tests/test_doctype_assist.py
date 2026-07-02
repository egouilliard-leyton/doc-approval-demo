"""Offline tests for the doc-type design wizard (Phase 3 Wave 1).

All LLM access is patched at ``app.pipeline.doctype_assistant._call_llm`` so these run
without network or an API key on PATH. They cover: turn-1 asks questions, a valid draft
finishes and passes the validators, the one-shot repair loop fixes an invalid draft,
repair-still-fails degrades gracefully, the missing-key guard raises, process docs reach
the context block, and an LLM error degrades without raising.
"""

import json

import pytest

from app.config import settings
from app.pipeline import doctype_assistant as da
from app.schemas import AssistRequest, AssistResponse, DocTypeCreate


@pytest.fixture(autouse=True)
def _set_key():
    """Most tests need a key set (only the missing-key test clears it)."""
    saved = settings.openrouter_api_key
    settings.openrouter_api_key = "test-key"
    try:
        yield
    finally:
        settings.openrouter_api_key = saved


# --- realistic draft fixtures (mirror a real DocTypeCreate) -------------------


def _valid_draft() -> dict:
    """A structurally sound purchase_order draft: scalars + a presence + a threshold."""
    return {
        "name": "purchase_order",
        "label": "Purchase Order",
        "icon": "",
        "extraction_definition": {
            "name": "purchase_order",
            "prompt": "",
            "core_paths": ["vendor", "po_number", "total"],
            "examples": [],
            "fields": [
                {"name": "vendor", "kind": "scalar", "cls": "Vendor", "coerce": "text", "is_core": True, "sub_fields": []},
                {"name": "po_number", "kind": "scalar", "cls": "PoNumber", "coerce": "text", "is_core": True, "sub_fields": []},
                {"name": "total", "kind": "scalar", "cls": "Total", "coerce": "number", "is_core": True, "sub_fields": []},
                {"name": "approval_signature", "kind": "presence", "cls": "ApprovalSignature", "coerce": "text", "is_core": False, "sub_fields": []},
            ],
        },
        "rule_definition": {
            "name": "purchase_order",
            "citation_paths": ["vendor", "po_number", "total"],
            "rules": [
                {"kind": "presence", "name": "vendor_present", "severity": "review", "field_path": "vendor"},
                {"kind": "presence", "name": "signature_present", "severity": "hard", "field_path": "approval_signature"},
                {"kind": "threshold", "name": "po_threshold", "severity": "review", "field_path": "total", "op": "lte", "threshold": 50000.0},
            ],
        },
        "citation_paths": ["vendor", "po_number", "total"],
    }


def _invalid_draft() -> dict:
    """Same shape but a rule references an undeclared field -> validators reject it."""
    draft = _valid_draft()
    draft["rule_definition"]["rules"][2]["field_path"] = "grand_total"  # not a declared field
    return draft


def _envelope(*, questions, spec, done, draft) -> str:
    return json.dumps(
        {
            "questions": questions,
            "updated_spec_markdown": spec,
            "done": done,
            "draft_doctype": draft,
        }
    )


# --- the draft fixtures pass / fail the real validators on their own ----------


def test_valid_draft_passes_validators():
    assert da._validate_draft(_valid_draft()) == []


def test_invalid_draft_is_rejected_by_validators():
    errors = da._validate_draft(_invalid_draft())
    assert errors and any("grand_total" in e for e in errors)


# --- turn 1: asks questions ----------------------------------------------------


def test_turn_one_asks_questions(monkeypatch):
    raw = _envelope(
        questions=["What kind of document is this?", "What must be approved?"],
        spec="# Draft\n",
        done=False,
        draft=None,
    )
    monkeypatch.setattr(da, "_call_llm", lambda messages: raw)
    out = da.run_assist_turn(AssistRequest(messages=[]))
    assert isinstance(out, AssistResponse)
    assert out.done is False
    assert out.draft_doctype is None
    assert len(out.questions) == 2


# --- valid draft -> done=True --------------------------------------------------


def test_valid_draft_completes(monkeypatch):
    raw = _envelope(questions=[], spec="# PO Spec\n", done=True, draft=_valid_draft())
    monkeypatch.setattr(da, "_call_llm", lambda messages: raw)
    out = da.run_assist_turn(AssistRequest(messages=[]))
    assert out.done is True
    assert out.warnings == []
    assert isinstance(out.draft_doctype, DocTypeCreate)
    assert out.draft_doctype.name == "purchase_order"
    assert out.questions == []


# --- repair loop fixes an invalid draft ---------------------------------------


def test_repair_loop_fixes_invalid(monkeypatch):
    first = _envelope(questions=[], spec="# PO\n", done=True, draft=_invalid_draft())
    second = _envelope(questions=[], spec="# PO\n", done=True, draft=_valid_draft())
    calls = {"n": 0}

    def fake(messages):
        calls["n"] += 1
        return first if calls["n"] == 1 else second

    monkeypatch.setattr(da, "_call_llm", fake)
    out = da.run_assist_turn(AssistRequest(messages=[]))
    assert calls["n"] == 2
    assert out.done is True
    assert isinstance(out.draft_doctype, DocTypeCreate)


# --- repair still fails -> graceful done=False + warnings ---------------------


def test_repair_still_fails(monkeypatch):
    invalid = _envelope(questions=[], spec="# PO\n", done=True, draft=_invalid_draft())
    calls = {"n": 0}

    def fake(messages):
        calls["n"] += 1
        return invalid

    monkeypatch.setattr(da, "_call_llm", fake)
    out = da.run_assist_turn(AssistRequest(messages=[]))
    assert calls["n"] == 2  # one initial + one repair
    assert out.done is False
    assert out.draft_doctype is None
    assert out.warnings and any("grand_total" in w for w in out.warnings)


# --- null top-level name -> graceful done=False, no 500 (regression) ----------


def test_null_name_degrades_gracefully(monkeypatch):
    """A draft whose extraction/rule are valid but whose top-level ``name`` is null must
    not raise (DocTypeCreate(**draft) would otherwise throw pydantic.ValidationError —
    NOT a ValueError — and escape as a FastAPI 500). The repair also returns name=null.
    """
    bad = _valid_draft()
    bad["name"] = None
    raw = _envelope(questions=[], spec="# PO\n", done=True, draft=bad)
    calls = {"n": 0}

    def fake(messages):
        calls["n"] += 1
        return raw

    monkeypatch.setattr(da, "_call_llm", fake)
    out = da.run_assist_turn(AssistRequest(messages=[]))
    assert calls["n"] == 2  # one initial + one repair, both name=null
    assert out.done is False
    assert out.draft_doctype is None
    assert out.warnings


# --- missing key -> raises -----------------------------------------------------


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    with pytest.raises(ValueError):
        da.run_assist_turn(AssistRequest(messages=[]))


# --- process docs reach the context block -------------------------------------


def test_process_docs_injected_into_context(monkeypatch):
    captured = {}

    def fake(messages):
        captured["messages"] = messages
        return _envelope(questions=["ok?"], spec="", done=False, draft=None)

    monkeypatch.setattr(da, "_call_llm", fake)
    da.run_assist_turn(
        AssistRequest(messages=[], process_docs=["SECRET-PROCESS-MARKER text"])
    )
    context = captured["messages"][1]["content"]
    assert "Process Documents:" in context
    assert "SECRET-PROCESS-MARKER" in context


def test_context_block_empty_prompts_user():
    block = da._build_context_block([], [], "", [])
    assert "No documents or spec yet" in block


# --- LLM raises -> graceful done=False + warning (no exception) ----------------


def test_llm_error_degrades_gracefully(monkeypatch):
    def boom(messages):
        raise RuntimeError("model down")

    monkeypatch.setattr(da, "_call_llm", boom)
    out = da.run_assist_turn(AssistRequest(messages=[], spec_markdown="# keep me\n"))
    assert out.done is False
    assert out.draft_doctype is None
    assert out.updated_spec_markdown == "# keep me\n"
    assert out.warnings and "assistant error" in out.warnings[0]


def test_unparsable_output_preserved_in_questions(monkeypatch):
    monkeypatch.setattr(da, "_call_llm", lambda messages: "this is not json")
    out = da.run_assist_turn(AssistRequest(messages=[]))
    assert out.done is False
    assert out.questions == ["this is not json"]
    assert out.warnings
