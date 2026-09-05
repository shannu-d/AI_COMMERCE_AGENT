# Bugs and defects found during development

A consolidated, honest list of the real defects hit while building this — the
implementation-day ones and the final integration-day ones. Full narrative per
milestone is in [`../implementation-status.md`](../implementation-status.md);
this is the index a reviewer wants.

Every one of these was found by a test, a live run, or a forensic audit — none by
a user in production, because there is no production.

---

## A. Final integration day (2026-09-04) — the money path went live

These surfaced when real Razorpay test-mode keys and a real webhook were wired
in for the first time. **None was a defect in the payment integration itself** —
the Razorpay client, signature verification and webhook handlers were correct.
They were environment and process drift.

| # | What was wrong | Root cause | Fix |
| --- | --- | --- | --- |
| A1 | The frontend was talking to the wrong backend | An **unrelated local app** (`L:\RazorPay`, a SQLite mock) occupied port 8000, and `frontend/src/api/config.ts` defaulted to `:8000` with no committed `frontend/.env` | Committed `frontend/.env` → `http://127.0.0.1:8004`; documented the port-8000 squatter |
| A2 | Razorpay webhooks returned 502 | The ngrok tunnel forwarded to `:8001`; the backend had moved to `:8004` | Restarted `ngrok http 8004` on the reserved free domain; verified a real signed webhook end to end |
| A3 | The running backend lacked half its routes (`/api/sessions`, `/api/auth/*`, `/api/merchant/*`) and reported the old merchant name "CircuitCraft" | A **stale uvicorn process** started days earlier, plus a stale `DEFAULT_MERCHANT_NAME=CircuitCraft` in `.env` predating the EASY BUY rebrand | Restarted from current source; `.env` → `DEFAULT_MERCHANT_NAME=EASY BUY` |
| A4 | `razorpay` was imported but **not declared** in `pyproject.toml` | The M11 dependency line was never added; the readiness audit flagged it as the single P0 | Added `razorpay>=1.4` |
| A5 | Two API tests began failing (`test_the_razorpay_id_is_null_until_m11`, `test_an_approved_cart_creates_an_order`) | Once real keys were in `.env`, `Settings` picked them up and `POST /api/orders` made a **live provider call mid-suite** — the suite was never hermetic at the payment boundary | `tests/conftest.py` now blanks `Settings.model_config["env_file"]`; a fake LLM client is injected into the auth tests the way the chat tests already do it |
| A6 | Checkout failed with *"International cards are not supported"* | The test **card** (`4111 1111 1111 1111`) has an international BIN and the Razorpay test account accepts domestic only — **not a code bug**. Razorpay sent a correct `payment.failed` webhook, which the app processed correctly (order → `PAYMENT_FAILED`, cart intact) | No code change. Demo uses Netbanking → Success, UPI `success@razorpay`, or a domestic card. This became a genuine graceful-failure demo. |

## A2. Browser walkthrough (2026-09-05) — four defects the test suite could not see

Found by driving the running site in Chrome, end to end, as a buyer with an
empty browser. All four passed 1,697 backend tests and 69 frontend tests
beforehand, because each needs a state no test constructed.

| # | What was wrong | Root cause | Fix |
| --- | --- | --- | --- |
| A2-1 | **Add to cart did nothing on a fresh browser** — the button rendered disabled on both the product page and every product card, with no explanation | `useAddToCart` read the session id from storage *at render time* and both call sites disabled the button when it was `null`. A buyer who arrived by browsing has never spoken to the agent, so nothing had minted one. `ensureSessionId()` existed for exactly this and its docstring says so — **nothing imported it.** Every test signed in or created a session first | The session is resolved **inside** the mutation, via `ensureSessionId()`; the `!sessionId` gate is gone from both buttons |
| A2-2 | **Every agent turn failed** with "I could not reach the assistant just then" | Groq's binding limit is a **per-minute token bucket** (8,000 TPM), and one turn is two calls totalling ~9,200 tokens. Leg 1 succeeded, leg 2 got 429 — and the client's exponential backoff of 0.5s then 1.0s retried *inside the same minute*, three refusals in two seconds | `LLMRateLimitError` now carries the provider's own `retry-after` (header, else the "try again in 8.522s" sentence), and the retry loop waits it out, bounded by `MAX_RETRY_AFTER_SECONDS = 45`. Live: Groq asked for 13s, the turn completed |
| A2-4 | **A buyer's order never reached their account.** Worse, a merchant sign-in from the same browser *took* it: the order landed under the administrator, whom `/api/account/orders` answers 403 — so it belonged to nobody who could ask for it | Two halves of one rule. `POST /api/sessions` claims only for a customer; `POST /api/auth/login` claimed for **any** role, merchant included. And ownership is derived from `orders.session_id -> sessions.user_id`, never written onto the order, so a session still anonymous at order time produced an order owned by nobody — permanently, since the buyer had already signed in and their next login had nothing left to claim | `login` claims only when the account is a customer; `create_order` claims an anonymous session for a signed-in customer, on the same terms. Two tests: a merchant sign-in leaves the session anonymous, and an order placed on a session that was anonymous still appears in `/api/account/orders` |
| A2-3 | **A completed turn was thrown away by the browser** — `MALFORMED_RESPONSE`, but only for a buyer whose cart was not empty | `serialize_cart` omitted `status` and omitted `price_changes` when there was no drift. `CartResponse.of` patched both on afterwards, so `/api/cart` was right and the **chat-embedded cart was not** — two renderings of one cart, which that method's own docstring warns against | Both fields are emitted by `serialize_cart` itself; `CartResponse.of` adds nothing. A new contract test reads the `Cart` object out of `frontend/src/api/schemas.ts` and fails if a required key is missing |

