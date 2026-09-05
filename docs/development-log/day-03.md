# Day 03 — 1 September 2026

**Date:** 1 September 2026
**Time:** 00:21 – 06:24 IST (+0530), from commit timestamps `78f6f4d` … `38232ea`

The long one. Nine milestones — the agent runtime, the commerce schema, and the entire money
path from cart to audit log.

## What Was I Trying to Do?

Two things, in order. First settle the provider question that Day 02 left open. Then build the
whole commerce path in one sequence, milestone by milestone, with tests and a documentation
entry after each: M5 agent runtime, M6 commerce schema, M7 cart, M8 approval, M9 Policy Engine,
M10 orders, M11 Razorpay, M12 webhook, M13 audit.

## Question

Several, one per milestone, but the one that governs the day: **at what point does the model
stop being involved?**

## Answer

At the cart. The model can search, look up a product, check inventory and propose a cart. It can
move a session to `WAITING_FOR_APPROVAL`. It cannot approve, and it cannot create an order —
`create_order` is not a registered tool at all, checked four separate ways
(`docs/implementation-status.md`, M5 section).

Everything after approval is deterministic: the Policy Engine evaluates ten rules with no
session, no query and no model; the order is committed *before* Razorpay is called; and payment
truth comes from a signature-verified webhook, not from the browser.

## Why?

The specification restates the same invariant in every part — LLM proposes, application
validates, user authorizes, Razorpay executes, system audits. The only way to make that true
rather than aspirational is to make the unsafe thing structurally impossible instead of
forbidden by prompt wording. L§29 and ADR-009 are explicit that the architecture must not depend
on what the prompt says.

So: no tool that charges anyone; `request_approval` can only write a `PENDING` row; `POST
/api/orders` requires an `approvals` row the model cannot create; and the Policy Engine re-reads
price and stock **live, inside the order transaction**, never from `cart_items.unit_price_snapshot`.

## What Changed?

- **ADR-016** removes the provisional Groq client (`78f6f4d`)
- **M5** agent runtime, executor, registry, tool handlers, `POST /api/chat`, sessions schema
  (migration `0003`) (`5ebcfee`, `7bd4dfa`, `723999d`)
- **M6** commerce schema — ADR-006's nine tables, migration `0004` (`0ba8b74`, `c5c8fec`, `7734fb3`)
- **M7** cart service, cart API, `propose_cart` handler (`1fd0683`, `2a40894`, `81f768f`)
- **M8** approval model and `POST /api/cart/approve` (`71b6a38`, `bdc8042`, `a29e4d7`)
- **M9** Policy Engine — ten rules, pure, no database (`9d25b89`, `a197636`, `fd276b9`)
- **M10** order creation, idempotency, minor-unit money conversion (`79ba93a`, `4e9cfc9`, `c52860e`)
- **M11** Razorpay order boundary and the SDK seam (`fa0bb96`, `74cbad6`)
- **M12** webhook handler — signature verification against the raw body (`2cb003e`, `5560ba8`)
- **M13** audit log (`40e67a1`, `3b73904`)
- **M15 backend half** — the named end-to-end scenarios (`dadb329`)
- The price-drift fix, and a written stopping point (`38232ea`)

## Problem I Hit

**`POST /api/cart/approve` could not recover from price drift. It looped.**

Found while writing the price-drift recovery integration test, not by a unit test — every unit
test passed, because each asserted one step in isolation.

The route re-priced the cart against the live catalog, incremented `cart_version`, then raised
`ApprovalError` because the incoming approval named the old version — and the generic
`try/except` around the service call rolled back the entire transaction, including the
legitimate re-pricing. The cart reverted to the old version and the old price. The next attempt
did exactly the same thing. The buyer could never reach a version they were able to approve.

See `docs/bugs/price-drift-approval-rollback-loop.md` (BUG-002). Fixed in `38232ea`.

A second, smaller one earlier in the day: the module-scoped seeded-database fixture cached the
schema *before* `test_catalog_integrity.py` downgraded to base at its own teardown, so every
later module queried a database with no tables. It surfaced several tests away from its cause and
read like a bug in the code under test.

## What I Tried

