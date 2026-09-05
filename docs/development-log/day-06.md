# Day 06 — 5 September 2026

**Date:** 5 September 2026
**Time:** 08:41 – 13:54 IST (+0530), from commit timestamps `8a94b48` … `b52a481`

## What Was I Trying to Do?

Land the evaluation suite, then actually *use* the application — open it in a browser and walk
the whole buyer journey. Later in the day the catalogue was rebuilt at the owner's request.

## Question

The suite passes 1,697 tests. The audit says no logic defects. **So what is still broken?**

## Answer

Four things, and none of them could have been found by any test in the repository. Every one
lives in a seam between two pieces that are each correct on their own.

## Why?

The evaluation suite evaluates the *agent*: 270 cases against the real catalogue, the real
ranking engine, the real cart, the real Policy Engine and the real MCP server, with only the
model and the payment provider faked. It is thorough about what it covers and structurally blind
to four things — it never renders a component, never calls a live model (ADR-015 forbids it),
reads a turn as a Python object rather than over the wire, and never placed an order on a session
that was anonymous at that moment.

So the browser found what the suite could not.

## What Changed?

Morning — the suite and the fixes it and the walkthrough produced:

- **`backend/tests/evals/`** — 270 cases, 3,470 deterministic checks (`8a94b48`)
- **F-3 fixed**: every `search_catalog` field now carries a description, the merchant's real
  attribute names are injected per category, `currency` is enumerated; prompt 1.2.0 → 1.3.0
  (`98b1100`)
- **Add-to-cart minted a session** inside the mutation (`d1ecb2c`)
- **Rate-limit retries honour the provider's `retry-after`** (`d7d801a`)
- **One cart serialization**, whichever door it comes through (`447791e`)
- **Order ownership** — login claims only for a customer; `POST /api/orders` claims an anonymous
  session (`4ae0390`)
- Documentation of all of it (`67006ad`), a repo tidy (`71d9e08`), a verified database backup
  (`ececefd`)

Afternoon:

- **Stale-session recovery** in the frontend (`567f35d`)
- **`RANKING_TOP_K` 3 → 9** at the owner's request (`9413bb5`, deviation D12)
- **Prompt 1.3.0 → 1.4.0**: do not build a cart the buyer did not ask for; demo prompt bank
  (`07381be`)
- **The catalogue rebuilt electronics-only**: 200 products / 360 SKUs / 40 leaf categories, and a
  `--prune` mode on the seeder (`b52a481`, deviation D13)

## Problem I Hit

Five distinct ones. In the order they appeared:

**1. F-3 — a stated requirement reached the catalogue as a preference.** Asked for
"noise-cancelling earbuds", the live model returned three real, in-stock, **non-ANC** earbuds and
described them as noise-cancelling. The cause was not the model: `search_catalog` reached it with
**no description on any field**, so nothing said `attributes` is the field that *eliminates*, and
nothing revealed that this merchant records `anc` rather than `noise_cancelling`. The requirement
went into `search_query`, which R§9 defines as a relevance signal and never a filter. The same
probe found a second defect beside it — the model volunteered `currency: "USD"`, which the
validator then refused, failing an otherwise correct search on a field the buyer never mentioned.
`docs/bugs/search-catalog-tool-parameters-f3.md` (BUG-008).

**2. *Add to cart* was dead on a fresh browser.** The button rendered disabled on the product
page and on every card. `useAddToCart` read the session id from storage at render time and both
call sites disabled the button when it was null — and a buyer who arrived by browsing has never
spoken to the agent, so nothing had minted one. `ensureSessionId()` existed for exactly this, with
a docstring saying so. **Nothing imported it.**
`docs/bugs/add-to-cart-anonymous-session.md` (BUG-005).

**3. Every agent turn failed.** Groq's binding limit is a per-minute token bucket, and one turn is
two calls totalling roughly 9,000 tokens. Leg one succeeded; leg two got a 429 every time — and
the bounded retry slept 0.5s then 1.0s, so all three attempts landed inside the same minute and met
the identical refusal in about two seconds.
`docs/bugs/llm-rate-limit-retry-exhaustion.md` (BUG-006).

