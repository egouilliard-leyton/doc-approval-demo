"""Evaluation harness API tests (offline: mock engine/provider, no network).

Mirrors tests/test_overview.py + tests/test_doc_types_api.py TestClient style.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_list_goldens():
    with TestClient(app) as client:
        resp = client.get("/eval/goldens")
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) >= 4
        by_id = {r["id"]: r for r in rows}
        assert {"invoice-clean", "invoice-mismatch", "contract-standard", "mock-baseline"} <= set(by_id)
        mb = by_id["mock-baseline"]
        assert mb["doc_type"] == "invoice"
        assert mb["field_count"] >= 1 and mb["collection_count"] >= 1


def test_get_golden_detail_and_404():
    with TestClient(app) as client:
        got = client.get("/eval/goldens/mock-baseline")
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["expected_fields"]["vendor"] == "MOCK INVOICE"
        assert "line_items" in body["expected_collections"]

        assert client.get("/eval/goldens/nope").status_code == 404


def test_run_and_list_and_get():
    with TestClient(app) as client:
        run = client.post(
            "/eval/run",
            json={"golden_id": "mock-baseline", "engine": "mock", "provider": "mock"},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["overall_score"] == 1.0
        assert body["golden_id"] == "mock-baseline"
        assert body["doc_type"] == "invoice"
        assert isinstance(body["field_scores"], list) and body["field_scores"]
        assert "line_items" in body["collection_scores"]
        run_id = body["id"]

        # The run shows up in the list, filtered by golden.
        runs = client.get("/eval/runs", params={"golden_id": "mock-baseline"})
        assert runs.status_code == 200, runs.text
        assert any(r["id"] == run_id for r in runs.json())

        # And is fetchable in full detail.
        got = client.get(f"/eval/runs/{run_id}")
        assert got.status_code == 200, got.text
        assert got.json()["overall_score"] == 1.0


def test_run_unknown_golden_404():
    with TestClient(app) as client:
        resp = client.post("/eval/run", json={"golden_id": "does-not-exist"})
        assert resp.status_code == 404, resp.text


def test_run_with_unknown_document_404():
    with TestClient(app) as client:
        resp = client.post(
            "/eval/run",
            json={"golden_id": "mock-baseline", "document_id": "no-such-doc"},
        )
        assert resp.status_code == 404, resp.text


def test_get_unknown_run_404():
    with TestClient(app) as client:
        assert client.get("/eval/runs/nope").status_code == 404