The shape of all four: a defect in the seam between two things that were each
correct. Section D's observation still holds — the safety properties held
throughout, and no defect here could move money — but these were found by using
the site, which no amount of unit testing substitutes for.

## B. Caught by the readiness audit (2026-09-03)

| # | What | Status |
| --- | --- | --- |
| B1 | `@lru_cache`d settings served stale values after `.env` changed, with no warning — caused a real misdiagnosis during the audit itself | Known; restart-to-reload is documented. Fixed in effect by the hermetic-test change (A5). |
| B2 | Raw markdown rendered in the chat transcript (the most visible product defect) | Resolved by ADR-020 — the agent's reply is short prose, cards render on the `/agent` surface |
| B3 | A missing Groq key failed per-turn instead of at startup | The `GROQ_MODEL` validator fails loudly at startup; the key check still fails on first construction — acceptable, documented |
| B4 | `PROGRESS.md` stale and contradicting `PROJECT_STATE.md` | Recurring; `PROJECT_STATE.md` is the single source of truth and is kept current |

## C. Implementation-time defects (found by tests, per milestone)

Selected — the full list is in `implementation-status.md`.

| Milestone | Defect | How it was caught |
| --- | --- | --- |
| M1 | Ambiguous ORM relationship — `products` has two FK paths to `categories` (plain + composite merchant-scoping), so SQLAlchemy could not configure the mapper | A live query; fixed with explicit `foreign_keys=` and an **offline** test that forces mapper configuration |
| M2 | A catalog test asserted a wrong category slug; `CATEGORY_NOT_FOUND` was doing its job and the test was wrong | Live catalog run |
| M3 | The ten policy rule functions each took an `evaluated_at` parameter nine of them never used | Code review during the write; moved onto `TransactionContext` |
| M5 | Module-scoped seeded-DB fixture cached the schema *before* `test_catalog_integrity.py` downgraded to base, so later modules queried a database with no tables | A later module's fixtures failing several tests away — read as a bug in the code under test |
| M8 | **Serious:** `POST /api/cart/approve` rolled back its legitimate re-pricing work on an `ApprovalError`, so price-drift recovery looped forever — re-price, bump version, fail, roll back, repeat | Writing the price-drift recovery integration test |
| M4-R | Groq is OpenAI-compatible, not Anthropic-shaped: `finish_reason` not `stop_reason`, tool args as a JSON **string**, usage under `prompt_tokens` — each a real defect, each now a named regression test | The fake-SDK test suite, on its first assertions |
| M14/F1 | **There was no CORS middleware anywhere in the backend** — every browser of every framework would have failed | Found before any frontend code was written; fixed first |
| M14/F1 | A `pydantic-settings` bug — `CORS_ALLOWED_ORIGINS` as a plain comma list raised `SettingsError` at import because pydantic ran `json.loads` on it first | Fixed with `Annotated[list[str], NoDecode]` |
| F0 | The frontend's first error-vocabulary draft invented four codes that do not exist (`CATEGORY_NOT_FOUND`, `CART_VERSION_STALE`, `APPROVAL_EXPIRED`, `SPENDING_LIMIT_EXCEEDED`) | A new backend test that reads the frontend's mirrored array and fails on drift |

## D. Pattern worth noting

Almost every defect in section C was **in the test scaffolding, not the code under
test** — an ambiguous fixture scope, a wrong assertion, a missing double. That is
the intended shape: the safety properties (no invented SKUs, no model-set price,
webhook-only payment truth, human-gated orders) are enforced structurally, so the
code under test tends to be right and the tests around it are where the mistakes
live. Section A is the exception — that was pure environment drift on the day the
system first met the real world.
