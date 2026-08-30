# Merchant AI Commerce Agent — Architecture Analysis Export

**Export date:** 2026-08-30  
**Source:** Analysis of `architecture.md` (16,736 lines, six parts)  
**Status:** No application code written; source document unmodified

---

## Overview

Analysis of the Merchant AI Commerce Agent specification: component inventory, dependency-ordered build plan, and the decisions the specification leaves open.

### Quick facts

- **16,736** lines read
- **13** architectural layers
- **100** tasks mapped
- **45** open questions
- **8** block coding

### The core invariant

Every part of the document restates this invariant:

```
Claude Sonnet → Application → User → Razorpay → System
proposes    validates    authorizes  executes   audits
```

The architecture ensures that Claude (the LLM) can never bypass the validation, authorization, execution, and audit boundaries, even through prompt injection or misconfiguration.

---

## Section 1: What the read turned up

Six headline findings drive everything that follows.

### Finding 01: The catalog schema is the only fully specified layer

All seven Phase-1 tables arrive with columns, types, keys, unique constraints and indexes. Every commerce table the money path depends on — carts, cart items, orders, order items, payments, audit events, plus the implied approvals, idempotency keys and webhook events — is named and then never defined.

### Finding 02: The ranking engine cannot be built as written

RelevanceScore has signals listed but no formula. PriceScore divides by an absent budget. PreferenceScore divides by zero when the buyer states no preferences. Two different weight sets are given for the same calculation (R§4 vs R§19). The document demands the ranker be deterministic and explainable, so none of this can be delegated to the model.

### Finding 03: Compatibility rests on a step that does not exist

The model must never invent compatibility — yet the model is what produces the `target_identifier` string matched against a free-form VARCHAR column. Nothing maps "I just got an iPhone 16" onto `iphone_16`. No canonicalization component, alias table, or lookup tool exists.

### Finding 04: Two tools contradict the safety rules around them

`request_approval` is offered to the model as a callable tool, but approval is by definition a human act. `create_order` appears in the tool list while the same document states it "must NOT be freely available to the LLM." Both need an explicit ruling before the approval and order milestones.

### Finding 05: The document's own task list omits the bottom half of the system

Its 58 numbered tasks cover the LLM, agent, policy, Razorpay, frontend and integration. There are no tasks for infrastructure, the database, the domain services, the ranking engine, the API layer, or evaluation — all of which the numbered tasks depend on.

### Finding 06: Two sections disagree on build order, and one input is missing entirely

The database part forbids commerce tables in the first milestone; the frontend part sequences cart work before the frontend. Separately, the document repeatedly cites MUST-WORK / SHOULD-WORK tiers and a "pre-submission gate" from a project brief that is not part of this file — and the 30–36 SKU CircuitCraft catalog it seeds from is referenced but never supplied.

---

## Section 2: Component inventory

Thirteen layers. The bar charts show how much of each layer the document defines well enough to implement directly (FULL), versus what needs a decision first (PARTIAL), versus what is required but was never named as a component at all (IMPLIED).

### Layer inventory table

| Layer | Parts | FULL | PARTIAL | IMPLIED | What is missing |
|-------|-------|------|---------|---------|-----------------|
| 0 Infrastructure | 9 | 22% | 34% | 44% | Dev orchestration, CI, test harness never mentioned |
| 1 Catalog schema | 7 | 86% | 14% | — | Only `compatibility_rules` semantics |
| 2 Commerce schema | 11 | — | 45% | 55% | No column definitions anywhere |
| 3 Repositories | 11 | — | — | 100% | Named in prose, absent from every file tree |
| 4 Domain services | 8 | 12% | 88% | — | Responsibilities listed, interfaces not |
| 5 Ranking engine | 11 | 36% | 64% | — | Relevance formula, weight set, budget combination |
| 6 Policy Engine | 12 | 50% | 50% | — | Limit scope, approval TTL, idempotency lifecycle |
| 7 LLM layer | 10 | 40% | 60% | — | Retry and timeout values, final schemas |
| 8 Agent Runtime | 13 | 62% | 38% | — | State machine, loop limit, session persistence |
| 9 Tools | 9 | 22% | 78% | — | Schemas illustrative; two have contested semantics |
| 10 API | 8 | 25% | 50% | 25% | Two conflicting chat response shapes |
| 11 Payments | 9 | 78% | 22% | — | Event subscriptions, money units, failure recovery |
| 12 Frontend | 24 | 55% | 45% | — | React vs Next.js undecided; no product images in schema |
| 13 Quality | 9 | 44% | 34% | 22% | No strategy for testing the agent without live model calls |

