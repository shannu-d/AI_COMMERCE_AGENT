# Day 05 — 4 September 2026

**Date:** 4 September 2026
**Time:** 10:55 – 20:16 IST (+0530), from commit timestamps `e10371c` … `c67186b`

**Gap before this day:** no commits between 3 September 11:09 and 4 September 10:55. What
happened in that period is not established from repository evidence, except that the readiness
audit in `docs/audit/` carries the date 3 September 2026 and names HEAD `4081628` — the last
commit of Day 04 — so it was performed against that state and committed here.

## What Was I Trying to Do?

Turn a chat demo into something that looks like a shop, then make the money path actually run
against Razorpay for the first time.

## Question

Two, and the second one was not the one I expected to be asking.

"Can the catalogue hold categories the specification never mentioned without a schema change?"

And then, once real credentials were in `.env`: **why does the checkout return 503?**

## Answer

The catalogue expanded with **no migration** — products, variants and attributes are JSONB and
the ranking, filter, tool and service layers are category-agnostic by design (ADR-021).

The 503 was not a credentials problem, a Razorpay problem, or a code problem in the payment
path. **The `razorpay` package was neither installed nor declared in `pyproject.toml`.** One
missing dependency line.

## Why?

The audit is what found it, and it found it by disbelieving the documentation. Two documents
blamed missing credentials; the credentials were present, valid and test-mode. The audit ran
`POST /api/orders/{id}/checkout` and read the actual error:
`503 PAYMENT_PENDING: "the razorpay package is not installed"`.

That is the whole reason the audit was worth doing: it treated documentation claims as
hypotheses and checked them.

## What Changed?

- **Storefront** — home, category, product, cart and order pages, the EASY BUY identity, and a
  dedicated Smart Agent recommendations surface (`e10371c`); ADR-020 records why the cards moved
  out of the transcript
- **Catalogue expansion** to clothing and furniture, data only (`1fba159`, ADR-021)
- **Merchant dashboard**, backend and frontend — seven pages, `/api/merchant/*` (`39f28b2`, ADR-022)
- **The readiness audit** committed as `docs/audit/` — 19 documents plus an index (`17c5236`)
- **Authentication and authorization** — customers and merchants, argon2id, opaque bearer tokens,
  `merchant_activity`; migrations `0005_identity` and `0006_merchant_activity` (`12963cb`, ADR-023)
- **`razorpay>=1.4` declared**, and the test suite made hermetic at the payment boundary (`2dda5ff`)
- **Auth frontend** and `python -m app.admin.provision_merchant` (`4ac2759`)
- **MCP server** — `python -m app.mcp`, exposing the merchant to an external AI buyer (`a9c7506`,
  ADR-024)
- Submission material and the live-money-path record (`cc025d0`), then a repo tidy (`c67186b`)

## Problem I Hit

Six, and the shape of them is worth recording: **none was a defect in the payment integration
itself.** The Razorpay client, signature verification and webhook handlers were correct. What
broke was environment and process drift.

| | What | Cause |
| --- | --- | --- |
| A1 | The frontend was talking to the wrong backend | An unrelated local app occupied port 8000, and `config.ts` defaulted to `:8000` with no committed `frontend/.env` |
| A2 | Razorpay webhooks returned 502 | The ngrok tunnel forwarded to `:8001`; the backend had moved to `:8004` |
| A3 | The running backend lacked half its routes and reported the old merchant name | A stale uvicorn process started days earlier, plus a stale `DEFAULT_MERCHANT_NAME` in `.env` |
| A4 | `razorpay` imported but **not declared** — the single P0 | The M11 dependency line was never added |
| A5 | Two API tests began failing | Once real keys were in `.env`, `Settings` picked them up and `POST /api/orders` made a **live provider call mid-suite** — the suite was never hermetic at the payment boundary |
| A6 | Checkout failed: "International cards are not supported" | The test card's BIN is international and this test account is domestic-only. **Not a code bug** — Razorpay sent a correct `payment.failed` webhook and the app processed it correctly |

See `docs/bugs/undeclared-razorpay-dependency.md` (BUG-001) and
`docs/bugs/non-hermetic-test-suite-live-payments.md` (BUG-004). The full list is
`docs/notes/bugs-found-during-development.md` §A.

