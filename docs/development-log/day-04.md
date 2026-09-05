# Day 04 — 3 September 2026

**Date:** 3 September 2026
**Time:** 00:25 – 11:09 IST (+0530), from commit timestamps `657d490` … `4081628`

**Gap before this day:** no commits between 1 September 06:24 and 3 September 00:25. What
happened in that period is not established from repository evidence.

## What Was I Trying to Do?

Two things that had been blocked. Switch the LLM provider to Groq, because the owner decided
it — reversing the decision recorded two days earlier — and then let a browser talk to this API
at all, which turned out to be a bigger problem than choosing a frontend framework.

## Question

Reversing ADR-016 is a documentation problem and a code problem at the same time. Which comes
first, and how do I stop the repository holding two live answers to the same question?

Then: what is actually stopping a frontend from existing?

## Answer

The provider decision is superseded explicitly, not edited away. **ADR-018 supersedes ADR-016 in
full**; ADR-016 is retained as history with its conclusion marked void. `architecture.md` names
Claude Sonnet at L§44, L§48, L§50 and A§56 and is never edited, so the deviation lives in the ADR
and in `docs/notes/deviations.md` (D7).

What was stopping the frontend: **there was no CORS middleware anywhere in `backend/app/`.** Not
"misconfigured" — absent. A browser on any origin but the API's own would be refused before a
request was attempted, which is every realistic setup, since a dev server and the API cannot
share a port.

## Why?

The owner's instruction was that Groq is the required and locked provider, permanently unless
they change it. That contradicts the specification and the ADR the repository already had, and
the failure mode of leaving that unreconciled is specific: a later session reads only the
repository, finds ADR-016, and migrates the code back. So exactly one live decision is allowed
to exist on the question.

CORS was fixed before any frontend code existed, because it blocked every frontend of every
scope and every framework. There was no point choosing between React and Next.js while the
answer to both was "the browser cannot reach the API".

## What Changed?

- **M4-R:** `GroqClient` as the concrete client, model `openai/gpt-oss-120b`; `Settings` gains
  the Groq configuration; `test_boundaries.py` updated to guard the new single importer
  (`657d490`)
- **CORS**: `cors_allowed_origins` in `Settings`, validated at startup; `CORSMiddleware` in
  `create_app()`; `tests/api/test_cors.py` (`6d147a9`)
- **M14 F0–F9**: the Vite + React + TypeScript frontend — API client, Zod schemas, chat window,
  recommendation cards, cart panel, approval dialog, Razorpay checkout, order page
  (`6d147a9`)
- **`tests/api/test_frontend_contract.py`**: a backend test that reads the frontend's mirrored
  error-code array and fails on drift (`6d147a9`)
- ADR-017 (Vite, not Next.js), ADR-018 (Groq locked), `docs/PROJECT_STATE.md` and `PROGRESS.md`
  created (`196520c`)
- CI workflow (`7646966`), then eslint wired in (`6dbaa86`)
- ADR-019: the agent chat runs on Assistant UI's runtime, and only its runtime (`4081628`)

## Problem I Hit

Three, all found in the writing rather than after it.

**1. Groq is OpenAI-compatible, not Anthropic-shaped.** `finish_reason`, not `stop_reason`. Tools
shaped as `{"type": "function", …}`. Tool arguments as a JSON **string**, not an object. Usage
under `prompt_tokens`/`completion_tokens`. The system prompt is the first message, not a
top-level field — sending `system=` is silently ignored. Each of those was a real defect in the
provisional client that Day 02 committed, and each now has a named regression test in
`tests/llm/test_client.py`.

The most dangerous one: the provisional client's stop-reason table was Anthropic's with one key
renamed, so `length` would have mapped to `UNKNOWN` rather than `MAX_TOKENS`, leaving
`is_truncated` permanently `False` — a truncated intent passing as a complete one.

**2. A `pydantic-settings` behaviour that the tests could not see.** `cors_allowed_origins` is a
`list[str]`, and pydantic-settings runs `json.loads` over a complex type *in its environment
source, before any field validator runs*. So a comma-separated `CORS_ALLOWED_ORIGINS` in `.env`
raised `SettingsError` at import — while every test passed, because they constructed
`Settings(cors_allowed_origins="a,b")` directly and never crossed the environment boundary that
broke. Fixed with `Annotated[list[str], NoDecode]`, plus two tests that use the real
`monkeypatch.setenv` path.

See `docs/bugs/missing-cors-and-pydantic-config-crash.md` (BUG-012).