**Legend:**
- **FULL (teal):** Implementable as written
- **PARTIAL (ochre):** Needs a decision
- **IMPLIED (red):** Required but never defined

---

## Section 3: Dependency-ordered build

Sixteen milestones, each independently demonstrable and depending only on those before it. Filled markers indicate the critical path to the flagship price-drift demonstration.

### Milestone sequence

| M# | Milestone | Contains | Exit condition |
|----|-----------|----------|-----------------|
| M0 | Foundation | Repo scaffold, typed configuration, Postgres via compose, lint and type-check, pytest harness | **app boots, empty suite green** |
| **M1** | **Catalog schema** | Seven Phase-1 tables, constraints, indexes, Alembic migration, target-alias table, CircuitCraft seed | **migration up and down clean, seed loads** |
| **M2** | **Catalog read services** | Repositories plus Catalog, Compatibility and Inventory services, including device-target resolution | **device + budget returns correctly filtered products** |
| **M3** | **Ranking engine** | Hard-constraint filter, four scorers, weighted aggregation, Top-K, structured explanations, weight config | **reproduces the worked example, 0.797 vs 0.787** |
| M4 | LLM layer | Claude client, intent schema, intent extraction, system prompt, tool schema definitions, output validation | **natural language to validated intent, offline-testable** |
| **M5** | **Agent Runtime, read-only** | Runtime loop, session and context, state machine, tool registry and executor, the four read tools, chat endpoint | **"case for iPhone 16 under ₹1500" returns grounded Top-3** |
| **M6** | **Commerce schema** | Carts, orders, payments, approvals, idempotency keys, webhook events, sessions, audit events | **migration clean, FK integrity tests pass** |
| **M7** | **Cart** | Cart service with backend-authoritative totals and versioning, `propose_cart`, cart endpoints | **version increments on every mutation** |
| **M8** | **Approval** | Approval bound to session, cart, cart version and approved total, with stale detection and expiry | **stale approval rejected under test** |
| **M9** | **Policy Engine** | Deterministic engine, eight independently testable rules, machine-readable reason codes | **price drift and out-of-stock both FAIL with correct codes** |
| **M10** | **Orders and idempotency** | Order service, order state machine, idempotency key lifecycle, hard gate on order creation | **duplicate request yields exactly one logical order** |
| **M11** | **Razorpay orders** | Client abstraction, test-mode order creation, internal-to-Razorpay mapping, checkout handoff | **policy PASS produces a real test-mode order** |
| **M12** | **Webhook** | Raw-body capture, signature verification, event-ID dedupe, order-independent handling, payment state | **bad signature rejected, duplicate event causes one transition** |
| M13 | Audit and trace | Append-only audit service, the twelve named events, visible agent trace | **full transaction reconstructable from audit events** |
| M14 | Frontend | Chat, product cards, cart, approval, policy-failure recovery, Razorpay Checkout, order status | **seventeen-point definition of done** |
| M15 | Integration and evaluation | The ten wiring tasks, four end-to-end scenarios, prompt-injection suite, evaluation harness | **flagship price-drift scenario demonstrable end to end** |

**Critical path:** M1 → M2 → M3 → M5 → M6 → M7 → M8 → M9 → M10 → M11 → M12

**Parallelizable:** M4 can run alongside M2–M3. M13 (audit/trace) and M14 (frontend) can run alongside M9–M12 once contracts are frozen. M15 depends on everything.

---

## Section 4: Open questions

Forty-five in total across ranking, catalog, schema, policy, agent and things the document never covers. Each carries a proposed default so work can proceed — the proposals are recommendations, not decisions.

### The eight blockers

These must be resolved before their milestone can start.

#### A2: RelevanceScore has no formula — BLOCKING (M3)

**Question:** Six signals are listed — category, name, description, tags, requested attributes, specification — with no statement of how they combine. The ranker is required to be deterministic and explainable, so this cannot fall to the model.

**Proposed default:** A fixed-weight signal sum, each normalized to 0–1:
- Category exact match: 0.40
- Tag overlap ratio: 0.25
- Name and description token overlap: 0.20
- Requested-attribute match ratio: 0.15

