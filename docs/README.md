# Documentation

Project documentation for the Document Auto-Approval System.

| Doc | What's in it |
| --- | --- |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | How it's built — the pipeline, swappable OCR/doc-type/rule layers, structuring & corrections, the data model, and the frontend. |
| [API.md](./API.md) | REST reference — every endpoint grouped by router. |
| [ROADMAP.md](./ROADMAP.md) | What's shipped, the recent work log, and the backlog. |
| [validation-rules.md](./validation-rules.md) | **Validation rules reference** — the catalogue of every rule primitive, the sandboxed expression DSL, and how to add a new one. |
| [VALIDATION-BRAINSTORM.md](./VALIDATION-BRAINSTORM.md) | The design rationale behind the validation model, plus the shipped/deferred status and the cross-document roadmap. |

**Deep dives (feature-level):**

| Doc | What's in it |
| --- | --- |
| [multi-document-cases.md](./multi-document-cases.md) | **Multi-document cases** — the Case entity, classify → reconcile → decide across N documents, and the design/phase plan behind it. |
| [document-generation.md](./document-generation.md) | **Document generation from templates** — turn an extraction into a filled DOCX/PDF; the two modes (form-fill / rich-HTML), the AI authoring agent, vision Fidelity QA, revision history, the data model + endpoints, and the honest TipTap-flattening limitation. |
| [large-document-extraction.md](./large-document-extraction.md) | **Extraction accuracy on long docs** — proximity grounding, section-aware extraction, cross-section list dedup, and the whole-document grounding fallback. |
| [signature-extraction.md](./signature-extraction.md) | **Signature detection** — the YOLOv8-ONNX best-effort spatial post-pass, its config, weights delivery, and measured accuracy. |
| [digital-signing.md](./digital-signing.md) | **Outbound digital signing (PAdES)** — sealing an **approved** document *or* a **generated** template output with a real X.509 signature + validation; the **visible** stamp placed at the template's signature marker (or a corner); the `pyhanko`/`mock` providers, the sign/validate endpoints, the `SignaturePanel` / `OutputSigner` UI, the `SIGNING_*` config, and the demo custody model + security notes. |

Start with the [root README](../README.md) for the pitch, setup, and running the app.

> **Code intelligence.** This repo is also indexed by GitNexus; `CLAUDE.md` and
> `.claude/skills/gitnexus/` describe how to query the code graph (impact analysis,
> execution flows). That's an agent-assist layer, separate from the product docs here.
