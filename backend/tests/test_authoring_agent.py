"""Phase 3 (authoring-agent) Waves 2+3 tests. Offline: ``provider=mock`` only.

The mock provider is deterministic and content-blind (mirrors the decision mock's
always-approve), so these tests exercise the whole SSE stream + tool-execution +
revision-persist path without a network call or an OPENROUTER_API_KEY.
"""

import json

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.generation import field_catalogue, render_field_placeholder
from app.pipeline.generation.authoring_agent import _execute_tool, _MOCK_CSS, run_authoring_agent
from app.schemas import AgentRequest


# --- helpers ------------------------------------------------------------------


def _create_template(client: TestClient, doc_type: str = "invoice") -> str:
    resp = client.post("/templates", json={"name": "Agent T", "doc_type": doc_type})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _put_body(client: TestClient, tid: str, html: str) -> None:
    resp = client.put(f"/templates/{tid}", json={"html_body": html})
    assert resp.status_code == 200, resp.text


def _events(client: TestClient, tid: str, message: str, provider: str = "mock") -> list[dict]:
    with client.stream(
        "POST", f"/templates/{tid}/agent", json={"message": message, "provider": provider}
    ) as resp:
        assert resp.status_code == 200, resp.text
        return [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]


# --- SSE integration (mock) ---------------------------------------------------


def test_agent_stream_mock_restyles_and_persists():
    with TestClient(app) as client:
        tid = _create_template(client)
        _put_body(client, tid, "<h1>Invoice</h1><p>Body</p>")
        before = len(client.get(f"/templates/{tid}/revisions").json())

        events = _events(client, tid, "make it fancy")
        types = [e["type"] for e in events]

        # token(s) precede the tools; the two tool rounds land in order; ends with done.
        assert "token" in types
        assert types[-1] == "done"
        css_call = next(e for e in events if e["type"] == "tool_call" and e["tool_name"] == "set_css")
        assert types.index("tool_call") < types.index("tool_result")
        css_event = next(e for e in events if e["type"] == "css")
        assert css_event["css"] == _MOCK_CSS
        assert css_event.get("revision_id")
        # The set_css tool_result reports success before the css payload event.
        css_result = next(
            e for e in events if e["type"] == "tool_result" and e["tool_name"] == "set_css"
        )
        assert css_result["ok"] is True
        # A second tool round inserts a placeholder for the first catalogue field.
        ph_call = next(
            e for e in events if e["type"] == "tool_call" and e["tool_name"] == "insert_placeholder"
        )
        assert ph_call is not None and css_call is not None
        ph_result = next(
            e for e in events if e["type"] == "tool_result" and e["tool_name"] == "insert_placeholder"
        )
        assert ph_result["ok"] is True

        # The mock's fixed CSS was actually persisted, and it created a revision.
        assert client.get(f"/templates/{tid}").json()["css"] == _MOCK_CSS
        after = len(client.get(f"/templates/{tid}/revisions").json())
        assert after > before


def test_agent_stream_full_type_sequence():
    """The mock emits a stable token…/set_css/css/insert_placeholder/done sequence."""
    with TestClient(app) as client:
        tid = _create_template(client)
        _put_body(client, tid, "<h1>Invoice</h1>")
        types = [e["type"] for e in _events(client, tid, "hi")]

        # Relative ordering of the meaningful milestones.
        for earlier, later in [
            ("token", "css"),
            ("css", "done"),
        ]:
            assert types.index(earlier) < types.index(later)
        assert types.count("tool_call") == 2
        assert types.count("tool_result") == 2


# --- unit: the hallucinated-field-path guard ----------------------------------


def test_insert_placeholder_rejects_unknown_field():
    result = _execute_tool(
        "insert_placeholder", {"field_path": "nonexistent.xyz"}, "tid", "invoice"
    )
    assert result["ok"] is False
    assert "unknown field" in result["error"]


def test_insert_placeholder_returns_exact_markup_for_valid_path():
    entry = field_catalogue("invoice")[0]
    result = _execute_tool(
        "insert_placeholder", {"field_path": entry.path}, "tid", "invoice"
    )
    assert result["ok"] is True
    assert result["markup"] == render_field_placeholder(entry.path, entry.label, entry.kind)


# --- unit: provider resolution -------------------------------------------------


def test_unknown_provider_raises():
    with TestClient(app) as client:
        tid = _create_template(client)
    try:
        run_authoring_agent(tid, AgentRequest(message="x"), provider="nope")
    except ValueError as exc:
        assert "Unknown authoring provider" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for an unknown provider")


def test_agent_route_unknown_provider_400():
    with TestClient(app) as client:
        tid = _create_template(client)
        resp = client.post(f"/templates/{tid}/agent", json={"message": "x", "provider": "nope"})
        assert resp.status_code == 400, resp.text
        assert "Unknown authoring provider" in resp.json()["detail"]


def test_agent_route_missing_template_404():
    with TestClient(app) as client:
        resp = client.post("/templates/missing/agent", json={"message": "x", "provider": "mock"})
        assert resp.status_code == 404, resp.text
