"""The AI doc-type design wizard — a conversational agent that turns a user's
description (plus uploaded process/example documents and review annotations) into a
validated :class:`~app.schemas.DocTypeCreate`.

A single OpenRouter call drives each turn. The agent runs in three phases: ELICITING
(ask clarifying questions, keep a living markdown spec, ``done=false``), REFINING (fold
in the user's annotations from the last Plannotator review), and COMPLETE (emit a
``draft_doctype`` and set ``done=true``). When the model claims completion, its draft is
validated against the same serialization validators + ``build_spec`` the CRUD layer uses;
if invalid, a single internal repair turn is attempted before giving up gracefully.

This module has NO FastAPI imports — it is importable and unit-testable standalone.
``openai`` is imported lazily inside :func:`_call_llm`, and that function is module-level
so tests can patch ``app.pipeline.doctype_assistant._call_llm``.
"""

from __future__ import annotations

import json

from app.config import settings
from app.extraction.definition import build_spec
from app.pipeline.doctype_schema_reference import build_schema_reference
from app.schemas import AssistRequest, AssistResponse, DocTypeCreate
from app.serialization import (
    dict_to_extraction_defn,
    validate_custom_extraction_dict,
    validate_custom_rule_dict,
)

# The head + tail are static; the field/rule/DSL catalogue in the middle is DERIVED from
# the live dataclasses (see doctype_schema_reference) so the prompt can never fall behind
# the validator when a new primitive is added.
_PROMPT_HEAD = """\
You are a document-type design wizard. You help a user turn a description of a kind of \
document (plus any uploaded process/example documents) into a precise, machine-runnable \
document-type definition for an approval pipeline.

You operate in three phases:
- ELICITING: when the design is still incomplete, ask 1-3 focused clarifying questions, \
keep the markdown spec updated to reflect everything decided so far, and set \
"done": false (leave "draft_doctype": null).
- REFINING: when the user has reviewed the spec and returned annotations (shown under \
"User Annotations from Last Review"), fold their feedback into the spec and either ask \
follow-up questions or finalize.
- COMPLETE: when the design is unambiguous and the user is satisfied, set "done": true, \
emit the full "draft_doctype" object, and return "questions": [].

Prefer a dedicated rule kind over an "expression" or "llm_advisory" whenever one fits — \
they are deterministic and clearer. Reach for "expression" only for a check no dedicated \
kind covers, and "llm_advisory" only for genuinely subjective judgments.

Respond ONLY with a JSON object (no markdown fences) of exactly this shape:
{
  "questions": ["..."],            // clarifying questions; [] when done
  "updated_spec_markdown": "...",  // the full current spec, always in the template below
  "done": false,                   // true only when draft_doctype is emitted and valid
  "draft_doctype": null            // the DocTypeCreate object when done, else null
}

The "draft_doctype" object MUST follow this contract exactly:
{
  "name": "snake_case_identifier",
  "label": "Human Label",
  "icon": "",
  "extraction_definition": {
    "name": "<same as top-level name>",
    "prompt": "",
    "core_paths": ["<declared field name>", ...],
    "examples": [],
    "fields": [ ...field objects, see "Extraction fields" below... ]
  },
  "rule_definition": {
    "name": "<same as top-level name>",
    "citation_paths": ["<declared field name>", ...],
    "rules": [ ...rule objects, see "Approval rule kinds" below... ]
  },
  "citation_paths": ["<declared field name>", ...]
}"""

_PROMPT_TAIL = """\
Hard requirements:
- Every "*_path" / "*_paths" in a rule MUST name a declared extraction field.
- extraction_definition.name == rule_definition.name == top-level name.
- Always set "prompt": "" and "examples": [] in extraction_definition.

Always output "updated_spec_markdown" using EXACTLY this structure:

# <Label> Specification

## 1. Purpose
<one-paragraph description of the document type and the approval goal>

## 2. Fields to Extract
| Field | Kind | Coerce | Core | cls | Notes |
|-------|------|--------|------|-----|-------|
<one row per field; for composite/list_composite fields, list sub-fields in Notes>

## 3. Approval Rules
| Rule | Kind | Severity | Params | Rationale |
|------|------|----------|--------|-----------|
<one row per rule>

## 4. Citation Paths
<bullet list of the fields worth citing in a decision>

## 5. Open Questions / Assumptions
<bullet list of anything still unresolved or assumed>

Respond ONLY with a JSON object, no markdown fences."""