**3. The frontend's first error-vocabulary draft invented four codes that do not exist** —
`CATEGORY_NOT_FOUND`, `CART_VERSION_STALE`, `APPROVAL_EXPIRED`, `SPENDING_LIMIT_EXCEEDED`. Caught
by the new contract test that reads the frontend array from the backend suite.

## What I Tried

For CORS, three choices were made deliberately and each has a test: `"*"` is rejected outright;
an origin with a trailing slash or a path is rejected (a browser's `Origin` is scheme, host and
port, so `http://localhost:5173/` matches nothing); and `allow_credentials=False` with
`allow_headers=["Content-Type"]`, because nothing in `app/api/` reads a cookie or an
`Authorization` header at this point.

For the chat runtime, ADR-019 constrains what Assistant UI is used for: `useLocalRuntime` with a
custom `ChatModelAdapter` whose `run()` is a plain async function returning one result — the
documented non-streaming pattern, because `POST /api/chat` answers once per turn and streaming is
a closed decision (ADR-010). `npx assistant-ui@latest init` is explicitly not run: it targets
Next.js and installs via shadcn, neither of which this project uses.

## What Worked

Suite at the end of the CORS phase: **1273 tests pass, 0 failures, 0 skips** (the previous 1258
plus 15 for CORS), 893 needing no database. M4-R later took it to **1287**.

A full chat turn was verified live against Groq. `CLAUDE.md` line 22 records M4-R as
"Implemented and live-verified (M4-R, 2026-09-02)" — one day earlier than the commit that
introduced it, which is dated 3 September 00:25 IST. The two are reconcilable (that commit time is
2 September 18:55 UTC) but the verification's own date and time are **not established from
repository evidence**; only that the document asserts it happened.

## What Did Not Work?

**L§50's `[ ] Claude Sonnet connected` cannot be satisfied and is not satisfied by connecting a
different model.** That is recorded as a permanent deviation (D7) rather than quietly ticked.

**An environment trap that cost time:** the throwaway PostgreSQL binds IPv4 only, and on this
machine `localhost` resolves to `::1` first — so a `TEST_DATABASE_URL` pointed at `localhost`
fails its reachability check and the entire `requires_db` suite *skips*, while `psql -h 127.0.0.1`
connects with the same credentials. A skipping run is not a passing run. Use `127.0.0.1`.

## Decision

**Groq is the locked provider (ADR-018, supersedes ADR-016).** Model `openai/gpt-oss-120b` —
open weights, served by Groq; no request reaches OpenAI.

**Vite, not Next.js (ADR-017).** This reversed the recommendation `PROGRESS.md` had been
carrying. The earlier reasoning was that an SSR framework gives `RAZORPAY_KEY_SECRET` a
server-side home; reading `RazorpayClient.checkout_config()` shows the frontend never receives
that secret — it gets the *public* key id, an amount, a currency and a provider order id. With no
secret to protect and no SEO requirement, an SSR layer would be paid for and unused.

**Assistant UI for the runtime only (ADR-019).** Cards, cart and approval stay ordinary
components, because tools execute server-side and product cards are not tool UI.

## Testing

```
python -m pytest              # 1273 passed after CORS; 1287 after M4-R
python -m pytest tests/api/test_cors.py
python -m pytest tests/api/test_frontend_contract.py
cd frontend && npm run test && npx tsc -b --noEmit
```

## Result

The browser can reach the API, a frontend exists, and the agent talks to Groq. CI runs on
GitHub Actions. The money path still had never touched real Razorpay credentials.

## What I Learned

A configuration bug can hide behind tests that never cross the boundary where it happens.
Constructing `Settings(...)` directly is not the same as reading the environment.

When a decision is reversed, superseding it explicitly is cheaper than editing it away. The
repository is read by people — and sessions — who were not there.

## Remaining Work

- The storefront beyond the chat MVP (a scope question the owner had not answered)
- Real Razorpay credentials, and with them M11's and M12's live checks
- Merchant identity of any kind — there was still no users table

## Evidence

| Kind | Reference |
| --- | --- |
| Commits | `657d490`, `6d147a9`, `196520c`, `7646966`, `6dbaa86`, `4081628` |
| Tests | `tests/api/test_cors.py`, `tests/api/test_frontend_contract.py`, `tests/llm/test_client.py`, `frontend/src/test/agent-runtime.test.tsx` |
| Docs | ADR-017, ADR-018, ADR-019; `docs/implementation-status.md` §14 and §15; `docs/PROJECT_STATE.md` |
| Bug report | `docs/bugs/missing-cors-and-pydantic-config-crash.md` (BUG-012) |
