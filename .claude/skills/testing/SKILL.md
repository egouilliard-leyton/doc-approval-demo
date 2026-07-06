---
name: testing
description: Write and run tests, and self-verify, as part of "done" — not only when asked. READ THIS whenever a task asks to write tests / unit tests / smoke tests / e2e tests, "test it", "make sure it works", "did you test it yourself", assess or grow test coverage, run the test suite, or after ANY implementation of behavior/interfaces/endpoints/UI. Covers unit + smoke + e2e (real UI via PinchTab), the 100%-pass don't-stop gate, surfacing the test report, and giving the owner a manual "what to test" checklist. If code shipped, it is not done until you have exercised it end-to-end yourself and the suite is green.
---

# Testing

Deliver code that is **actually verified** — unit-tested, smoke-tested, and exercised end-to-end on the real thing before you ever say "it works." The job is not done when the code compiles; it is done when you have run it, the full suite is green, and the tests are committed. `node --check` / "it builds" / "it should work" is **not** a test.

## Why this skill exists (the gap it closes)
Testing here happens **reactively** — the owner has to ask "did you test it?", often twice, and the honest first answer is too often "no." The single clean miss this week was a session that ran `node --check`, then handed testing back to the owner — exactly after he said *"you should test and make sure it works before telling me to test again."* Close that gap: **self-verify before handing back, every time.**

## When this runs
1. **As part of "done"** — after implementing any behavior, interface/endpoint, or UI. Write tests and run them without being asked.
2. **On explicit request** — "write tests", "write smoke tests", "test it with pinchtab", "run all tests and fix", "how is the e2e coverage?".
3. **As the orchestrator's test gate** — `/orchestrate` Step 5 follows this skill (100% non-skipped pass before commit).

## Non-negotiables (Edouard's standing requirements)
Hard requirements, each asked for repeatedly:
- **Self-verify before handing back.** Never tell the owner "it works" or "you can test it now" until you have actually run the flow end-to-end yourself. If you haven't run it, say so and run it — don't hand testing back.
- **Unit AND smoke — both, explicitly.** Not one or the other. Unit tests for logic; smoke tests that the thing actually boots and the happy paths work. After UI work, *"write smoke tests after testing with pinchtab."*
- **E2E on the real UI via PinchTab**, not just unit. Drive the actual app: **every button works, every URL loads the correct information, no console errors**, UX/UI looks as it should. Include the **hard multi-step flows** (at least ~3 cross-section journeys, e.g. create→configure→verify), not just single pages.
- **100%-pass, don't-stop gate.** *"Do not stop until all are implemented and pass."* Iterate until 100% of non-skipped tests pass. A stable set of environment-dependent skips is fine; never turn a real failure into a skip or delete a test to go green. When you change shared state, fix the tests that encode a count/version you just changed — don't suppress them.
- **Surface the report.** Tell the owner where the test/smoke report is, and **open the HTML report in Chrome** when there is one (e.g. Playwright's `127.0.0.1:9323`).
- **Give a manual "what to test" checklist.** He tests in parallel — hand him a short numbered list of what to click/verify himself.
- **Green, then commit + PR.** When the suite is green, commit the tests and open/update the PR — don't leave tests uncommitted.

## Test types (write the ones the change needs)
| Layer | What it covers | Typical tool |
|---|---|---|
| **Unit** | Pure logic, edge cases, error paths — fast, isolated | pytest · vitest · jest · go test |
| **Smoke** | The app boots and the critical happy paths work; every route responds; no errors | Playwright (frontend) · a `smoke.py`/`smoke` runner · API pings |
| **E2E (real UI)** | Full user journeys driven through the actual browser, incl. multi-step flows | **PinchTab** (`/pinchtab`, `/leytongo-testing-and-guides`) · Playwright |
| **Integration** | Real dependencies wired together (DB, webhooks, auth) | project's harness; live services where creds exist |

## Workflow
1. **Discover the test setup.** Find the existing test dir, runner, and conventions (`pytest.ini`/`pyproject`, `vitest.config`, `playwright.config`, a `smoke` script, CI). **Match them** — mirror the nearest sibling test's structure, naming, and fixtures. Don't introduce a new framework when one exists.
2. **Decide the layers.** For the change, write the unit tests it needs + smoke tests for the paths it touches. If it has UI, plan the PinchTab e2e journeys (including ≥3 hard multi-step ones).
3. **Write tests that assert real behavior**, not tautologies. Cover the edge/error cases, not just the happy path.
4. **Run everything and go green.** Run the full suite; iterate until 100% of non-skipped tests pass. Root-cause real failures (they often expose real bugs — fix the bug, not the test). Use sub-agents to parallelize big runs when helpful.
5. **Drive the real UI.** For anything user-facing, actually walk it through PinchTab: every button, every URL, no console errors, UX looks right. Note any failure you find as a real bug.
6. **Surface results.** Report counts (unit/smoke/e2e passed), point to the report, open the HTML report in Chrome if there is one, and give the owner a numbered manual-test checklist.
7. **Commit + PR.** Stage tests explicitly, commit with counts in the message, push / open the PR.

## Coverage assessments & audits
When asked "how is the coverage?" or to plan the test suite: report the current state honestly (what's tested, what's RED, what's missing), then either grow the suite to the target or deliver a prioritized plan — whichever was asked. Reconcile any count you cite against a real run; don't quote a stale number.

## Environment-blocked tests
Some e2e/integration tests need secrets/services (Supabase keys, `SVIX_AUTH_TOKEN`, live SpiceDB, etc.). If a test can't run because a credential/service is genuinely missing, **say so explicitly and surface it as a blocker** — don't silently skip it and imply everything passed. Run everything that *can* run; name what couldn't and why.

## Self-improvement
If this pass taught you something reusable about the project's test setup (the runner, a fixture pattern, where the smoke script lives, a flaky area), update this SKILL.md. If it touched a project-specific testing skill's domain, refresh that skill too.

## Anti-patterns (do NOT do)
- Don't claim "it works" / hand testing back before running it yourself.
- Don't treat `node --check`, a typecheck, or "it builds" as testing.
- Don't skip or delete a failing test to go green, or hide a real failure behind a skip.
- Don't write only unit tests when the ask was unit **and** smoke (and e2e).
- Don't leave tests uncommitted, or forget to point the owner at the report.
- Don't quote a coverage/test number you didn't just verify against a real run.