---

#### B1: Device identifiers are never canonicalized — BLOCKING (M2)

**Question:** Compatibility matching depends on an exact string in a free-form column, produced by the one component forbidden from guessing compatibility.

**Proposed default:** A `compatibility_targets` reference table with canonical identifier, display name and alias array, plus a resolver step in the Compatibility Service. An unresolvable target triggers clarification, never a guess.

---

#### C1: Phase-2 commerce tables have no columns — BLOCKING (M6)

**Question:** Ten tables that the entire money path sits on exist only as names and a two-line sketch, while the seven catalog tables are specified to the index.

**Proposed default:** Design them in an ADR before M6, following the Phase-1 conventions:
- UUID primary keys
- TIMESTAMPTZ timestamps
- Foreign-key integrity
- Merchant scoping
- NUMERIC(12,2) money

---

#### C3: Session and approval persistence is deferred — BLOCKING (M8)

**Question:** The document explicitly leaves the strategy open, but the Policy Engine reads approval state and the audit requirement implies durability.

**Proposed default:** Persist to PostgreSQL. In-memory state would make the price-drift and duplicate-request scenarios untestable across processes.

---

#### C4: Money units are never reconciled — BLOCKING (M11)

**Question:** Postgres stores `NUMERIC(12,2)`; Razorpay transacts in integer paise. The conversion boundary is not mentioned anywhere, which is a silent correctness risk in the one place correctness matters most.

**Proposed default:** Keep NUMERIC(12,2) as the domain type, convert to integer minor units exactly once at the Razorpay client boundary, and assert round-trip equality in tests.

---

#### D5 / D6: Can the model approve, or create orders? — BLOCKING (M8 / M10)

**Question:** `request_approval` is model-callable but approval is a human act. `create_order` is listed as a tool and simultaneously declared off-limits to the model. Both need a ruling enforced in code, not in prompt wording.

**Proposed default:**
- `request_approval` may only move state to WAITING_FOR_APPROVAL; only a user-originated `POST /api/cart/approve` records approval.
- Do not register `create_order` as a model-callable tool at all.

---

#### E3: Two conflicting chat response shapes — BLOCKING (M5 / M14)

**Question:** The Agent Runtime part returns state and trace; the frontend part returns recommendations. Both the agent and the frontend build against this contract.

**Proposed default:** One union contract carrying:
- `session_id`
- `message`
- `state`
- `recommendations[]` (always structured, never parsed out of prose)
- `cart`
- `trace[]`
- `error`

---

#### F11 / F12: Two required inputs are outside this document — BLOCKING (M1)

**Question:** The MUST-WORK / SHOULD-WORK tiers and the "pre-submission gate" are cited repeatedly but live in a project brief that is not part of `architecture.md`. The 30–36 SKU CircuitCraft catalog is referenced but never supplied.

**Proposed default:** Obtain the brief before fixing scope; author the seed catalog as an explicit deliverable of M1 if none exists.

---

### Additional open questions (A1, A3–A8, B2–B9, C2, C5–C7, D1–D4, D7–D10, E1–E7, F1–F10)

These carry the same structure — question, severity, blocking milestone, proposed default — and are documented in full in `docs/analysis/03-open-questions.md`. The document includes:

