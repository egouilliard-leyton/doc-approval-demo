# Documentation

Project documentation for the Document Auto-Approval System.

| Doc | What's in it |
| --- | --- |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | How it's built — the pipeline, swappable OCR/doc-type/rule layers, structuring & corrections, the data model, and the frontend. |
| [API.md](./API.md) | REST reference — every endpoint grouped by router. |
| [ROADMAP.md](./ROADMAP.md) | What's shipped, the recent work log, and the backlog. |
| [validation-rules.md](./validation-rules.md) | **Validation rules reference** — the catalogue of every rule primitive, the sandboxed expression DSL, and how to add a new one. |
| [VALIDATION-BRAINSTORM.md](./VALIDATION-BRAINSTORM.md) | The design rationale behind the validation model, plus the shipped/deferred status and the cross-document roadmap. |

Start with the [root README](../README.md) for the pitch, setup, and running the app.

> **Code intelligence.** This repo is also indexed by GitNexus; `CLAUDE.md` and
> `.claude/skills/gitnexus/` describe how to query the code graph (impact analysis,
> execution flows). That's an agent-assist layer, separate from the product docs here.
