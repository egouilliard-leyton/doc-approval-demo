---
name: documentation
description: Write project documentation and keep it current — the doc pass that should happen as part of "done", not only when asked. READ THIS whenever a task creates/updates docs (README, architecture/handover docs, ROADMAP, CHANGELOG, API/reference docs, docstrings, usage guides), when the user says "update all documentation" / "document this" / "keep docs up to date" / "make docs navigable", when sharing something with humans (a setup/handover doc), or after ANY implementation that changed behavior, interfaces, config, setup, or data model. If code shipped and the docs no longer match, bringing them in line is part of finishing the work.
---

# Documentation

Produce documentation that is **accurate, minimal, discoverable, and committed** — and keep it current as code changes. The job is not done when the code works; it is done when the docs match the code and are pushed. Out-of-date docs are worse than none.

## Why this skill exists (the gap it closes)
Documentation here is habitually deferred to a final "now update all documentation," and sometimes the session ends with docs half-written and **uncommitted**. Treat a docs update as a first-class deliverable with the same "committed & pushed, verified" bar as code. **Don't wait to be asked twice.** If you shipped a change that a reader would need to know about, update the docs in the same pass and say you did.

## When this runs
1. **As part of "done"** — after any change to behavior, a public interface/signature, config/env, CLI flags, setup steps, or the data model. Don't wait for an explicit request.
2. **On explicit request** — "update all documentation", "document X", "create the docs", "keep docs up to date".
3. **As an orchestrator phase closeout** — dispatched by `/orchestrate`'s Documentation step (a dedicated doc sub-agent invokes this skill).
4. **When sharing with humans** — a setup/onboarding/handover doc (see "Handover mode").

## Non-negotiables (Edouard's standing requirements)
These are hard requirements, not preferences — each has been asked for repeatedly:
- **Cross-linked navigation.** Every docs pass builds/refreshes a **docs index hub** (`docs/README.md` or the repo's equivalent) and adds nav links between related docs. **Verify every link resolves** before finishing. "Seamless navigation around the docs" is a requirement, not a nice-to-have.
- **"For the next agent."** Write so a fresh agent or teammate can pick up the work cold: current state, architecture, how to run it, what's left. Handover/onboarding framing.
- **If no docs exist, create the full set** — don't just drop a README. Standard set: `README.md` + `docs/ARCHITECTURE.md` + `docs/API.md` (if there's an API/CLI surface) + `docs/ROADMAP.md` (state + what's left) + `docs/README.md` (the index) + `HANDOVER.md` when handing off.
- **Commit & push.** A docs pass isn't complete until the files are committed and pushed (or in the PR). Never end with docs written-but-uncommitted. README changes reach GitHub.
- **Verify claims against code.** Any number in docs (test counts, endpoint counts, versions, primitive counts) must be checked against the real code/output before writing — don't copy a stale figure.
- **Mask secrets.** Never print a real secret in any doc; show `len=N` or last-4 only. Use `.env.example` with placeholder values, never real ones.

## Core principles
- **Document the contract, not the implementation.** What it does, how to use it, inputs/outputs, gotchas, and *why* for non-obvious decisions. Let the code carry the "how".
- **Discover, then match.** Mirror the repo's existing docs location, format, headings, and tone. Don't introduce a new docs system when one exists; respect generated/off-limits files (e.g. gitnexus-managed `CLAUDE.md`/`AGENTS.md` — leave those alone).
- **Minimal and true.** No aspirational or speculative docs, no badge/boilerplate padding. Every command/example must be real and, where feasible, verified by running it.
- **Diff-driven updates.** When updating, start from `git diff` (or the change summary) and touch only the sections the change affects. Don't rewrite whole files.
- **No orphan docs.** New docs are linked from the index; docs for removed features are deleted or corrected in the same pass.

## Doc types & where they go (discover first, then match)
| Change / need | Doc to touch |
|---|---|
| New/changed public API, endpoint, function, CLI | Reference docs / docstrings / OpenAPI + a usage example |
| New feature or module | README feature list + short "how to use"; ARCHITECTURE doc if the repo keeps one |
| Behavior / interface / config change | The existing section — update in place; CHANGELOG entry if the repo keeps one |
| Setup / install / env / security nuance | README "Getting started", `.env.example` (mask real values), note prerequisites (e.g. "requires Claude Code", sandboxing) |
| Architecture / decision | ARCHITECTURE doc or ADR/decision-record if the repo uses them |
| Project state & what's left | ROADMAP / HANDOVER |
| Handing to humans/dev team | Human-facing handover doc (see Handover mode) |

## Workflow
1. **Locate the docs surface.** Look for `README*`, `docs/`, `CHANGELOG*`, `HANDOVER*`, ADRs, docstring conventions, any docs generator (mkdocs, Sphinx, Docusaurus, JSDoc/TypeDoc). Match what exists; if nothing exists, plan the standard set above.
2. **Determine the delta.** From the request or `git diff`, list exactly what changed that a reader needs to know.
3. **Write/patch the minimum.** Edit affected sections in place; add sections only where new surface appeared. Include a runnable example for anything user-facing.
4. **Verify.** Run commands/snippets where feasible; reconcile every number against real output; mask secrets.
5. **Wire navigation.** Ensure new files are linked from the index hub and relevant docs cross-link each other. **Check every link resolves.**
6. **Commit & push.** Stage docs explicitly by path, commit with a clear message, push (or add to the PR). Confirm it reached the remote/GitHub.
7. **Report.** List docs created/updated, what changed, and the commit — so the caller sees docs kept pace. If a report is requested, also deliver a plain-text `.txt` summary alongside any HTML/MD.

## Handover mode (sharing with humans)
When docs are for a person/team rather than the next agent, produce a **self-contained human-facing handover** (docx/PDF/HTML per the ask) covering full setup — prerequisites, install, credentials/config (masked), how to run, and where to go next. Use `/md-to-pdf` or the docx skill for polished output. For mixed-status content (confirmed vs still-open), use Obsidian-style callouts (`[!success]`/`[!warning]`/`[!question]`/`[!info]`) with a Legend block.

## Keeping docs updated (the maintenance half)
- Treat a code change with no matching doc change as an **incomplete change** — flag it even if not asked.
- On removal, remove/correct the docs in the same pass. Stale instructions harm more than gaps.
- CHANGELOG (if present): one entry per user-visible change, newest on top, repo's existing style.
- Consolidate over duplicate; if info lives in two places, merge and cross-link.

## Self-improvement
If this pass taught you something reusable about how docs work in this project (a convention, a docs generator quirk, where the index lives), update this SKILL.md. If the docs pass touched a project-specific skill's domain, refresh that skill's SKILL.md too — skills here are expected to be self-improving.

## Anti-patterns (do NOT do)
- Don't end a session with docs written but uncommitted.
- Don't add a new doc without linking it from the index, or leave dead links.
- Don't pad with badges / empty "Contributing"/"License" stubs the repo didn't ask for.
- Don't document volatile internals that will rot; document the stable contract.
- Don't invent behavior or copy stale numbers — verify or mark as unverified.
- Don't touch generated/off-limits docs (gitnexus `CLAUDE.md`/`AGENTS.md`, vendored files).