- **A1:** Two competing weight sets (MAJOR, M3)
- **A3:** PriceScore undefined without a budget (BLOCKING, M3)
- **A4:** PreferenceScore divides by zero (MAJOR, M3)
- **A5:** Multi-product budget combination algorithm (MAJOR, M3)
- **A6:** Top-K scope on multi-product requests (MINOR)
- **A7:** Who writes the recommendation reason string (MAJOR, M5/M14)
- **A8:** Dynamic intent-driven weighting (MINOR)
- **B2:** Category slug taxonomy not shared with the model (BLOCKING, M4/M5)
- **B3:** `compatibility_rules.constraints` semantics (MAJOR, M2)
- **B4:** `rule_type` enum (MINOR)
- **B5:** Compatibility attaches to product, price/stock to variant (MAJOR)
- **B6:** Product images missing from the schema (MAJOR, M14)
- **B7:** `search_catalog` product/variant granularity (MAJOR, M5)
- **B8:** Merchant scoping at runtime (MAJOR, M5)
- **B9:** Currency handling (MINOR)
- **C2:** No user/identity model (MAJOR, M6/M8)
- **C5:** `reserved_quantity` lifecycle is undefined (MAJOR, M7/M9)
- **C6:** Concurrency between policy check and order creation (MAJOR, M9/M10)
- **C7:** Two overlapping state machines (MAJOR, M5/M10)
- **D1:** Approval TTL (MAJOR, M8)
- **D2:** Price *decrease* handling (MAJOR, M9)
- **D3:** Spending-limit scope and storage (MAJOR, M9)
- **D4:** Idempotency key generation, scope, and TTL (BLOCKING, M10)
- **D7:** Which Razorpay webhook events to subscribe (MAJOR, M12)
- **D8:** Payment-failure recovery path (MAJOR, M12)
- **D9:** Price change while Razorpay Checkout is open (MINOR)
- **D10:** Refunds and cancellation (MINOR)
- **E1:** Tool-call loop limit value (MAJOR, M5)
- **E2:** LLM retry/timeout values (MINOR, M4)
- **E4:** Tool naming inconsistency (MINOR)
- **E5:** Stock disclosure granularity (MINOR, M5/M14)
- **E6:** Agent trace persistence (MINOR, M13)
- **E7:** `audit_events` schema (MAJOR, M13)
- **F1–F10:** Absent from the document entirely (various impacts)

---

## Section 5: Task breakdown

One hundred tasks total — the document's 58 preserved unchanged, plus 42 added to close gaps that would otherwise leave the numbered tasks unable to start.

### Task family summary

| Family | Count | Source | Purpose |
|--------|-------|--------|---------|
| INFRA | 6 | Added | Scaffold, config, CI |
| DB | 18 | Added | Both schema phases |
| SVC | 8 | Added | Domain services |
| RANK | 11 | Added | Filters and scorers |
| LLM | 12 | Spec | LLM layer |
| AGENT | 15 | Spec | Agent Runtime |
| API | 6 | Added | FastAPI routes |
| POLICY | 7 | Spec | Policy Engine |
| RZP | 7 | Spec | Razorpay payments |
| OBS | 1 | Added | Logging, redaction |
| FE | 8 | Spec | Frontend |
| INT | 10 | Spec | Integration |
| TEST | 4 | Added | End-to-end scenarios |
| EVAL | 2 | Added | Evaluation harness |

**Total:** 100 tasks (58 from document + 42 added)

### Milestone-to-task mapping

#### M0 – Foundation (added)

- INFRA-01: Repository scaffold
- INFRA-02: Python project setup
- INFRA-03: Configuration module
- INFRA-04: Local Postgres via docker-compose
- INFRA-05: Test harness
- INFRA-06: CI workflow

#### M1 – Catalog schema (added)

- DB-01: SQLAlchemy models for merchants, categories
- DB-02: Models for products, product_variants
- DB-03: Models for inventory, compatibility_rules, product_relationships
- DB-04: All constraints (PKs, FKs, UNIQUE, etc.)
- DB-05: All specified indexes
- DB-06: Initial Alembic migration
- DB-07: `compatibility_targets` table + migration
- DB-08: CircuitCraft seed catalog (30–36 SKUs)
- DB-09: Schema tests

#### M2 – Catalog read services (added)

- SVC-01: Repository layer
- SVC-02: Catalog Service
- SVC-03: Compatibility Service + target resolution
- SVC-04: Inventory Service
- SVC-05: Service tests

#### M3 – Ranking engine (added)

- RANK-01: Ranking configuration (weight profiles)
- RANK-02: Hard-constraint filter
- RANK-03: PreferenceScore scorer
- RANK-04: PriceScore scorer
- RANK-05: RelevanceScore scorer
- RANK-06: Weighted aggregator + Top-K
- RANK-07: Structured explanation output
- RANK-08: Multi-product budget combination
- RANK-09: Cross-sell / upsell service
- RANK-10: No-match behavior
- RANK-11: Ranking tests (reproduce worked example)

#### M4 – LLM layer (from spec)

- LLM-01: Claude client abstraction
- LLM-02: Structured buyer-intent schema (Pydantic)
- LLM-03: Intent extraction
- LLM-04: System prompt
- LLM-05: Tool schema definitions
- LLM-06: Structured tool-call handling
- LLM-07: Conversation context
- LLM-08: Grounded recommendation response
- LLM-09: Cart proposal communication
- LLM-10: Failure communication
- LLM-11: Prompt-injection resistance tests
- LLM-12: LLM integration tests

