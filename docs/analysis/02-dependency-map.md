# Dependency Map & Implementation Order

## 1. The dependency spine

Every component in the system sits on this chain. Nothing above a line can be built
honestly before the thing below it exists.

```
                         Frontend (React/Next)
                                  |
                            FastAPI routes
                                  |
                 +----------------+----------------+
                 |                                 |
          Agent Runtime                     Cart / Order APIs
                 |                                 |
        +--------+--------+                        |
        |                 |                        |
   LLM client        Tool registry                 |
   + prompts         + handlers                    |
        |                 |                        |
        +--------+--------+------------------------+
                          |
                    Policy Engine  <-- gate before any money moves
                          |
        +-----------------+-----------------+
        |                 |                 |
  Recommendation    Cart Service      Order Service --> Razorpay --> Webhook
     Service              |                 |
        |                 |                 |
   +----+----+------------+-----------------+
   |         |            |
 Catalog  Compat.     Inventory        Audit Service
 Service  Service      Service
   |         |            |                 |
   +---------+------------+-----------------+
                          |
                    Repository layer
                          |
                     SQLAlchemy
                          |
                      PostgreSQL
                (catalog + commerce schema)
```

## 2. Component-level dependency table

Read as "X cannot be completed until Y exists."

| Component | Hard dependencies |
| --- | --- |
| Repositories | Phase-1 tables + Alembic + SQLAlchemy session |
| Catalog Service | ProductRepository, VariantRepository |
| Compatibility Service | CompatibilityRepository, **device-identifier canonicalization** (undefined) |
| Inventory Service | InventoryRepository |
| Recommendation Service | Catalog + Compatibility + Inventory services, ranking weight config, **RelevanceScore definition** (undefined) |
| Cross-sell recommender | RelationshipRepository, Compatibility Service, Inventory Service |
| Tool T-1/T-2 | Catalog Service |
| Tool T-3 | Compatibility Service |
| Tool T-4 | Inventory Service |
| Tool T-5 `propose_cart` | Cart Service → carts/cart_items tables |
| Tool T-6 `request_approval` | Approval state model → approvals table |
| Tool T-7 `create_order` | Policy Engine + Order Service + idempotency store |
| Tool T-8 `get_order_status` | Order Service + Payment state |
| Tool registry | Tool interface + Pydantic schemas |
| Agent Runtime loop | LLM client, tool registry, session store, state machine, error model |
| `POST /api/chat` | Agent Runtime |
| Cart APIs | Cart Service, cart versioning |
| `POST /api/cart/approve` | Approval model + Policy Engine |
| Policy Engine | Catalog (live price), Inventory (live stock), Cart (+version), Approval, Order state, Idempotency store, spending-limit config |
| Order Service | Policy Engine PASS, orders/order_items tables, idempotency store |
| Razorpay client | Config/secrets |
| Razorpay order creation | Order Service + Razorpay client |
| Checkout handoff | Razorpay order creation |
| Webhook endpoint | Raw-body middleware, webhook secret, payments table, webhook_events table, Audit Service |
| Audit Service | audit_events table |
| Agent trace | Agent Runtime instrumentation |
| Frontend chat | `POST /api/chat` returning a **structured** recommendations payload |
| Frontend cart | Cart APIs |
| Frontend approval | `POST /api/cart/approve` + policy reason codes |
| Frontend checkout | Razorpay order info endpoint + public key |
| Frontend order status | `GET /api/orders/{id}` driven by verified webhook state |
| E2E price-drift scenario | Policy price rule + approval versioning + fresh idempotency key + frontend recovery UI |

## 3. Ordering conflict in the source document

Two parts of `architecture.md` give incompatible ordering advice, and this must be
resolved before work starts.

- **D§36 / D§39** say the first milestone is catalog-only and explicitly list `cart`,
  `cart_items`, `orders`, `order_items`, `payments`, `audit_events` as "do NOT implement
  in the first catalog milestone."
- **F§37** ("What you should build first") sequences: database → catalog APIs →
  compatibility → ranking → Agent Runtime → tool calling → **cart** → Policy Engine →
  Razorpay → webhook → frontend → integration → flagship failure scenario.

These agree if "first milestone" is read as *milestone 1 of many*, with the commerce
tables arriving as their own later schema milestone. **Recommended resolution:** treat
the commerce schema as a distinct migration milestone (M6 below) that lands immediately
before Cart Service, rather than either bundling it into M1 or deferring it past the
Agent Runtime.