## What I Tried

A5 is the one that changed how the suite is built. The fix is in `tests/conftest.py`: blank
`Settings.model_config["env_file"]` so the suite cannot pick up real credentials from the
developer's `.env`, and inject a fake LLM client into the auth tests the way the chat tests
already did. Before that, running `pytest` on a machine with working keys made real API calls.

A6 turned into a demo asset rather than a fix. The decline path is real, it is handled
gracefully, and it is now the documented failure demonstration: use Netbanking → Success, UPI
`success@razorpay`, or a domestic card.

## What Worked

**The money path ran end to end for the first time.** Order → Razorpay Checkout → a
signature-verified webhook → `PAYMENT_CONFIRMED` → audit rows. The `payment.failed` path was
verified live too, on a genuine international-card decline.

That closes M11's and M12's live checks, which Day 03 had explicitly left open.

The MCP surface was verified end to end against the same Razorpay test mode: `create_quote` →
`authorize_and_pay` with an amount-carrying mandate → `get_order_status`.

Suite after M16: backend **1344 passed** with a database; frontend **57 passed**, typecheck,
eslint and build clean (`docs/implementation-status.md`, M16 section).

## What Did Not Work?

The audit's own conclusion needs one qualification, which was added later: it says "no logic
defects were found". That was true of what it examined. It did not drive the whole buyer journey
from an empty browser, and four logic defects were living in exactly that band — found the next
day. See Day 06 and the addendum in `docs/audit/19-final-readiness-report.md`.

Four audit recommendations were still open at the end of the day: startup validation of
`GROQ_API_KEY` (R3), a git remote so CI can run (R6), a configuration fingerprint in the startup
log (R8), and automated browser E2E (R9).

## Decision

**The catalogue may grow beyond the specification's 30–36 SKU prototype, as data only** (ADR-021).
`DEFAULT_MERCHANT_ID` is unchanged; only the display name moves to EASY BUY.

**Authentication reopens ADR-006's "no users table" deliberately** (ADR-023). A merchant
administrator is created by an operator command, never by an HTTP route — a registration endpoint
with a role field is the thing that most often goes wrong.

**The MCP surface is purely additive** (ADR-024): a separate entrypoint, not imported by the
FastAPI app, calling the same services. The invariant is preserved — `authorize_and_pay` carries
the exact quoted amount, the Policy Engine still re-reads live price and stock, `create_order` is
still not a tool.

## Testing

```
python -m pytest        # 1344 passed with a database after M16
cd frontend && npm run test    # 57 passed
```

Live, by hand: a real Razorpay test-mode order, Checkout in a browser, a signed webhook through
an ngrok tunnel, and the resulting audit rows.

## Result

A browsable storefront, a merchant dashboard, real accounts, a working money path proven against
Razorpay test mode, and a second front door over MCP. The evaluation suite did not exist yet.

## What I Learned

Documentation is a hypothesis. Two documents in this repository confidently blamed missing
credentials for a failure caused by a missing dependency line, and both were written by people
with access to the truth.

A test suite that reads the developer's `.env` is not hermetic, and you find out when it spends
real money — or in this case, calls a real provider mid-run.

## Remaining Work

- The evaluation suite (M15's other half)
- Audit recommendations R3, R6, R8, R9
- A live re-verification of the agent against the expanded catalogue

## Evidence

| Kind | Reference |
| --- | --- |
| Commits | `e10371c`, `1fba159`, `39f28b2`, `17c5236`, `12963cb`, `2dda5ff`, `4ac2759`, `a9c7506`, `01f11d0`, `cc025d0`, `c67186b` |
| Migrations | `0005_identity.py`, `0006_merchant_activity.py` |
| Tests | `tests/api/test_merchant.py`, `tests/api/test_auth.py`, `tests/api/test_account.py`, `tests/mcp/test_mcp_server.py`, `frontend/src/test/auth.test.tsx` |
| Docs | ADR-020 … ADR-024; `docs/audit/` (19 documents); `docs/notes/bugs-found-during-development.md` §A |
| Bug reports | `docs/bugs/undeclared-razorpay-dependency.md` (BUG-001), `docs/bugs/non-hermetic-test-suite-live-payments.md` (BUG-004) |
