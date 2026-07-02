"""Admin overview aggregate endpoint (offline: mock engines/providers)."""

from fastapi.testclient import TestClient

from app.main import app

from .conftest import SAMPLES


def test_overview_aggregates():
    with TestClient(app) as client:
        # Baseline (seeded engines/doc-types exist from lifespan).
        base = client.get("/overview").json()
        assert base["engines_enabled"] >= 1
        assert base["doc_types"] >= 1

        # Ingest + structure one invoice, then correct a field.
        with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
            doc_id = client.post(
                "/documents", files={"file": ("invoice-clean.pdf", fh)}
            ).json()["id"]
        client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
        client.post(
            f"/documents/{doc_id}/structure",
            params={"doc_type": "invoice", "provider": "mock", "ocr_engine": "mock"},
        )
        client.patch(
            f"/documents/{doc_id}/structure/field",
            json={"path": "invoice_no", "value": "INV-1"},
        )

        stats = client.get("/overview").json()
        assert stats["documents_total"] == base["documents_total"] + 1
        assert sum(stats["documents_by_status"].values()) == stats["documents_total"]
        assert stats["corrections_total"] >= 1
        assert stats["corrected_documents"] >= 1
        assert stats["avg_extraction_confidence"] is not None