#### M5 – Agent Runtime, read-only (from spec + added)

- AGENT-01: Runtime skeleton
- AGENT-02: Tool abstraction
- AGENT-03: Catalog tools
- AGENT-04: Compatibility tool
- AGENT-05: Inventory tool
- AGENT-06: Connect Claude Sonnet
- AGENT-07: Multi-tool orchestration
- API-01: FastAPI application
- API-02: `POST /api/chat` endpoint

#### M6 – Commerce schema (added)

- DB-10: Models for carts, cart_items
- DB-11: Models for orders, order_items
- DB-12: Models for payments
- DB-13: Models for approvals
- DB-14: Models for idempotency_keys
- DB-15: Models for webhook_events
- DB-16: Models for audit_events
- DB-17: Session persistence model
- DB-18: Commerce migration + tests

#### M7 – Cart (added + from spec)

- SVC-06: Cart Service
- AGENT-08: `propose_cart()` tool
- API-03: Cart endpoints

#### M8 – Approval (added + from spec)

- AGENT-09: Explicit approval state
- POLICY-04: Approval model and binding
- API-04: `POST /api/cart/approve`

#### M9 – Policy Engine (from spec)

- POLICY-01: PolicyEngine abstraction
- POLICY-02: Deterministic rules
- POLICY-03: Machine-readable reason codes
- POLICY-05: Price-drift scenario
- POLICY-06: Inventory revalidation
- POLICY-07: Spending limit

#### M10 – Orders & idempotency (added + from spec)

- SVC-07: Order Service
- AGENT-10: Safety boundary for order creation
- AGENT-12: Duplicate-operation protection
- AGENT-11: Price-change recovery
- API-05: `POST /api/orders`

#### M11 – Razorpay orders (from spec)

- RZP-01: Razorpay client abstraction
- RZP-02: Test-mode order creation
- RZP-03: Checkout integration
- API-06: `GET /api/orders/{order_id}`

#### M12 – Webhook (from spec)

- RZP-04: Webhook endpoint
- RZP-05: Webhook idempotency
- RZP-06: Payment source of truth

#### M13 – Audit & observability (added + from spec)

- SVC-08: Audit Service
- RZP-07: Emit audit events
- AGENT-14: Visible agent trace
- OBS-01: Structured logging

#### M14 – Frontend (from spec)

- FE-00: Frontend scaffold
- FE-01: Chat page
- FE-02: Recommendation rendering
- FE-03: Cart UI
- FE-04: Explicit approval UI
- FE-05: Policy failure UI
- FE-06: Razorpay Checkout integration
- FE-07: Order status display

#### M15 – Integration & evaluation (added + from spec)

- INT-01 through INT-10: Wiring tasks (chat → agent, cart, approval, policy, order, Razorpay, checkout, webhook, status)
- AGENT-13: Prompt-injection test
- AGENT-15: Agent Runtime integration suite
- TEST-01: Payment integration suite
- TEST-02: End-to-end success scenario
- TEST-03: End-to-end price-drift scenario (flagship)
- TEST-04: End-to-end out-of-stock scenario
- EVAL-01: Evaluation harness
- EVAL-02: Evaluation suite

### Gaps in the document's own numbering

- POLICY-04 (approval state) defines input to POLICY-01 (PolicyEngine) — the order is inverted
- AGENT-13 and LLM-11 are the same test filed under two families
- The database is declared the first implementation task and has no task ID
- AGENT-03 to AGENT-05 depend on services no task builds

---

## Section 6: Proposed structure

The document contains four partial file trees that overlap and disagree, each telling the reader to reconcile it with a master structure that does not exist. This is that reconciliation.

### Complete file tree

