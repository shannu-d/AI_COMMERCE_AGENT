# Proposed Repository, Documentation & Notes Structure

`architecture.md` contains **four partial file trees** — LLM (L§50), Agent Runtime
(A§57), Policy + Payments (P§37), and Frontend (F§30) — and each one says the same
thing: reconcile me with the master repository structure before coding. Three of the
four overlap and disagree in small ways.

This document is that reconciliation. It is a **proposal**; no directories beyond
`docs/analysis/` have been created.

## 1. Reconciling the four partial trees

| Conflict | L§50 | A§57 | P§37 | Resolution |
| --- | --- | --- | --- | --- |
| Agent module contents | runtime, prompts, context, state, tools | + registry, executor, errors | — | Take the A§57 superset |
| LLM module contents | client, models, schemas, intent, errors | client, schemas, models | — | Take the L§50 superset |
| Prompt location | `agent/prompts.py` | `agent/prompts.py` | — | Keep under `agent/`; version-control prompt text as separate files |
| Policy location | not shown | `policy/policy_engine.py` | `policy/` with rules, schemas, errors | Take the P§37 superset |
| Orders | not shown | `services/order_service.py` | `orders/` package with service, repository, schemas | Use a single `services/order_service.py` + shared `repositories/`; do not create a parallel `orders/` package |
| Audit | not shown | `services/audit_service.py` | `audit/` package | Same — one `services/audit_service.py` |
| Repositories | absent from all three | mentioned in prose (A§20) only | absent | Add an explicit `repositories/` package — the layer is named in the architecture but missing from every tree |

Two rules govern the merge, both stated by the document itself: *"integrate with the
existing repository structure rather than blindly creating duplicate modules"* (P§37) and
*"do not create duplicate APIs if equivalent services already exist"* (F§26).

## 2. Proposed repository layout

```
AI_COMMERCE/
├── architecture.md                  # source of truth — never edited by implementation work
├── README.md                        # what this is, how to run it
├── docker-compose.yml               # Postgres for local development
├── .env.example                     # placeholder values only, never real secrets
│
├── docs/
│   ├── analysis/                    # this analysis (already created)
│   │   ├── 01-architecture-inventory.md
│   │   ├── 02-dependency-map.md
│   │   ├── 03-open-questions.md
│   │   ├── 04-task-breakdown.md
│   │   └── 05-proposed-repo-structure.md
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
│   ├── contracts/                   # frozen interfaces other layers build against
│   │   ├── api-endpoints.md
│   │   ├── tool-schemas.md
│   │   ├── policy-reason-codes.md
│   │   └── error-codes.md
│   │
│   ├── runbook/
│   │   ├── local-setup.md
│   │   ├── seed-catalog.md
│   │   ├── razorpay-test-mode.md
│   │   └── demo-script.md           # the success + price-drift walkthrough
│   │
│   └── notes/                       # working notes, not authoritative
│       ├── progress.md              # milestone status, updated as work lands
│       ├── deviations.md            # every place the build departs from architecture.md, and why
│       └── session-log.md           # what happened in each working session
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/
│   │   └── versions/
│   │
│   ├── app/
│   │   ├── main.py                  # FastAPI application factory
│   │   ├── config.py                # typed settings from environment
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
│   │   ├── repositories/            # named in A§20, absent from every proposed tree
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
│   │   ├── ranking/                 # the whole first part of architecture.md lives here
│   │   │   ├── filters.py           # hard-constraint filtering
│   │   │   ├── scorers.py           # preference, price, relevance, compatibility
│   │   │   ├── ranker.py            # weighted aggregation + Top-K
│   │   │   ├── explain.py           # structured explanation output
│   │   │   ├── combinations.py      # multi-product budget combination
│   │   │   └── weights.py           # configurable weight profiles
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
│   │   │   │   └── system_prompt.md     # version-controlled prompt text
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
│   │           └── catalog.json     # the 30–36 SKU catalog
│   │
│   └── tests/
│       ├── conftest.py
│       ├── fixtures/
│       │   └── llm/                 # recorded Claude responses for deterministic CI
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
| --- | --- |
| Added `repositories/` | A§20 names the repository layer explicitly; no proposed tree includes it |
| Added `ranking/` | The ranking system is the largest single part of `architecture.md` and appears in no proposed tree |
| `agent/tools/` as a package, one file per tool | Eight tools with schemas and handlers will not stay readable in one `tools.py` |
| `prompts/system_prompt.md` as text | L§28 requires the system prompt be version-controlled; text diffs are far more reviewable than a Python string literal |
| `orders/` and `audit/` folded into `services/` | P§37 would create packages parallel to A§57's services; P§37 itself says not to duplicate modules |
| `agent/trace.py` split from `runtime.py` | The agent trace is a distinct SHOULD-WORK feature added after the core flow stabilizes |
| No `create_order.py` under `agent/tools/` | Pending open question **D6** — order creation is proposed as a user-initiated API path, not a model-callable tool |

## 3. Documentation structure

Four kinds of document, kept apart because they have different lifetimes and different
authority:

| Directory | Contains | Authority | Changes |
| --- | --- | --- | --- |
| `architecture.md` | The specification | Highest — the source of truth | Not edited by implementation work |
| `docs/analysis/` | This analysis | Derived; refreshed if the spec changes | Rarely |
| `docs/decisions/` | ADRs resolving open questions | Binding once accepted | Append-only; superseded, never rewritten |
| `docs/contracts/` | Frozen interfaces (API, tools, reason codes, error codes) | Binding across layers | Versioned deliberately; a change is a coordinated event |
| `docs/runbook/` | How to run, seed, demo | Operational | Freely |
| `docs/notes/` | Progress, deviations, session log | Non-authoritative | Continuously |

**ADR template** (`docs/decisions/ADR-000-template.md`):

```
# ADR-NNN: <title>

Status:        Proposed | Accepted | Superseded by ADR-NNN
Date:          YYYY-MM-DD
Open question: <ID from docs/analysis/03-open-questions.md>
Milestone:     <M#>

## Context
What architecture.md says, and precisely what it leaves open.

## Decision
The chosen resolution, stated so code can be written against it.

## Consequences
What this enables, what it forecloses, what it costs.

## Alternatives considered
What else was on the table and why it lost.
```

The `deviations.md` note is the important one for this project: because
`architecture.md` is the source of truth and is not to be edited, every place the
implementation resolves an ambiguity or departs from the letter of the spec needs a
traceable record — open question ID, ADR number, and the code it affects.

## 4. Suggested working conventions

1. **One milestone per working session.** The document is emphatic (D§39, A§58, F§37)
   that this must not be built in one pass.
2. **Freeze contracts before dependent work.** The frontend and the agent both build
   against `POST /api/chat`; that contract is written into `docs/contracts/` and agreed
   before either starts.
3. **Every open question gets an ADR before its milestone starts,** not after.
4. **Tests land with their milestone,** since almost every milestone's exit condition in
   the document is phrased as a test.
5. **Never edit `architecture.md`** — corrections go into ADRs and `deviations.md`.