**4. A completed turn was discarded by the browser** as `MALFORMED_RESPONSE`, but only when the
cart was non-empty — which is why it never reproduced against an empty session. `serialize_cart`
omitted `status`, and omitted `price_changes` when there was no drift; `CartResponse.of` patched
both on afterwards. So `/api/cart` satisfied the frontend's schema and the chat-embedded cart did
not — two renderings of one cart, which that method's own docstring warns against.
`docs/bugs/chat-cart-serialization-mismatch.md` (BUG-007).

**5. A buyer's order reached no account, and a merchant sign-in took it.** Ownership is derived
from `orders.session_id → sessions.user_id` and never written onto the order. `POST /api/sessions`
claimed only for a customer; `POST /api/auth/login` claimed for **any** role — so an administrator
signing in from the same browser took ownership of the anonymous session, and
`/api/account/orders` answers a merchant 403. The order belonged to nobody who was allowed to ask
for it. `docs/bugs/order-ownership-session-hijacking.md` (BUG-003).

Later in the day, two more, both caused by the catalogue growth:

**6. A 413 after the search had already succeeded.** With 200 products the tool payload — system
prompt, eight tool schemas and a per-category attribute vocabulary of 484 names — crossed Groq's
hard 8,000-token *per request* ceiling. The turn failed at the worst possible point: after the
search worked.

**7. `KeyError: 'wattage'`** during seed validation — a compatibility predicate named
`minimum_wattage` on wireless chargers whose attributes said `output_wattage`.
`docs/bugs/catalog-seed-constraint-key-error.md` (BUG-014).

## What I Tried

For the rate limit, the first fix honoured the provider's `retry-after` header (Groq asked for 13
seconds; the turn then completed). That was right but incomplete: when the *daily* quota is gone
Groq asks for twenty minutes, and sleeping the 45-second cap twice just made the buyer wait 90
seconds for the same failure. So a hint longer than the cap now fails immediately.

For the 413 I tried three things before one worked. Trimming the score breakdown out of the
model's copy of results saved 300 tokens and broke the evaluation grader that reads it — reverted,
because a claim about ranking that nothing can check is not worth 300 tokens. Capping the
vocabulary at twelve names per category saved 193 tokens, which was not enough. What worked was
three changes together: drop attributes (not scores) from the model's copy, send the vocabulary
only on the first call of a turn, and cap it at six names per category — ordered so the names
products actually *differ* on survive the cut. Under plain alphabetical order `storage_gb` fell
off the phone list and "a phone with 256GB" had no name to state.

## What Worked

- Backend suite **1,711 passed, 2 xfailed, 0 skipped**; frontend **71 passed**; lint and
  typecheck clean.
- Live against the model, after the rebuild: `5G phone under 30000` (the 4G model excluded despite
  being cheaper), `256GB storage`, `16GB RAM and 512GB SSD`, `20000mAh`, `144Hz`, `65W`, and
  `noise-cancelling earbuds under 5000` all filtered correctly.
- The F-3 probe now produces `search_catalog(category="earbuds", attributes={"anc": true})` and
  returns exactly the two ANC products.
- The database backup was verified by restoring it into a scratch database and comparing row
  counts, then dropping the scratch database.

## What Did Not Work?

**F-1 is still open.** The assistant's prose is not validated against the turn's own tool results,
so an invented SKU or price can reach `message`. Nothing downstream carries it —
`recommendations[]` is built from `TurnMemory`, the invented SKU does not resolve, and no order can
be created from it — but it is real, and it is recorded as two strict `xfail`s so the suite stays
green while the defect stays visible. `docs/bugs/llm-prose-hallucination-f1.md` (BUG-015).

**F-2 is still open.** `recommend_many` and `combine(total_budget=...)` are implemented, tested and
reachable from no tool or route.

**One capability was lost to the 8,000-token ceiling.** With six attribute names advertised per
category, `wifi_standard` falls outside the six for routers — so "Find a Wi-Fi 6 router" returns
every router, ranked, rather than only the Wi-Fi 6 ones. It under-filters rather than claiming
anything false, which is the direction prompt rule 9 asks for, but it is a real reduction and it is
documented in `docs/DEMO-SCRIPT.md` so it does not ambush a recording.

