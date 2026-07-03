"""Black-box extraction endpoint tests (Track 1).

Fully offline: the mock OCR engine + mock structuring/decision providers, and the
offline heuristic classifier. Mirrors tests/test_eval_routes.py (TestClient) +
tests/test_ingest.py (multipart uploads). Assertions are scoped to each test's own
``document_id`` because the suite shares one DB that accumulates rows.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import SAMPLES

_MOCK = {
    "ocr_engine": "mock",
    "structuring_provider": "mock",
    "decision_provider": "mock",
}


def _post_extract(client: TestClient, sample: str, **data) -> "object":
    with (SAMPLES / sample).open("rb") as fh:
        return client.post("/extract", files={"file": (sample, fh)}, data=data)


def test_full_run_with_explicit_doc_type():
    with TestClient(app) as client:
        resp = _post_extract(client, "invoice-clean.pdf", doc_type="invoice", **_MOCK)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["document_id"]
        assert body["doc_type"] == "invoice"
        # Explicit doc_type -> no auto-classify step.
        assert body["classify"] is None
        assert body["prescan"] is not None  # run_prescan defaults to True

        total = (body["structured"]["fields"].get("total") or {}).get("value")
        assert total == 1234.56, body["structured"]["fields"]
        assert body["decision"]["decision"] in {"approve", "flag", "needs_review"}


def test_auto_classify_when_doc_type_omitted():
    with TestClient(app) as client:
        # Omit doc_type -> the offline heuristic classifier resolves it.
        resp = _post_extract(client, "invoice-clean.pdf", **_MOCK)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["classify"] is not None
        resolved = body["classify"]["doc_type"]
        assert resolved is not None
        assert body["doc_type"] == resolved
        assert body["structured"]["doc_type"] == resolved
        assert any("auto-classified" in w for w in body["warnings"])


def test_unknown_doc_type_override_422():
    with TestClient(app) as client:
        resp = _post_extract(client, "invoice-clean.pdf", doc_type="not-a-real-type", **_MOCK)
        assert resp.status_code == 422, resp.text


def test_run_prescan_false_skips_prescan_but_still_decides():
    with TestClient(app) as client:
        resp = _post_extract(
            client, "invoice-clean.pdf", doc_type="invoice", run_prescan="false", **_MOCK
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["prescan"] is None
        assert body["decision"]["decision"] in {"approve", "flag", "needs_review"}
        assert (body["structured"]["fields"].get("total") or {}).get("value") == 1234.56


def test_persisted_and_queryable_afterward():
    with TestClient(app) as client:
        resp = _post_extract(client, "invoice-clean.pdf", doc_type="invoice", **_MOCK)
        assert resp.status_code == 200, resp.text
        doc_id = resp.json()["document_id"]

        # The document persisted like any staged upload.
        detail = client.get(f"/documents/{doc_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["id"] == doc_id

        # The review queue scans persisted structure results without erroring.
        rq = client.get("/review-queue")
        assert rq.status_code == 200, rq.text


def test_batch_mixed_good_and_bad():
    with TestClient(app) as client:
        with (SAMPLES / "invoice-clean.pdf").open("rb") as good:
            resp = client.post(
                "/extract/batch",
                files=[
                    ("files", ("invoice-clean.pdf", good.read(), "application/pdf")),
                    # A .pdf that isn't a real PDF -> normalize_to_pages fails -> 422.
                    ("files", ("broken.pdf", b"not a real pdf", "application/pdf")),
                ],
                data={"doc_type": "invoice", **_MOCK},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["succeeded"] == 1, body
        assert body["failed"] == 1, body

        by_name = {it["filename"]: it for it in body["items"]}
        good_item = by_name["invoice-clean.pdf"]
        assert good_item["result"] is not None
        assert good_item["document_id"]
        assert good_item["error"] is None

        bad_item = by_name["broken.pdf"]
        assert bad_item["result"] is None
        assert bad_item["error"]
        assert bad_item["error_status"] == 422
