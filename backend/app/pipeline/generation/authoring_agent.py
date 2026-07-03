"""Phase 3 (authoring-agent) Waves 2+3: the tool-calling engine that edits a template.

Two providers behind one entrypoint, mirroring ``agent.py`` / ``mapper.py``:

* ``llm`` — a streaming, tool-calling OpenRouter loop (OpenAI-compatible client), imported
  lazily so the app boots and tests run without the optional ``openai`` dep. The model can
  only see the template's HTML/CSS *text* (never a render), so it works from the source and
  writes back the COMPLETE document body/stylesheet via the ``set_html``/``set_css`` tools.
* ``mock`` — a deterministic, content-blind script (mirrors ``agent.py``'s always-approve
  mock): it re-styles the CSS and inserts one placeholder so the offline tests exercise the
  whole stream + tool-execution + revision-persist path without a network call.

The engine is a synchronous generator of :class:`AgentEvent` (the SSE route runs it in a
threadpool). Every tool execution opens its OWN ``Session(engine)`` — never the request
session, which FastAPI tears down before the stream drains — and persists through the shared
:func:`apply_template_update` so each write snapshots a revertible :class:`TemplateRevision`.
Graceful degradation everywhere: any LLM error becomes an ``error`` event and the stream
always ends with a ``done`` event; it never raises into the response.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import DocType, Template, TemplateMode, TemplateRevision
from app.schemas import AgentEvent, AgentRequest, TemplateUpdate

from .binder import render_field_placeholder
from .catalogue import field_catalogue
from .qa import run_template_qa
from .template_edits import apply_template_update

PROVIDERS = {"llm", "mock"}

# OpenAI/OpenRouter function-tool schemas. The two ``set_*`` tools MUST always carry the
# complete document (the model can't see a render, so a fragment would silently truncate).
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "set_html",
            "description": (
                "Replace the template's document body with new HTML. Always pass the "
                "COMPLETE body HTML, never a fragment — it wholesale-replaces the body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "html": {
                        "type": "string",
                        "description": "The COMPLETE document body HTML.",
                    },
                    "note": {"type": "string", "description": "Optional edit note."},
                },
                "required": ["html"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_css",
            "description": (
                "Replace the template's stylesheet. Always pass the COMPLETE stylesheet, "
                "never a fragment — it wholesale-replaces the CSS."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "css": {
                        "type": "string",
                        "description": "The COMPLETE stylesheet.",
                    },
                    "note": {"type": "string", "description": "Optional edit note."},
                },
                "required": ["css"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_placeholder",
            "description": (
                "Return the canonical span markup for a bindable field placeholder. Does "
                "NOT mutate the template — paste the returned markup into a set_html call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "field_path": {
                        "type": "string",
                        "description": "A dotted catalogue path (from list_available_fields).",
                    },
                    "label": {
                        "type": "string",
                        "description": "Optional visible label; defaults to the catalogue label.",
                    },
                },
                "required": ["field_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_available_fields",
            "description": "List every bindable field path (with label + kind) for this doc type.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_preview",
            "description": (
                "Render the current template to page images and get a vision-based fidelity "
                "critique of your own work. Use after making visual edits to check them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instructions": {
                        "type": "string",
                        "description": "Optional extra guidance for the reviewer.",
                    },
                    "provider": {
                        "type": "string",
                        "description": "Optional QA vision provider override.",
                    },
                },
            },
        },
    },
]


def run_authoring_agent(
    template_id: str, request: AgentRequest, provider: str = ""
) -> Iterator[AgentEvent]:
    """Stream the authoring agent's response for one user message.

    Resolves the provider (explicit arg else ``settings.agent_authoring_provider``) and
    raises :class:`ValueError` on an unknown one (the route maps that to 400). Dispatches to
    the offline ``mock`` script or the streaming ``llm`` tool-calling loop. Yields
    :class:`AgentEvent` items; a synchronous generator so it can be driven in a threadpool.
    """
    provider = provider or settings.agent_authoring_provider
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown authoring provider '{provider}'. Available: {', '.join(sorted(PROVIDERS))}"
        )

    # Read the template's current state FRESH (the request session is gone once we stream).
    with Session(engine) as session:
        tmpl = session.get(Template, template_id)
        if tmpl is None:
            raise ValueError(f"Template '{template_id}' not found.")
        doc_type = tmpl.doc_type
        html_body = tmpl.html_body
        css = tmpl.css

    if provider == "mock":
        return _run_mock(template_id, doc_type)
    return _run_llm(template_id, request, doc_type, html_body, css)


# --- tool execution -----------------------------------------------------------


def _newest_revision_id(session: Session, template_id: str) -> str | None:
    """The id of the just-written revision (newest snapshot for this template)."""
    rev = session.exec(
        select(TemplateRevision)
        .where(TemplateRevision.template_id == template_id)
        .order_by(TemplateRevision.created_at.desc())
    ).first()
    return rev.id if rev else None


def _execute_tool(name: str, args: dict, template_id: str, doc_type: DocType) -> dict:
    """Run one tool by name, each opening its OWN session; never raises to the caller.

    Returns a JSON-serializable result dict always carrying ``ok``; ``set_html``/``set_css``
    add ``html``/``css`` + ``revision_id`` on success, ``insert_placeholder`` adds ``markup``,
    ``list_available_fields`` adds ``fields``. A bad tool name or bad args -> ``ok=False``.
    """
    if name == "set_html":
        html = args.get("html")
        if not isinstance(html, str) or not html.strip():
            return {"ok": False, "error": "set_html requires non-empty html"}
        try:
            from bs4 import BeautifulSoup  # lazy: optional docgen dep

            BeautifulSoup(html, "html.parser")
        except Exception as exc:  # noqa: BLE001 — unparseable body -> reject, don't persist
            return {"ok": False, "error": f"unparseable html: {exc}"}
        with Session(engine) as session:
            tmpl = session.get(Template, template_id)
            if tmpl is None:
                return {"ok": False, "error": "template not found"}
            tmpl = apply_template_update(
                session, tmpl, TemplateUpdate(html_body=html, revision_note="agent: set_html")
            )
            return {
                "ok": True,
                "revision_id": _newest_revision_id(session, template_id),
                "html": tmpl.html_body,
            }

    if name == "set_css":
        css = args.get("css")
        if not isinstance(css, str) or not css.strip():
            return {"ok": False, "error": "set_css requires non-empty css"}
        with Session(engine) as session:
            tmpl = session.get(Template, template_id)
            if tmpl is None:
                return {"ok": False, "error": "template not found"}
            tmpl = apply_template_update(
                session, tmpl, TemplateUpdate(css=css, revision_note="agent: set_css")
            )
            return {
                "ok": True,
                "revision_id": _newest_revision_id(session, template_id),
                "css": tmpl.css,
            }

    if name == "insert_placeholder":
        field_path = args.get("field_path")
        catalogue = field_catalogue(doc_type)
        entry = next((e for e in catalogue if e.path == field_path), None)
        if entry is None:  # hallucinated path -> reject (mapper.py-style guard)
            return {"ok": False, "error": f"unknown field '{field_path}'"}
        label = args.get("label") or entry.label
        return {"ok": True, "markup": render_field_placeholder(entry.path, label, entry.kind)}

    if name == "list_available_fields":
        fields = [
            {"path": e.path, "label": e.label, "kind": e.kind}
            for e in field_catalogue(doc_type)
        ]
        return {"ok": True, "fields": fields}

    if name == "render_preview":
        with Session(engine) as session:
            tmpl = session.get(Template, template_id)
            if tmpl is None:
                return {"ok": False, "error": "template not found"}
            if tmpl.mode != TemplateMode.rich_html or not tmpl.html_body:
                return {"ok": False, "error": "no HTML body to preview"}
            report = run_template_qa(
                tmpl,
                document_id=None,
                structured_fields=None,
                provider=args.get("provider", ""),
                instructions=args.get("instructions"),
            )
        return {
            "ok": True,
            "summary": report.summary,
            "findings": [f.model_dump() for f in report.findings],
        }

    return {"ok": False, "error": f"unknown tool '{name}'"}


# --- mock provider ------------------------------------------------------------


_MOCK_CSS = "body{font-family:Georgia,serif} h1{color:navy}"


def _run_mock(template_id: str, doc_type: DocType) -> Iterator[AgentEvent]:
    """Deterministic, content-blind script (mirrors ``agent.py``'s always-approve mock).

    Restyles the CSS with a fixed stylesheet and inserts a placeholder for the doc type's
    first catalogue field (always valid), emitting the full token/tool_call/tool_result/
    css event sequence so the offline tests exercise the whole stream + persist path.
    """
    yield AgentEvent(type="token", text="Sure — ")
    yield AgentEvent(type="token", text="I'll adjust the styling.")

    # 1. Restyle via set_css (persists a revision).
    css_args = {"css": _MOCK_CSS}
    yield AgentEvent(type="tool_call", tool_name="set_css", tool_args=css_args)
    css_result = _execute_tool("set_css", css_args, template_id, doc_type)
    yield AgentEvent(
        type="tool_result",
        tool_name="set_css",
        ok=css_result["ok"],
        detail=css_result.get("error"),
    )
    if css_result.get("css") is not None:
        yield AgentEvent(
            type="css", css=css_result["css"], revision_id=css_result.get("revision_id")
        )

    # 2. Offer a placeholder for the first (always-valid) catalogue field.
    catalogue = field_catalogue(doc_type)
    first_path = catalogue[0].path if catalogue else ""
    ph_args = {"field_path": first_path}
    yield AgentEvent(type="tool_call", tool_name="insert_placeholder", tool_args=ph_args)
    ph_result = _execute_tool("insert_placeholder", ph_args, template_id, doc_type)
    yield AgentEvent(
        type="tool_result",
        tool_name="insert_placeholder",
        ok=ph_result["ok"],
        detail=ph_result.get("error"),
    )

    yield AgentEvent(type="token", text=" Done — restyled and added a field placeholder.")
    yield AgentEvent(type="done")


# --- llm provider -------------------------------------------------------------


def _system_prompt(
    doc_type: DocType, html_body: str | None, css: str | None
) -> str:
    """Compact system prompt: catalogue summary + the CURRENT html/css + hard rules."""
    catalogue = field_catalogue(doc_type)
    catalogue_lines = "\n".join(f"- {e.path} — {e.label}" for e in catalogue)
    return (
        f"You are a document template author for {getattr(doc_type, 'value', doc_type)} "
        "documents. You edit the template's HTML body and CSS on request using the provided "
        "tools.\n\n"
        "IMPORTANT rules:\n"
        "- You can call `render_preview` to render the current template and get a vision "
        "critique of your own work. Use it after making visual edits to check them.\n"
        "- set_html and set_css must ALWAYS carry the COMPLETE document, never a fragment — "
        "they wholesale-replace the body/stylesheet.\n"
        "- Only bind field paths that appear in the catalogue below; use "
        "insert_placeholder to get the canonical markup, then embed it in your set_html.\n\n"
        f"Bindable fields:\n{catalogue_lines}\n\n"
        f"CURRENT HTML body:\n{html_body or '(empty)'}\n\n"
        f"CURRENT CSS:\n{css or '(empty)'}"
    )


def _run_llm(
    template_id: str,
    request: AgentRequest,
    doc_type: DocType,
    html_body: str | None,
    css: str | None,
) -> Iterator[AgentEvent]:
    """Streaming, tool-calling OpenRouter loop; degrades to an error+done on any failure.

    Buffers streamed tokens (emitted as ``token`` events), accumulates fragmented tool-call
    deltas, then — per round — announces each call (``tool_call``), executes it, emits the
    result (``tool_result`` plus ``html``/``css``), and appends exactly one ``tool`` message
    per call before the next model turn. Any exception ends the stream with error+done.
    """
    try:
        import openai  # lazy: optional dep

        messages: list[dict] = [
            {"role": "system", "content": _system_prompt(doc_type, html_body, css)}
        ]
        for turn in request.history:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": request.message})

        client = openai.OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.agent_authoring_base_url,
            timeout=settings.agent_authoring_timeout_s,
        )

        for _ in range(settings.agent_authoring_max_tool_iterations):
            stream = client.chat.completions.create(
                model=settings.agent_authoring_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                stream=True,
                temperature=0,
            )

            assistant_text = ""
            # index -> {"id", "name", "arguments"}; arguments arrive fragmented across chunks.
            tool_calls: dict[int, dict] = {}
            for chunk in stream:
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    assistant_text += delta.content
                    yield AgentEvent(type="token", text=delta.content)
                for tc in getattr(delta, "tool_calls", None) or []:
                    slot = tool_calls.setdefault(
                        tc.index, {"id": None, "name": "", "arguments": ""}
                    )
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

            if not tool_calls:
                messages.append({"role": "assistant", "content": assistant_text})
                yield AgentEvent(type="done")
                return

            # Reconstruct the assistant message that carries the tool calls.
            ordered = [tool_calls[i] for i in sorted(tool_calls)]
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_text or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {"name": call["name"], "arguments": call["arguments"]},
                        }
                        for call in ordered
                    ],
                }
            )

            for call in ordered:
                name = call["name"]
                try:
                    parsed_args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}
                    result = {"ok": False, "error": "invalid tool arguments"}
                    yield AgentEvent(type="tool_call", tool_name=name, tool_args=parsed_args)
                else:
                    yield AgentEvent(type="tool_call", tool_name=name, tool_args=parsed_args)
                    result = _execute_tool(name, parsed_args, template_id, doc_type)

                yield AgentEvent(
                    type="tool_result",
                    tool_name=name,
                    ok=result["ok"],
                    detail=result.get("error"),
                )
                if result.get("html") is not None:
                    yield AgentEvent(
                        type="html", html=result["html"], revision_id=result.get("revision_id")
                    )
                if result.get("css") is not None:
                    yield AgentEvent(
                        type="css", css=result["css"], revision_id=result.get("revision_id")
                    )

                # Exactly one tool response per call, or the next turn 400s.
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result),
                    }
                )

        # Max iterations exhausted without a final text turn.
        yield AgentEvent(
            type="error", message="authoring agent stopped after max tool iterations"
        )
        yield AgentEvent(type="done")
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never raise into the stream
        yield AgentEvent(type="error", message=str(exc))
        yield AgentEvent(type="done")