## 4. Recommended implementation order

Milestones are sequenced so that every milestone is independently demonstrable and each
one only depends on milestones before it.

| # | Milestone | Contains | Exit condition |
| --- | --- | --- | --- |
| M0 | Foundation | Repo scaffold, config/env loading, `.env.example`, Postgres via compose, lint/format, pytest harness | `pytest` runs green on an empty suite; app boots |
| M1 | Catalog schema | 7 Phase-1 tables, ORM models, relationships, constraints, indexes, Alembic migration, CircuitCraft seed (30–36 SKUs), model tests | Migration up/down clean; seed loads; constraint tests pass |
| M2 | Catalog read services | Repositories, Catalog / Compatibility / Inventory services + tests | Given a device + budget, service returns correct filtered products |
| M3 | Ranking engine | Hard-constraint filter, four feature scorers, weighted aggregator, Top-K, weight config, ranking tests | Worked example from R§10 reproduces the documented scores |
| M4 | LLM layer | Claude client, intent schema, intent extraction, system prompt, tool schema definitions, output validation | Natural language → validated structured intent, offline-testable |
| M5 | Agent Runtime (read-only) | Runtime loop, session/context, state machine, tool registry, executor, validation pipeline, loop limit, error model, tools T-1..T-4, `POST /api/chat` | "Find me a case for iPhone 16 under ₹1500" returns grounded Top-3 |
| M6 | Commerce schema | carts, cart_items, orders, order_items, payments, audit_events, approvals, idempotency_keys, webhook_events, sessions (+ users if adopted) | Migration clean; FK integrity tests pass |
| M7 | Cart | Cart Service, cart versioning, authoritative totals, `propose_cart` tool, cart APIs | Cart total is backend-computed; version increments on mutation |
| M8 | Approval | Approval model bound to cart+version+total, stale detection, `request_approval`, `POST /api/cart/approve` | Stale approval is rejected by test |
| M9 | Policy Engine | PolicyEngine, 8 rules, reason codes, TransactionContext/PolicyDecision schemas, per-rule tests | Price-drift and out-of-stock tests both FAIL correctly with the right reason code |
| M10 | Orders + idempotency | Order Service, order state machine, idempotency key lifecycle, `create_order` gating | Duplicate request produces exactly one logical order |
| M11 | Razorpay orders | Razorpay client, test-mode order creation, internal↔Razorpay mapping, checkout config endpoint | Policy PASS produces a real test-mode Razorpay order |
| M12 | Webhook | Raw-body capture, signature verification, event-ID dedupe, order-independent handling, payment state update | Invalid signature rejected; duplicate event causes one transition |
| M13 | Audit + trace | Audit Service, the 12 named audit events, agent trace | Full transaction reconstructable from audit events |
| M14 | Frontend | FE-01..FE-07 built against already-working APIs | Definition-of-done checklist in F§33 |
| M15 | Integration & evaluation | INT-01..INT-10, E2E success, price drift, out of stock, duplicate, prompt injection, eval suite | Flagship failure scenario demonstrable end to end |

## 5. Critical path

The shortest chain to the flagship demo is:

**M1 → M2 → M3 → M5 → M6 → M7 → M8 → M9 → M10 → M11 → M12**

M4 can proceed in parallel with M2–M3. M13 (audit/trace) and M14 (frontend) can be
developed alongside M9–M12 once their API contracts are frozen. M15 depends on
everything.

## 6. Parallelizable work

| Track | Milestones | Can start after |
| --- | --- | --- |
| Data & catalog | M1, M2, M3 | M0 |
| AI | M4 | M0 (schema-only work), M2 for real tool wiring |
| Commerce & money | M6..M12 | M1 for schema, M5 for agent integration |
| Frontend | M14 | Frozen contracts from M5, M7, M8, M11 |
| Quality | M15 fixtures | Continuously, per milestone |

## 7. Highest-risk dependencies

1. **RelevanceScore is undefined** (blocks M3 from being fully deterministic).
2. **Device-identifier canonicalization is unspecified** (blocks M2 compatibility from
   working on real natural-language input).
3. **Phase-2 schema has no column definitions** (blocks M6, which the entire money path
   sits on).
4. **Approval/session persistence is explicitly deferred** (blocks M8, which the Policy
   Engine depends on).
5. **Money representation** — NUMERIC(12,2) in Postgres vs Razorpay's integer minor
   units — is never reconciled (silent correctness risk at M11).