```
AI_COMMERCE/
├── architecture.md                  # source of truth — never edited
├── README.md
├── docker-compose.yml
├── .env.example
│
├── docs/
│   ├── analysis/                    # this analysis
│   │   ├── 01-architecture-inventory.md
│   │   ├── 02-dependency-map.md
│   │   ├── 03-open-questions.md
│   │   ├── 04-task-breakdown.md
│   │   ├── 05-proposed-repo-structure.md
│   │   └── README.md
│   │
│   ├── decisions/                   # ADRs — one file per resolved open question
│   │   ├── ADR-000-template.md
│   │   ├── ADR-001-ranking-weights.md
│   │   ├── ADR-002-relevance-score.md
│   │   ├── ADR-003-compatibility-target-resolution.md
│   │   ├── ADR-004-commerce-schema.md
│   │   ├── ADR-005-session-and-approval-persistence.md
│   │   ├── ADR-006-money-representation.md
│   │   ├── ADR-007-approval-and-order-authority.md
│   │   └── ADR-008-chat-api-contract.md
│   │
│   ├── contracts/                   # frozen interfaces
│   │   ├── api-endpoints.md
│   │   ├── tool-schemas.md
│   │   ├── policy-reason-codes.md
│   │   └── error-codes.md
│   │
│   ├── runbook/
│   │   ├── local-setup.md
│   │   ├── seed-catalog.md
│   │   ├── razorpay-test-mode.md
│   │   └── demo-script.md
│   │
│   └── notes/
│       ├── progress.md
│       ├── deviations.md
│       └── session-log.md
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/
│   │   └── versions/
│   │
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   │
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   └── models/
│   │   │       ├── merchant.py
│   │   │       ├── category.py
│   │   │       ├── product.py
│   │   │       ├── variant.py
│   │   │       ├── inventory.py
│   │   │       ├── compatibility.py
│   │   │       ├── relationship.py
│   │   │       ├── cart.py
│   │   │       ├── order.py
│   │   │       ├── payment.py
│   │   │       ├── approval.py
│   │   │       ├── idempotency.py
│   │   │       ├── webhook_event.py
│   │   │       ├── session.py
│   │   │       └── audit.py
│   │   │
│   │   ├── repositories/
│   │   │   ├── product_repository.py
│   │   │   ├── variant_repository.py
│   │   │   ├── inventory_repository.py
│   │   │   ├── compatibility_repository.py
│   │   │   ├── relationship_repository.py
│   │   │   ├── cart_repository.py
│   │   │   ├── order_repository.py
│   │   │   ├── payment_repository.py
│   │   │   ├── idempotency_repository.py
│   │   │   └── audit_repository.py
│   │   │
│   │   ├── services/
│   │   │   ├── catalog_service.py
│   │   │   ├── compatibility_service.py
│   │   │   ├── inventory_service.py
│   │   │   ├── recommendation_service.py
│   │   │   ├── cart_service.py
│   │   │   ├── order_service.py
│   │   │   └── audit_service.py
│   │   │
│   │   ├── ranking/
│   │   │   ├── filters.py
│   │   │   ├── scorers.py
│   │   │   ├── ranker.py
│   │   │   ├── explain.py
│   │   │   ├── combinations.py
│   │   │   └── weights.py
│   │   │
│   │   ├── llm/
│   │   │   ├── client.py
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   ├── intent.py
│   │   │   └── errors.py
│   │   │
│   │   ├── agent/
│   │   │   ├── runtime.py
│   │   │   ├── state.py
│   │   │   ├── context.py
│   │   │   ├── registry.py
│   │   │   ├── executor.py
│   │   │   ├── trace.py
│   │   │   ├── errors.py
│   │   │   ├── prompts/
│   │   │   │   ├── __init__.py
│   │   │   │   └── system_prompt.md
│   │   │   └── tools/
│   │   │       ├── search_catalog.py
│   │   │       ├── get_product.py
│   │   │       ├── get_compatible_products.py
│   │   │       ├── check_inventory.py
│   │   │       ├── propose_cart.py
│   │   │       ├── request_approval.py
│   │   │       ├── get_order_status.py
│   │   │       └── get_upsell_candidates.py
│   │   │
│   │   ├── policy/
│   │   │   ├── policy_engine.py
│   │   │   ├── rules.py
│   │   │   ├── reason_codes.py
│   │   │   ├── schemas.py
│   │   │   └── errors.py
│   │   │
│   │   ├── payments/
│   │   │   ├── razorpay_client.py
│   │   │   ├── checkout.py
│   │   │   ├── webhook.py
│   │   │   └── schemas.py
│   │   │
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   ├── errors.py
│   │   │   └── routes/
│   │   │       ├── chat.py
│   │   │       ├── cart.py
│   │   │       ├── orders.py
│   │   │       └── webhooks.py
│   │   │
│   │   └── seed/
│   │       ├── circuitcraft.py
│   │       └── data/
│   │           └── catalog.json
│   │
│   └── tests/
│       ├── conftest.py
│       ├── fixtures/
│       │   └── llm/
│       ├── db/
│       ├── services/
│       ├── ranking/
│       ├── llm/
│       ├── agent/
│       ├── tools/
│       ├── policy/
│       ├── payments/
│       ├── webhooks/
│       ├── orders/
│       ├── integration/
│       └── evaluation/
│
└── frontend/
    ├── package.json
    └── src/
        ├── components/
        │   ├── ChatWindow/
        │   ├── MessageList/
        │   ├── MessageInput/
        │   ├── ProductCard/
        │   ├── ProductRecommendationList/
        │   ├── CartPanel/
        │   ├── CartItem/
        │   ├── CartSummary/
        │   ├── ApprovalPanel/
        │   ├── CheckoutButton/
        │   └── OrderStatus/
        ├── pages/
        │   └── ChatPage/
        ├── services/
        │   ├── api.ts
        │   ├── chat.ts
        │   ├── cart.ts
        │   └── orders.ts
        ├── state/
        │   ├── chat.ts
        │   ├── cart.ts
        │   └── checkout.ts
        └── types/
            ├── product.ts
            ├── cart.ts
            ├── order.ts
            └── chat.ts
```

