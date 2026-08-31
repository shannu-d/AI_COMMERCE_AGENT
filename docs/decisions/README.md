# Architecture Decision Records

Every decision this implementation makes that `architecture.md` leaves open, states inconsistently,
or requires without defining. `architecture.md` is the source of truth and is **never edited**;
resolutions live here instead.

These records are **append-only**. A decision that changes is superseded by a new ADR; the
superseded file keeps its text and gains a "Superseded by" status line.

## Index

| ADR | Title | Status | Milestone | Closes |
| --- | --- | --- | --- | --- |
| [000](ADR-000-template.md) | Template | Template | — | — |
| [001](ADR-001-architecture-invariant.md) | The Architecture Invariant | Accepted | all | — |
| [002](ADR-002-database-as-product-source-of-truth.md) | PostgreSQL as the Source of Truth for Product Facts | Accepted, **implemented (M1)** | M1 | B8, B9, F12 |
| [003](ADR-003-device-identifier-canonicalization.md) | Device Identifier Canonicalization | Accepted, **partly implemented (M1)** | M1 / M2 | B1, B3, B4, B5 |
| [004](ADR-004-deterministic-recommendation-scoring.md) | Deterministic Recommendation Scoring | Accepted | M3 | A1, A2, A3, A4, A5, A6, A7, A8 |
| [005](ADR-005-hard-constraints-vs-soft-preferences.md) | Hard Constraints versus Soft Preferences | Accepted | M3 | C5 (partial) |
| [006](ADR-006-commerce-schema.md) | Commerce Schema (Phase 2) | Accepted, **implemented (M5 sessions, M6 the rest)** | M5 / M6 | C1, C2, C3, C6, C7, E7 |
| [007](ADR-007-approval-model.md) | The Approval Model | Accepted, **implemented (M8)** | M8 | D1, D5 |
| [008](ADR-008-money-representation.md) | Money Representation | Accepted, **partly implemented (M1)** | M1 / M11 | C4 |
| [009](ADR-009-agent-tool-boundaries.md) | Agent Tool Boundaries | Accepted, **read tools (M5) and `propose_cart` (M7) implemented** | M5–M11 | B2, B7, D6, E1, E4, E5 |
| [010](ADR-010-chat-api-contract.md) | The Chat API Contract | Accepted, **implemented (M5)** | M5 / M14 | E3, E6 |
| [011](ADR-011-razorpay-order-creation-boundary.md) | The Razorpay Order Creation Boundary | Accepted | M9–M11 | D3, C6 |
| [012](ADR-012-webhook-as-payment-truth.md) | The Verified Webhook is Payment Truth | Accepted | M12 | D7, D8 |
| [013](ADR-013-idempotency-strategy.md) | Idempotency Strategy | Accepted | M10 / M12 | D4 |
| [014](ADR-014-price-drift-recovery.md) | Price Drift Recovery | Accepted | M9–M15 | D2, D9 |
| [015](ADR-015-llm-test-seam.md) | The LLM Test Seam | Accepted, **implemented (M4)** | M4 / M5 | F1, E2 |
| [016](ADR-016-single-model-provider.md) | Claude Is the Only Model Provider | Accepted, **implemented (M4)** | M4 / M5+ | — |

"Closes" refers to the question IDs in [`docs/analysis/03-open-questions.md`](../analysis/03-open-questions.md).

## What "Accepted, not implemented" means

Most of these ADRs are decided and unbuilt. That is intentional: the money path must not be coded
before its decisions exist, and this session's implementation stops after M1. Each ADR names the
milestone that will implement it, and lists the tests that milestone must produce.

Implemented so far: ADR-002 in full for the catalog, ADR-003's reference table, seed and
resolution service, ADR-004 and ADR-005 in full (the ranking engine, M3), ADR-008's catalog half
(`NUMERIC(12,2)`, string-encoded money in seed data, no floats), ADR-009's tool *schemas* and
exclusions (M4), ADR-009's read tools and validation pipeline plus ADR-010's chat contract and
ADR-006's two session tables (M5), ADR-006's remaining nine tables (M6), ADR-009's `propose_cart`
and the cart contract of F§12/F§13 (M7), ADR-007 in full (M8), ADR-015 in full, and ADR-016 in
full.

## Where these ADRs deliberately depart from prior proposals

`docs/analysis/03-open-questions.md` carries *proposed defaults*, which were recommendations rather
than decisions. Two were overruled, both recorded in the ADR that overruled them:

| Question | Analysis proposed | Decided | ADR |
| --- | --- | --- | --- |
| A2 RelevanceScore weights | category 0.40 / tag 0.25 / name+description 0.20 / attributes 0.15 | category 0.40 / attribute 0.30 / text 0.20 / tag 0.10 | ADR-004 |
| A4 PreferenceScore with no preferences | 1.0 (neutral) | 0.0 | ADR-004 |

Two others were sharpened rather than overruled: ADR-009 declines to register `create_order` even
as a hard-failing tool, and ADR-003 splits `target_type` into two distinct meanings instead of one.

## The three enums, kept apart

A recurring source of confusion in the source document is that three different state machines share
value names. They are separate, each owned by one table, and none is ever derived from another:

| Enum | Owner | Read by |
| --- | --- | --- |
| Conversation state | `sessions.conversation_state` | the UI and the agent runtime |
| Approval status | `approvals.status` | the Policy Engine |
| Order state | `orders.status` | the Policy Engine, the webhook handler, the UI |

A session whose conversation state reads `APPROVED` authorizes nothing. Only an `approvals` row does.