def _build_system_prompt() -> str:
    """Assemble the system prompt, injecting the dataclass-derived schema catalogue."""
    return f"{_PROMPT_HEAD}\n\n{build_schema_reference()}\n\n{_PROMPT_TAIL}"


_SYSTEM_PROMPT = _build_system_prompt()


def _build_context_block(
    process_docs: list[str],
    example_docs: list[str],
    spec_markdown: str,
    annotations: list[dict],
) -> str:
    """Assemble the plain-text context handed to the model as the first user message.

    Returns a prompt asking what the user wants to build when nothing is supplied yet.
    """
    sections: list[str] = []
    if process_docs:
        body = "\n\n".join(d for d in process_docs)
        sections.append(f"Process Documents:\n{body}")
    if example_docs:
        body = "\n\n".join(d for d in example_docs)
        sections.append(f"Example Documents:\n{body}")
    if spec_markdown:
        sections.append(f"Current Spec:\n{spec_markdown}")
    if annotations:
        lines = [
            f"- Decision: {a.get('decision')}. Feedback: {a.get('feedback')}"
            for a in annotations
        ]
        sections.append("User Annotations from Last Review:\n" + "\n".join(lines))

    if not sections:
        return (
            "No documents or spec yet. Ask the user what kind of document they want "
            "to create."
        )
    return "\n\n".join(sections)


def _build_llm_messages(request: AssistRequest) -> list[dict]:
    """Build the OpenRouter message list: system, the context block, then the transcript."""
    context_block = _build_context_block(
        request.process_docs,
        request.example_docs,
        request.spec_markdown,
        request.annotations,
    )
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": context_block},
    ]
    messages.extend({"role": m.role, "content": m.content} for m in request.messages)
    return messages


def _call_llm(messages: list[dict]) -> str:
    """Single OpenRouter chat completion; returns the raw response content string.

    Module-level (and lazily importing ``openai``) so offline tests can patch it.
    """
    import openai  # lazy: optional dep

    client = openai.OpenAI(
        api_key=settings.openrouter_api_key, base_url=settings.assist_base_url
    )
    response = client.chat.completions.create(
        model=settings.assist_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0,
    )
    return response.choices[0].message.content or "{}"


def _validate_draft(draft: dict) -> list[str]:
    """Validate a candidate ``draft_doctype`` dict, returning human-readable errors.

    Runs the two serialization validators and additionally tries ``build_spec`` (which
    catches cls / Pydantic-model errors the structural validators miss).
    """
    errors: list[str] = []
    if not isinstance(draft.get("name"), str) or not draft.get("name"):
        errors.append("draft_doctype: 'name' must be a non-empty string")
    if not isinstance(draft.get("label"), str) or not draft.get("label"):
        errors.append("draft_doctype: 'label' must be a non-empty string")
    if draft.get("citation_paths") is not None and not isinstance(draft.get("citation_paths"), list):
        errors.append("draft_doctype: 'citation_paths' must be a list")
    extraction = draft.get("extraction_definition")
    rule = draft.get("rule_definition")
    if not isinstance(extraction, dict):
        return [*errors, "draft_doctype: 'extraction_definition' must be an object"]
    if not isinstance(rule, dict):
        return [*errors, "draft_doctype: 'rule_definition' must be an object"]

    errors.extend(validate_custom_extraction_dict(extraction))
    fields = extraction.get("fields")
    field_names = {
        f["name"]
        for f in (fields if isinstance(fields, list) else [])
        if isinstance(f, dict) and isinstance(f.get("name"), str)
    }
    errors.extend(validate_custom_rule_dict(rule, field_names))

    # Catch cls/model errors the structural validators don't (e.g. a missing "cls" key).
    try:
        build_spec(dict_to_extraction_defn(extraction))
    except Exception as exc:  # noqa: BLE001 — surface as a validation error, never raise
        errors.append(f"extraction definition failed to build: {exc}")

    return errors