**The live evaluation re-run could not be completed.** The account's daily token quota was
exhausted (200,000/day, per model). A full two-leg turn is ~9,000 tokens, so a day holds roughly 22
turns per model.

## Decision

**The evaluation suite evaluates the agent, not the product.** Recorded as recommendation R-5 in
`docs/EVALUATION-REPORT.md`: drive the whole journey in a browser before any release. Its blindness
is not a coverage gap to fill with more cases.

**Top-K is configuration, not a business rule** (deviation D12). The evaluation cases now resolve
the cap from `Settings.ranking_top_k` instead of carrying the literal `3`, because a case file that
hard-codes a deployment setting fails the application for obeying its own configuration.

**Pruning is a separate, explicit request** (deviation D13). Seeding is an upsert and never
deletes, which is right for a loader — a merchant may legitimately add products through the
dashboard. `--prune` deactivates rather than deletes anything an order or a cart references.

## Testing

```
TEST_DATABASE_URL=postgresql+psycopg://ai_commerce:ai_commerce@127.0.0.1:5432/ai_commerce_test \
  python -m pytest -q          # 1711 passed, 2 xfailed, 0 skipped
python -m ruff check . && python -m ruff format --check .
cd frontend && npm run test && npx tsc -b --noEmit && npx eslint . --max-warnings 0
```

New regression tests written this day, all verified to fail without their fix:

- `tests/llm/test_client.py` — four rate-limit cases, including that a wait longer than the cap
  fails immediately rather than sleeping first
- `tests/api/test_frontend_contract.py::test_a_serialized_cart_carries_every_field_the_frontend_requires`
  — reads the `Cart` object out of `frontend/src/api/schemas.ts`
- `tests/api/test_auth.py::test_a_merchant_sign_in_does_not_claim_a_shopping_session`
- `tests/api/test_account.py::test_an_order_placed_on_a_session_that_was_anonymous_still_reaches_the_account`
- `frontend/src/test/agent-runtime.test.tsx` — a fresh session is minted after a 404, and a second
  refusal is reported rather than looped

## Result

The application works end to end in a browser, on a 200-product electronics catalogue, with the
agent filtering on real structured attributes. Two evaluation findings remain open and are
recorded rather than hidden.

## What I Learned

A test suite proves the code does what the tests say. It does not prove the product works. Four of
the five defects here were found by opening the application and using it, and each one had passed
1,697 backend and 69 frontend tests that morning.

Dead code with a docstring explaining exactly why it exists is worse than no code: `ensureSessionId`
described the bug it was written to prevent, and the bug shipped anyway because nothing imported it.

A hard per-request token ceiling is an architectural constraint, not an operational detail. It
decides how much the model can be told, and it got smaller — in effect — every time the catalogue
got bigger.

## Remaining Work

- **F-1** — validate the assistant's prose against the turn's own tool results
- **F-2** — expose R§13's combination search, or record that a basket ceiling is unenforced
- Audit **R3**, **R6**, **R8**, **R9** — startup key validation, a git remote, a config
  fingerprint, automated browser E2E
- `wifi_standard` and other names pushed outside the six advertised per category

## Evidence

| Kind | Reference |
| --- | --- |
| Commits | `8a94b48`, `98b1100`, `d1ecb2c`, `d7d801a`, `447791e`, `4ae0390`, `67006ad`, `71d9e08`, `ececefd`, `567f35d`, `9413bb5`, `07381be`, `b52a481` |
| Tests | `tests/evals/`, `tests/llm/test_client.py`, `tests/api/test_frontend_contract.py`, `tests/api/test_auth.py`, `tests/api/test_account.py`, `frontend/src/test/agent-runtime.test.tsx` |
| Docs | `docs/EVALUATION-REPORT.md` (§20a, R-5), `docs/notes/bugs-found-during-development.md` §A2, `docs/notes/deviations.md` D12 and D13, `docs/DEMO-SCRIPT.md` |
| Bug reports | BUG-003, BUG-005, BUG-006, BUG-007, BUG-008, BUG-013, BUG-014, BUG-015 in `docs/bugs/` |
