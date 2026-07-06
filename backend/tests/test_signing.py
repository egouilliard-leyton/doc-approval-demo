"""Phase 6 outbound signing tests. Use the offline mock provider — no pyhanko dep.

The mock provider appends a plain-text marker instead of a real CMS signature, so
the whole sign/validate/gate round-trip runs offline. A single guarded smoke test
exercises the real pyhanko path when the ``signing`` extra is installed.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import storage
from app.config import settings
from app.db import engine
from app.models import Document, PipelineRun
from app.pipeline.signing import run_signing, sign_pdf_bytes, validate_document_signature
from app.pipeline.signing import mock as mock_signing

from .conftest import SAMPLES
from .test_smoke_e2e import _stash_structured_doc
from app.main import app


# --- helpers ------------------------------------------------------------------


def _upload(client: TestClient, name: str, doc_type: str | None = None) -> str:
    data = {"doc_type": doc_type} if doc_type else None
    with (SAMPLES / name).open("rb") as fh:
        resp = client.post("/documents", files={"file": (name, fh)}, data=data)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _ocr(client: TestClient, doc_id: str) -> None:
    assert client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"}).status_code == 200


def _structure(client: TestClient, doc_id: str, doc_type: str = "invoice") -> None:
    resp = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": doc_type, "provider": "mock", "ocr_engine": "mock"},
    )
    assert resp.status_code == 200, resp.text


def _decide(client: TestClient, doc_id: str, provider: str = "mock") -> dict:
    resp = client.post(f"/documents/{doc_id}/decide", params={"provider": provider})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _uniquify_invoice_no(doc_id: str) -> None:
    """Give this doc a unique invoice_no in its persisted structure before deciding.

    The mock structurer emits a constant invoice_no, so the second invoice decided in
    the shared test DB would flag as a duplicate (a hard rule). Signing only needs an
    ``approve``, so we make each doc's number unique to keep that rule out of the way.
    """
    with Session(engine) as session:
        run = session.exec(
            select(PipelineRun)
            .where(PipelineRun.document_id == doc_id)
            .order_by(PipelineRun.created_at.desc())
        ).first()
        structure = dict(run.stage_results["structure"])
        fields = dict(structure["fields"])
        node = dict(fields["invoice_no"])
        node["value"] = f"INV-{uuid4()}"
        fields["invoice_no"] = node
        structure["fields"] = fields
        run.stage_results = {**run.stage_results, "structure": structure}
        session.add(run)
        session.commit()


def _approved_pdf(client: TestClient) -> str:
    """Upload invoice-clean.pdf and run it through to an approve decision."""
    doc_id = _upload(client, "invoice-clean.pdf")
    _ocr(client, doc_id)
    _structure(client, doc_id)
    _uniquify_invoice_no(doc_id)
    decision = _decide(client, doc_id)
    assert decision["decision"] == "approve", decision
    return doc_id


# --- route tests: happy path --------------------------------------------------


def test_sign_route_signs_approved_invoice():
    with TestClient(app) as client:
        doc_id = _approved_pdf(client)

        post = client.post(f"/documents/{doc_id}/sign", params={"provider": "mock"})
        assert post.status_code == 200, post.text
        result = post.json()
        assert result["status"] == "signed"
        assert result["provider"] == "mock"
        assert result["signed_pdf_url"], "expected a signed PDF url"
        assert result["validation"]["valid"] is True
        assert result["validation"]["intact"] is True
        assert result["validation"]["trusted"] is True

        detail = client.get(f"/documents/{doc_id}").json()
        assert detail["status"] == "signed"


def test_sign_get_refetch():
    with TestClient(app) as client:
        doc_id = _approved_pdf(client)
        post = client.post(f"/documents/{doc_id}/sign", params={"provider": "mock"}).json()

        got = client.get(f"/documents/{doc_id}/sign")
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["signed_pdf_url"] == post["signed_pdf_url"]
        assert body["validation"]["valid"] == post["validation"]["valid"]


def test_validate_signature_after_signing():
    with TestClient(app) as client:
        doc_id = _approved_pdf(client)
        client.post(f"/documents/{doc_id}/sign", params={"provider": "mock"})

        resp = client.post(
            f"/documents/{doc_id}/validate-signature", params={"provider": "mock"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["valid"] is True


def test_redecide_invalidates_prior_signature():
    """Re-running /decide must invalidate a signature made from the old decision.

    A signed PDF is a real cryptographic attestation of an approval; it must not
    survive a re-decision. After signing, re-deciding drops the persisted ``sign``
    result (GET -> 404) and deletes the on-disk signed PDF, and the doc leaves the
    ``signed`` state. A fresh signature must be re-run.
    """
    with TestClient(app) as client:
        doc_id = _approved_pdf(client)
        sign = client.post(f"/documents/{doc_id}/sign", params={"provider": "mock"}).json()
        assert client.get(f"/documents/{doc_id}/sign").status_code == 200
        assert client.get(f"/files/{doc_id}/signed/signed.pdf").status_code == 200

        # Re-decide (still approve) — the stale seal must be cleared regardless.
        _decide(client, doc_id)

        assert client.get(f"/documents/{doc_id}/sign").status_code == 404
        assert client.get(f"/files/{doc_id}/signed/signed.pdf").status_code == 404
        detail = client.get(f"/documents/{doc_id}").json()
        assert detail["status"] != "signed"
        # Re-signing works again afterwards.
        again = client.post(f"/documents/{doc_id}/sign", params={"provider": "mock"})
        assert again.status_code == 200, again.text
        assert again.json()["signed_pdf_url"] == sign["signed_pdf_url"]


# --- route tests: gating + errors ---------------------------------------------


def test_sign_before_decide_409():
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")
        _ocr(client, doc_id)
        _structure(client, doc_id)  # decide deliberately skipped
        resp = client.post(f"/documents/{doc_id}/sign", params={"provider": "mock"})
        assert resp.status_code == 409, resp.text


def test_sign_non_pdf_400():
    """The mime guard runs before the decide check, so a non-PDF is a 400 regardless."""
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-gen.jpg")
        resp = client.post(f"/documents/{doc_id}/sign", params={"provider": "mock"})
        assert resp.status_code == 400, resp.text
        assert "requires a PDF" in resp.json()["detail"]


def test_sign_unknown_provider_400():
    with TestClient(app) as client:
        doc_id = _approved_pdf(client)
        resp = client.post(f"/documents/{doc_id}/sign", params={"provider": "nope"})
        assert resp.status_code == 400, resp.text
        assert "Unknown signing provider" in resp.json()["detail"]


def test_sign_missing_document_404():
    with TestClient(app) as client:
        assert client.post(
            "/documents/missing/sign", params={"provider": "mock"}
        ).status_code == 404
        assert client.get("/documents/missing/sign").status_code == 404
        assert client.post(
            "/documents/missing/validate-signature", params={"provider": "mock"}
        ).status_code == 404


# --- unit tests ---------------------------------------------------------------


def test_run_signing_rejects_non_pdf():
    doc = Document(filename="t.jpg", mime="image/jpeg")
    with pytest.raises(ValueError):
        run_signing(doc, "mock")


def test_mock_validate_unsigned_reports_invalid():
    validation = mock_signing.validate(b"%PDF-1.4 unsigned bytes")
    assert validation.valid is False
    assert validation.intact is False
    assert validation.trusted is False


def test_validate_document_signature_unsigned_reports_invalid():
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")  # uploaded but never signed
        doc = Document(id=doc_id, filename="invoice-clean.pdf", mime="application/pdf")
        validation = validate_document_signature(doc, "mock")
        assert validation.valid is False


# --- real path smoke (guarded: runs iff the pyhanko extra is installed) --------


def test_pyhanko_real_signature_smoke():
    pytest.importorskip("pyhanko")
    with TestClient(app) as client:
        doc_id = _approved_pdf(client)
        # Go through the entrypoint on the real provider; the doc is on disk via upload.
        doc = Document(id=doc_id, filename="invoice-clean.pdf", mime="application/pdf")
        result = run_signing(doc, "pyhanko")

        assert result.provider == "pyhanko"
        assert result.status.value == "signed"
        assert result.validation.valid is True
        assert result.validation.intact is True
        assert result.validation.trusted is True
        assert result.validation.signer is not None
        assert result.validation.signer.common_name == settings.signing_signer_name


# --- generated-output signing (outbound: sign a template's generated PDF) ------


def _rich_html_pdf_output(client: TestClient) -> tuple[str, str]:
    """Create a rich-html invoice template + generate a PDF from a stashed doc.

    Mirrors ``test_smoke_e2e.test_smoke_rich_html_journey``. Returns
    ``(template_id, output_id)`` where the output is a real PDF on disk.
    """
    tid = client.post(
        "/templates", json={"name": "Sign-Me Letter", "doc_type": "invoice"}
    ).json()["id"]
    html = '<p>Invoice for <span data-field="vendor" data-field-kind="text">Vendor</span></p>'
    put = client.put(
        f"/templates/{tid}", json={"html_body": html, "output_formats": ["pdf"]}
    )
    assert put.status_code == 200, put.text
    doc_id = _stash_structured_doc()
    gen = client.post(f"/templates/{tid}/generate", params={"document_id": doc_id})
    assert gen.status_code == 201, gen.text
    return tid, gen.json()["output_id"]


def test_sign_generated_output_signs_pdf():
    with TestClient(app) as client:
        tid, oid = _rich_html_pdf_output(client)

        resp = client.post(
            f"/templates/{tid}/outputs/{oid}/sign", params={"provider": "mock"}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["provider"] == "mock"
        assert body["template_id"] == tid
        assert body["output_id"] == oid
        assert body["signed_output_id"] == f"{oid}-signed"
        assert body["signed_output_url"], "expected a signed output url"
        assert body["signed_output_url"].endswith("-signed.pdf")
        assert body["validation"]["valid"] is True
        assert body["validation"]["intact"] is True
        assert body["validation"]["trusted"] is True


def test_signed_generated_output_is_downloadable():
    """The <output_id>-signed.pdf is fetchable through the /files static mount."""
    with TestClient(app) as client:
        tid, oid = _rich_html_pdf_output(client)
        client.post(f"/templates/{tid}/outputs/{oid}/sign", params={"provider": "mock"})

        got = client.get(f"/files/templates/{tid}/outputs/{oid}-signed.pdf")
        assert got.status_code == 200, got.text
        assert got.content[:4] == b"%PDF"


def test_sign_generated_output_missing_output_404():
    with TestClient(app) as client:
        tid, _ = _rich_html_pdf_output(client)
        resp = client.post(
            f"/templates/{tid}/outputs/does-not-exist/sign", params={"provider": "mock"}
        )
        assert resp.status_code == 404, resp.text


def test_sign_generated_output_missing_template_404():
    with TestClient(app) as client:
        resp = client.post(
            "/templates/no-such-template/outputs/whatever/sign",
            params={"provider": "mock"},
        )
        assert resp.status_code == 404, resp.text


def test_sign_generated_output_unknown_provider_400():
    with TestClient(app) as client:
        tid, oid = _rich_html_pdf_output(client)
        resp = client.post(
            f"/templates/{tid}/outputs/{oid}/sign", params={"provider": "nope"}
        )
        assert resp.status_code == 400, resp.text


# --- unit test on the shared core (sign_pdf_bytes) ----------------------------


def test_sign_pdf_bytes_mock_roundtrip():
    """The shared core signs real PDF bytes and self-validates all-True (mock)."""
    pdf_bytes = (SAMPLES / "invoice-clean.pdf").read_bytes()
    signed_bytes, validation, engine_version, latency_ms = sign_pdf_bytes(
        pdf_bytes, "mock"
    )
    assert validation.valid is True
    assert validation.intact is True
    assert validation.trusted is True
    assert engine_version == "mock"
    assert latency_ms >= 0
    assert signed_bytes.startswith(b"%PDF")
    # The freshly signed bytes carry a marker the mock validator recognises.
    revalidated = mock_signing.validate(signed_bytes)
    assert revalidated.valid is True
    assert revalidated.intact is True
    assert revalidated.trusted is True


def test_sign_arbitrary_bytes_then_mock_validate():
    """Signing arbitrary (non-signed) bytes then mock-validating reflects intact/trusted."""
    signed_bytes, _, _, _ = sign_pdf_bytes(b"not really a pdf", "mock")
    revalidated = mock_signing.validate(signed_bytes)
    assert revalidated.intact is True
    assert revalidated.trusted is True
    # Un-signed bytes on their own validate as invalid.
    assert mock_signing.validate(b"not really a pdf").valid is False


# --- real-path smoke (guarded: runs iff the pyhanko extra is installed) --------


def test_pyhanko_real_generated_output_signature_smoke():
    pytest.importorskip("pyhanko")
    with TestClient(app) as client:
        tid, oid = _rich_html_pdf_output(client)

        # Default provider (SIGNING_PROVIDER defaults to pyhanko) => the real path.
        resp = client.post(f"/templates/{tid}/outputs/{oid}/sign")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["provider"] == "pyhanko"
        assert body["validation"]["valid"] is True
        assert body["validation"]["intact"] is True
        assert body["validation"]["trusted"] is True
        assert body["validation"]["signer"] is not None
        assert body["validation"]["signer"]["common_name"] == settings.signing_signer_name

        # The written signed file is a genuine CMS-bearing PDF, not a mock marker.
        signed = storage.template_outputs_dir(tid) / f"{oid}-signed.pdf"
        assert signed.is_file()
        raw = signed.read_bytes()
        assert b"/ByteRange" in raw
        assert b"adbe.pkcs7.detached" in raw