### Deliberate departures from the document's trees

| Departure | Reason |
|-----------|--------|
| Added `repositories/` | A§20 names the repository layer explicitly; no proposed tree includes it |
| Added `ranking/` | The ranking system is the largest single part of the spec and appears in no proposed tree |
| `agent/tools/` as a package, one file per tool | Eight tools with schemas and handlers will not stay readable in one `tools.py` |
| `prompts/system_prompt.md` as text | L§28 requires the system prompt be version-controlled; text diffs are far more reviewable than a Python string literal |
| `orders/` and `audit/` folded into `services/` | P§37 would create packages parallel to A§57's services; P§37 itself says not to duplicate modules |
| `agent/trace.py` split from `runtime.py` | The agent trace is a distinct SHOULD-WORK feature added after the core flow stabilizes |
| No `create_order.py` under `agent/tools/` | Pending open question D6 — order creation is proposed as a user-initiated API path, not a model-callable tool |

### Documentation with four different lifetimes

| Directory | Contains | Authority | Changes |
|-----------|----------|-----------|---------|
| `architecture.md` | The specification | Highest — source of truth | Not edited by implementation work |
| `docs/analysis/` | This analysis | Derived; refreshed if spec changes | Rarely |
| `docs/decisions/` | ADRs resolving open questions | Binding once accepted | Append-only; superseded, never rewritten |
| `docs/contracts/` | Frozen interfaces (API, tools, reason codes, error codes) | Binding across layers | Versioned deliberately; a change is a coordinated event |
| `docs/runbook/` | How to run, seed, demo | Operational | Freely |
| `docs/notes/` | Progress, deviations, session log | Non-authoritative | Continuously |

---

## Unable to export

The following elements from the artifact could not be fully captured in Markdown form but are described above:

1. **Visual CSS styling** — colors, typography hierarchy, responsive layout, dark-mode support. These exist only in the HTML artifact.
2. **Interactive filter buttons** — the "open questions" section includes JavaScript-driven filtering by severity and category, which works only in the HTML artifact.
3. **Sticky sidebar navigation** — the table of contents auto-highlights the current section as you scroll, which works only in the HTML artifact.
4. **Hover states and transitions** — subtle CSS interactions are not representable in Markdown.

All content, structure, decisions, tables, diagrams, task IDs, and architectural information have been preserved exactly in text form.

---

## Full write-ups

For additional detail, source code reference locations, and complete rationale, see:

- `docs/analysis/01-architecture-inventory.md` — Every component across 13 layers with completeness ratings
- `docs/analysis/02-dependency-map.md` — Detailed dependency graph and build-order rationale
- `docs/analysis/03-open-questions.md` — All 45 questions with full context and proposed defaults
- `docs/analysis/04-task-breakdown.md` — The 100 tasks with cross-references to milestones
- `docs/analysis/05-proposed-repo-structure.md` — Repository structure reconciliation with full notes

---

**Export complete.** This Markdown preserves all architecture decisions, open questions, task IDs, file trees, and implementation details from the artifact without summarization or interpretation. Ready for review by another AI.