def _parse_response(raw: str) -> dict:
    """Parse the model's JSON envelope; raise on anything that isn't a JSON object."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("assistant response was not a JSON object")
    return payload


def run_assist_turn(request: AssistRequest) -> AssistResponse:
    """Run one wizard turn: call the assistant, parse it, and validate any final draft.

    Never raises into the caller except the explicit key guard. Any LLM/parse failure
    degrades to a graceful ``done=False`` response carrying a warning.
    """
    if not settings.openrouter_api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is not set; the doc-type assistant needs it."
        )

    messages = _build_llm_messages(request)
    try:
        raw = _call_llm(messages)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, surface as a warning
        return AssistResponse(
            questions=["(assistant unavailable)"],
            updated_spec_markdown=request.spec_markdown,
            done=False,
            draft_doctype=None,
            warnings=[f"assistant error: {exc}"],
        )

    try:
        payload = _parse_response(raw)
    except Exception as exc:  # noqa: BLE001 — unparsable model output -> safe fallback
        return AssistResponse(
            questions=[raw],
            updated_spec_markdown=request.spec_markdown,
            done=False,
            draft_doctype=None,
            warnings=[f"assistant returned unparsable output: {exc}"],
        )

    questions = [str(q) for q in (payload.get("questions") or [])]
    updated_spec = str(payload.get("updated_spec_markdown") or request.spec_markdown)
    done = bool(payload.get("done"))
    draft = payload.get("draft_doctype")

    # Not finished (or no draft to validate): hand the turn straight back.
    if not done or not isinstance(draft, dict):
        return AssistResponse(
            questions=questions,
            updated_spec_markdown=updated_spec,
            done=False,
            draft_doctype=None,
            warnings=[],
        )

    errors = _validate_draft(draft)
    if errors:
        # One internal repair attempt: ask the model to fix the listed errors and
        # re-emit ONLY the JSON. The repair message is internal — not added to the
        # frontend transcript.
        repair_msg = {
            "role": "user",
            "content": (
                "Your draft_doctype has these validation errors. Fix them and re-emit "
                "ONLY the JSON:\n" + "\n".join(f"- {e}" for e in errors)
            ),
        }
        try:
            raw = _call_llm([*messages, {"role": "assistant", "content": raw}, repair_msg])
            payload = _parse_response(raw)
        except Exception as exc:  # noqa: BLE001 — repair failed -> give up gracefully
            return AssistResponse(
                questions=[],
                updated_spec_markdown=updated_spec,
                done=False,
                draft_doctype=None,
                warnings=[f"draft validation failed and repair errored: {exc}"],
            )
        questions = [str(q) for q in (payload.get("questions") or [])]
        updated_spec = str(payload.get("updated_spec_markdown") or updated_spec)
        draft = payload.get("draft_doctype")
        errors = _validate_draft(draft) if isinstance(draft, dict) else ["repair did not emit a draft_doctype"]
        if errors:
            return AssistResponse(
                questions=[],
                updated_spec_markdown=updated_spec,
                done=False,
                draft_doctype=None,
                warnings=errors,
            )

    # Belt-and-suspenders: even if a field-type error slips past _validate_draft,
    # constructing DocTypeCreate can still raise (e.g. pydantic.ValidationError, which
    # is NOT a ValueError in Pydantic v2). Never let that escape as a 500; done=True is
    # only returned with a successfully-constructed DocTypeCreate.
    try:
        doctype = DocTypeCreate(**draft)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, surface as a warning
        return AssistResponse(
            questions=[],
            updated_spec_markdown=updated_spec,
            done=False,
            draft_doctype=None,
            warnings=[f"draft_doctype failed schema construction: {exc}"],
        )

    return AssistResponse(
        questions=[],
        updated_spec_markdown=updated_spec,
        done=True,
        draft_doctype=doctype,
        warnings=[],
    )


__all__ = [
    "run_assist_turn",
    "_build_context_block",
    "_build_llm_messages",
    "_call_llm",
]