For the drift loop, the first shape was the obvious one — catch the error, return the status
code. That is what produced the loop, because "the approval failed" and "the re-pricing must be
discarded" are not the same statement. The fix separates them: the re-priced cart and its new
version are committed, and the stale-version refusal is returned on top of that, so the buyer's
next request can confirm a version that actually exists.

The same shape appears again in M10's order route, deliberately: when the service marks an
idempotency key FAILED, that write must survive, so the transaction is committed rather than
rolled back. A key left RESERVED after a refusal would deadlock the buyer's next attempt against
a lock nobody holds.

## What Worked

Each milestone was verified against the throwaway PostgreSQL before the next one started:

| Milestone | Result |
| --- | --- |
| M5 | 920 tests pass, 0 fail, 0 skip |
| M6 | 951 |
| M7 | 1018 |
| M8 | 1071 |
| M9 | 1115 |
| M10 | 1181 |
| M11 | 1201 |
| M12 | 1226 |
| M13 | 1246 |
| M15 (backend) | 1258 |

(from `docs/implementation-status.md`, per-milestone "How M*n* was verified" entries)

## What Did Not Work?

**M11's live check was not performed.** The Razorpay client was code-complete and covered by
test doubles, but no real test-mode order had been created — there were no credentials on this
machine at the time. That was recorded as an unperformed check rather than reported as done
(`74cbad6`, "docs: record M11 and its unperformed live check").

The same is true of the webhook: signature verification was tested against constructed payloads,
not against a request Razorpay actually sent.

## Decision

**Payment authorization stays outside the LLM.** The Policy Engine is pure and evaluates all ten
rules rather than stopping at the first failure, returning machine-readable reason codes. See
ADR-011 (Razorpay order boundary), ADR-012 (webhook as payment truth), ADR-013 (idempotency),
ADR-014 (price-drift recovery).

**A price change in either direction invalidates an approval.** P§32 illustrates only an
increase; ADR-014 extends it, because the buyer approved a specific total and charging a
different one — cheaper or not — charges an amount that was never authorized.

**The provider is Claude, not Groq** — recorded as ADR-016 on this day. That decision was
reversed by the project owner two days later; see Day 04 and ADR-018.

## Testing

```
python -m pytest        # 1258 passed, 0 failed, 0 skipped at the end of the day
python -m pytest tests/integration/test_scenarios.py
```

`tests/integration/test_scenarios.py::test_price_drift_recovers_through_a_fresh_approval` is the
test that found the loop and now guards it.

## Result

The full path exists end to end in code: chat → recommendations → cart → approval → policy →
order → Razorpay order → webhook → audit. None of the money path had touched a real payment
provider yet.

## What I Learned

Unit tests that each assert one step will all pass while the sequence they belong to is broken.
The drift loop needed an integration test to exist at all.

"Roll back on error" is not a safe default when part of the work in the transaction was
legitimate. Deciding *what* to roll back is a design question, not a `try/except` idiom.

## Remaining Work

- M11's live Razorpay check
- M12's real signed webhook
- M14: the entire frontend
- The provider question, which ADR-016 answered but the owner had not

## Evidence

| Kind | Reference |
| --- | --- |
| Commits | `78f6f4d`, `5ebcfee`, `7bd4dfa`, `723999d`, `0ba8b74`, `c5c8fec`, `7734fb3`, `1fd0683`, `2a40894`, `81f768f`, `71b6a38`, `bdc8042`, `a29e4d7`, `9d25b89`, `a197636`, `fd276b9`, `79ba93a`, `4e9cfc9`, `c52860e`, `fa0bb96`, `74cbad6`, `2cb003e`, `5560ba8`, `40e67a1`, `3b73904`, `dadb329`, `38232ea` |
| Migrations | `0003_sessions.py`, `0004_commerce_schema.py` |
| Tests | `tests/integration/test_scenarios.py`, `tests/policy/test_engine.py`, `tests/api/test_webhooks.py`, `tests/services/test_audit_service.py` |
| Docs | `docs/implementation-status.md` M5–M13 and M15 sections; ADR-011 … ADR-016 |
| Bug report | `docs/bugs/price-drift-approval-rollback-loop.md` (BUG-002) |
