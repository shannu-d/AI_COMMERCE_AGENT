# Architecture Analysis — Merchant AI Commerce Agent

Analysis of `architecture.md` (16,736 lines / ~200 KB), read in full. **No application
code has been written and `architecture.md` has not been modified.**

## The documents

| File | What it answers |
| --- | --- |
| [01-architecture-inventory.md](01-architecture-inventory.md) | Every architectural component across 13 layers, with responsibility and how completely the spec defines it |
| [02-dependency-map.md](02-dependency-map.md) | What depends on what, the ordering conflict inside the source document, and a 16-milestone build order |
| [03-open-questions.md](03-open-questions.md) | 45 ambiguities and missing decisions, each with severity and a proposed default |
| [04-task-breakdown.md](04-task-breakdown.md) | 100 tasks — the document's own 58, plus 42 that close its gaps |
| [05-proposed-repo-structure.md](05-proposed-repo-structure.md) | The four partial file trees in the spec reconciled into one, plus the documentation and notes structure |

## What the system is

A conversational commerce agent for a merchant catalog (CircuitCraft, 30–36 SKUs), built
on one invariant that every part of the document restates:

> **LLM proposes → application validates → user authorizes → Razorpay executes → system audits.**

Claude Sonnet handles natural language and tool selection. PostgreSQL owns product
truth. A deterministic ranking engine owns relevance. A deterministic Policy Engine owns
whether money may move. A verified Razorpay webhook owns whether it did.

The flagship demonstration is not the happy path — it is the **price-drift failure**: a
buyer approves a total, the price changes before order creation, the Policy Engine
re-fetches live data, fails, blocks the Razorpay order, and forces a fresh approval with
a fresh idempotency key.

## Headline findings

1. **The catalog schema is the only fully specified layer.** All seven Phase-1 tables
   have columns, types, constraints, and indexes. Every commerce table the money path
   depends on — carts, orders, payments, approvals, idempotency keys, audit events — is
   named but never defined.
2. **The ranking engine has no RelevanceScore formula**, and the document gives two
   different weight sets for the same calculation. Both must be resolved before the
   ranker can be deterministic, which the spec demands.
3. **Compatibility depends on a canonicalization step that does not exist.** The model
   must not guess compatibility, yet the model is what produces the target identifier
   string that gets matched against the database.
4. **Two tools contradict their own safety rules.** `request_approval` is model-callable
   but approval is a human act; `create_order` is in the tool list but the spec says it
   must not be freely available to the model.
5. **The document's own task list has no tasks for** infrastructure, the database, the
   domain services, the ranking engine, the API layer, or evaluation — roughly the
   bottom half of the system.
6. **Two sections disagree on build order** for the commerce schema, and the document
   references an external project brief (MUST-WORK / SHOULD-WORK tiers, a
   "pre-submission gate") that is not part of this file.

## Eight decisions that block coding

From [03-open-questions.md](03-open-questions.md):

| # | Question | Blocks |
| --- | --- | --- |
| A2 | RelevanceScore formula | Ranking engine |
| B1 | Device-identifier canonicalization | Compatibility service |
| C1 | Phase-2 commerce schema | The entire money path |
| C3 | Session and approval persistence | Approval + policy |
| C4 | Money representation at the Razorpay boundary | Payment correctness |
| D5/D6 | May the model approve or create orders | Approval + orders |
| E3 | Canonical `/api/chat` contract | Agent + frontend |
| F11/F12 | External requirement tiers, and the seed catalog data | First milestone |

## Status

Analysis complete. Awaiting approval before any implementation.
