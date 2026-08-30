# Architecture Inventory

Derived from `architecture.md` (16,736 lines, six parts). This inventory names every
architectural component the document specifies or implies, its responsibility, and how
completely the source document specifies it.

**Spec completeness legend**

| Mark | Meaning |
| --- | --- |
| FULL | Columns / signatures / rules given explicitly. Implementable as written. |
| PARTIAL | Purpose and shape given, but a decision or formula is missing. |
| IMPLIED | Required by other sections but never defined as a component. |

Source-part shorthand: **R** = Ranking System, **D** = PostgreSQL Database, **L** = LLM
Architecture, **A** = Agent Runtime, **P** = Policy + Razorpay, **F** = Frontend + E2E.

---

## Layer 0 — Infrastructure & cross-cutting

| ID | Component | Responsibility | Spec | Ref |
| --- | --- | --- | --- | --- |
| INF-1 | Config & secrets loader | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, DB URL. `.env.example` with no real values. Never in prompts, frontend, or API responses. | PARTIAL | L§45, P-RZP-01 |
| INF-2 | PostgreSQL instance | Authoritative store for catalog and commerce state. | FULL | D§2 |
| INF-3 | Alembic migrations | Versioned schema evolution. | FULL | D§38 |
| INF-4 | SQLAlchemy engine / session management | ORM + unit-of-work boundary. | PARTIAL | D§38 |
| INF-5 | Ranking weight configuration | Weights stored as configuration, not hard-coded. | PARTIAL | R§19, R-RULE-14 |
| INF-6 | Policy configuration | Spending limit and related deterministic thresholds. | PARTIAL | P§13 |
| INF-7 | Test harness | pytest-style suites per layer; no framework named. | IMPLIED | — |
| INF-8 | Local dev orchestration (Docker/compose) | Not mentioned anywhere in the document. | IMPLIED | — |
| INF-9 | CI pipeline | Not mentioned anywhere in the document. | IMPLIED | — |

## Layer 1 — Persistence, Phase 1 (catalog)

Fully specified with columns, types, keys, constraints, and indexes. This is the only
part of the schema the document defines at column level.

| ID | Table | Key columns | Constraints | Spec |
| --- | --- | --- | --- | --- |
| DB-1 | `merchants` | id, name, description, currency, is_active, created_at, updated_at | PK uuid | FULL |
| DB-2 | `categories` | id, merchant_id, name, slug, parent_id, timestamps | FK merchant, self-FK parent, `UNIQUE(merchant_id, slug)` | FULL |
| DB-3 | `products` | id, merchant_id, category_id, name, slug, description, brand, attributes JSONB, tags TEXT[], is_active, timestamps | FK merchant, FK category, `UNIQUE(merchant_id, slug)` | FULL |
| DB-4 | `product_variants` | id, merchant_id, product_id, sku, name, price NUMERIC(12,2), currency, attributes JSONB, is_active, timestamps | FK merchant, FK product, `UNIQUE(merchant_id, sku)` | FULL |
| DB-5 | `inventory` | id, variant_id, quantity, reserved_quantity, updated_at | FK variant, `UNIQUE(variant_id)` | FULL |
| DB-6 | `compatibility_rules` | id, product_id, target_type, target_identifier, rule_type, constraints JSONB, timestamps | FK product, index `(target_type, target_identifier)` | PARTIAL (semantics of `constraints`, enum of `rule_type`) |
| DB-7 | `product_relationships` | id, source_product_id, target_product_id, relationship_type, priority, created_at | two FKs to products, index on source | FULL |

Indexes specified: `products(merchant_id)`, `products(category_id)`,
`products(merchant_id, category_id)`, `products(is_active)`,
`product_variants(merchant_id, sku)` unique,
`compatibility_rules(target_type, target_identifier)`,
`product_relationships(source_product_id)`. GIN indexes on `tags` / `attributes` are
deferred until query patterns justify them.

## Layer 2 — Persistence, Phase 2 (commerce)

The database part calls these "future" and tells the first milestone not to build them
(D§36, D§39). The Policy, Payment, and Frontend parts then depend on all of them. **No
column-level schema is given for any table in this layer** — this is the single largest
specification gap in the document.

| ID | Table | Required by | Spec |
| --- | --- | --- | --- |
| DB-8 | `carts` | Cart service, cart versioning, policy approval binding | PARTIAL (needs `cart_version`) |
| DB-9 | `cart_items` | Cart totals, policy item validation | PARTIAL |
| DB-10 | `orders` | Order service, order state machine, Razorpay order mapping | PARTIAL (P§29 sketches `internal_order_id`, `razorpay_order_id`, `status`, `amount`) |
| DB-11 | `order_items` | Order line detail | IMPLIED |
| DB-12 | `payments` | Payment state from verified webhook | PARTIAL (P§29 sketches `payment_id`, `razorpay_payment_id`, `order_id`, `status`, `amount`) |
| DB-13 | `audit_events` | Append-style audit trail (a MUST-WORK component per A§40) | PARTIAL (event names listed in P-RZP-07, no columns) |
| DB-14 | `approvals` | Approval tied to user/session + cart + cart_version + approved total | IMPLIED (P§10, POLICY-04) |
| DB-15 | `idempotency_keys` | Duplicate order protection, fresh key after price drift | IMPLIED (P§15–16) |
| DB-16 | `webhook_events` | Razorpay `event_id` dedupe store | IMPLIED (P§25–26) |
| DB-17 | `sessions` | Session/conversation persistence — persistence strategy explicitly deferred | IMPLIED (A§38) |
| DB-18 | `users` | `user_id` appears in the policy input; no user table anywhere | IMPLIED (P§5) |

## Layer 3 — Repositories

Named as a layer (A§20: Runtime → Tool Handler → Service → Repository → PostgreSQL) but
never enumerated. Derived from the tables above.

`ProductRepository`, `VariantRepository`, `InventoryRepository`,
`CompatibilityRepository`, `RelationshipRepository`, `CartRepository`,
`OrderRepository`, `PaymentRepository`, `AuditRepository`, `IdempotencyRepository`,
`WebhookEventRepository`. Spec: IMPLIED throughout.

## Layer 4 — Domain services

Responsibilities are enumerated in A§21 and R§20.

| ID | Service | Responsibility | Spec |
| --- | --- | --- | --- |
| SVC-1 | Catalog Service | Product/variant retrieval, SKU lookup, catalog search, authoritative price retrieval | PARTIAL |
| SVC-2 | Compatibility Service | Compatibility validation, compatible-product retrieval | PARTIAL |
| SVC-3 | Inventory Service | Availability, quantity validation, pre-order re-check | PARTIAL |
| SVC-4 | Recommendation Service | Candidate filtering, ranking, Top-K | PARTIAL |
| SVC-5 | Cart Service | Cart creation, item validation, authoritative total, cart versioning | PARTIAL |
| SVC-6 | Order Service | Order creation, order state | PARTIAL |
| SVC-7 | Payment Service | Razorpay interaction, payment state | FULL-ish |
| SVC-8 | Audit Service | Append-style action/decision/payment trail | PARTIAL |

## Layer 5 — Recommendation / ranking engine

The pipeline is: category → budget → compatibility → required-spec → inventory hard
filters, then normalized feature scoring, then weighted sum, then Top-K (target: Top 3).

| ID | Component | Definition given | Spec |
| --- | --- | --- | --- |
| RNK-1 | Hard-constraint filter | Merchant, category, budget, device/model, required spec, compatibility, quantity availability, existence | FULL |
| RNK-2 | CompatibilityScore | Binary 1.0/0.0; preferred design removes incompatible before ranking | FULL |
| RNK-3 | PreferenceScore | `matched_preferences / total_preferences` | PARTIAL (zero-preference case undefined) |
| RNK-4 | PriceScore | `1 - (price / max_budget)` | PARTIAL (no-budget case undefined; explicitly labelled a replaceable MVP choice) |
| RNK-5 | RelevanceScore | Signals listed (category, name, description, tags, requested attributes, spec); **no formula** | PARTIAL — the largest algorithmic gap |
| RNK-6 | Weighted aggregator | `Σ Weight_i × FeatureScore_i` | PARTIAL (two competing weight sets — see open questions) |
| RNK-7 | Top-K selector | Top 3 | FULL |
| RNK-8 | Multi-product budget combiner | "evaluates valid combinations against the overall budget" — no algorithm | PARTIAL |
| RNK-9 | Cross-sell / upsell recommender | Must be grounded in compatibility, catalog, bundle rules, user intent | PARTIAL |
| RNK-10 | Dynamic weight adjustment from intent | Described as a later capability; weights adapt to expressed intent | PARTIAL |
| RNK-11 | No-match behavior | Never fabricate; may offer real alternatives, labelled as alternatives not exact matches | FULL |

## Layer 6 — Policy Engine

The deterministic safety boundary between the agent and money.

| ID | Component | Spec |
| --- | --- | --- |
| POL-1 | `PolicyEngine` (TransactionContext → PolicyDecision) | FULL |
| POL-2 | Approval rule (explicit approval exists) | FULL |
| POL-3 | Cart validity rule | PARTIAL |
| POL-4 | Product / variant validity rule | FULL |
| POL-5 | Price rule (live re-fetch, compare to approved total) | FULL |
| POL-6 | Inventory rule (live re-check) | FULL |
| POL-7 | Quantity rule | PARTIAL |
| POL-8 | Spending-limit rule | PARTIAL (scope and storage undecided) |
| POL-9 | Order-state rule | PARTIAL |
| POL-10 | Idempotency rule | PARTIAL |
| POL-11 | Reason codes | FULL — `APPROVAL_REQUIRED`, `PRICE_CHANGED`, `OUT_OF_STOCK`, `INVALID_PRODUCT`, `SPENDING_LIMIT_EXCEEDED`, `ORDER_ALREADY_EXISTS`, `INVALID_CART` |
| POL-12 | Approval state model (user/session + cart + cart_version + approved total, stale detection) | PARTIAL (no TTL) |

## Layer 7 — LLM layer

Model: Claude Sonnet via the Anthropic API. Treated throughout as a **probabilistic,
non-authoritative** component whose output is untrusted input.

| ID | Component | Spec |
| --- | --- | --- |
| LLM-1 | Claude client abstraction (env-based key, model config, timeout, bounded retry) | PARTIAL (no values) |
| LLM-2 | System prompt (12 enumerated behavioral rules, version-controlled) | FULL as a list of requirements |
| LLM-3 | Structured buyer-intent schema (product_requirements, compatibility_requirements, budget, preferences, quantity) — Pydantic | PARTIAL (explicitly "not necessarily the final schema") |
| LLM-4 | Intent extraction | PARTIAL |
| LLM-5 | Clarification detection (required vs optional information) | FULL as a rule |
| LLM-6 | Tool schema definitions | PARTIAL (shapes illustrative) |
| LLM-7 | Model-output validation (LLM output = untrusted proposal) | FULL as a rule |
| LLM-8 | Output categorization (7 kinds: NL response, intent, tool call, tool result, cart proposal, clarification, final explanation) | FULL |
| LLM-9 | Retry / timeout / rate-limit / malformed-output handling | PARTIAL (no values) |
| LLM-10 | Context & token control | FULL as a rule |

## Layer 8 — Agent Runtime

The orchestration layer between FastAPI and Claude. Explicitly *not* the LLM.

| ID | Component | Spec |
| --- | --- | --- |
| AR-1 | Runtime loop (call model → tool? → validate → execute → return result → repeat) | FULL |
| AR-2 | Session store (session_id, history, intent, candidates, selection, cart, cart version, approval, policy, order, payment) | PARTIAL (persistence deferred) |
| AR-3 | Conversation context manager (multi-turn intent accumulation) | FULL as a rule |
| AR-4 | Agent state machine — 14 states + 7 failure states | PARTIAL ("exact state machine finalized during implementation") |
| AR-5 | Tool registry (name, description, input schema, handler, output schema) | FULL |
| AR-6 | Tool executor / handler layer | FULL |
| AR-7 | Tool-argument validation pipeline (parse → schema → authorization → business → execute) | FULL |
| AR-8 | Tool-result formatter (structured, small, relevant, validated; no raw rows, no secrets) | FULL |
| AR-9 | Loop limiter + termination conditions (6 listed) | PARTIAL (limit value undecided) |
| AR-10 | Agent trace (SHOULD-WORK) | PARTIAL (persistence undecided) |
| AR-11 | Structured error model (`{success:false, error:{code, message}}`) | FULL |
| AR-12 | Tool permission tiers (low / medium / high / financial) | FULL |
| AR-13 | Idempotency orchestration | PARTIAL |

## Layer 9 — Tools

| ID | Tool | Risk tier | Spec |
| --- | --- | --- | --- |
| T-1 | `search_catalog(category, search_query, max_price, currency, attributes)` | low | PARTIAL |
| T-2 | `get_product(product_id)` | low | PARTIAL |
| T-3 | `get_compatible_products(target_type, target_identifier)` | low | PARTIAL |
| T-4 | `check_inventory(variant_id, quantity)` | low | FULL |
| T-5 | `propose_cart(items[])` | medium | PARTIAL |
| T-6 | `request_approval(...)` | medium | PARTIAL — semantics ambiguous |
| T-7 | `create_order(...)` | high | PARTIAL — exposure to the model ambiguous |
| T-8 | `get_order_status(order_id)` | low | FULL |
| T-9 | `get_upsell_candidates(...)` | low | Optional, PARTIAL |

## Layer 10 — API (FastAPI)

| ID | Endpoint | Spec |
| --- | --- | --- |
| API-1 | `POST /api/chat` | PARTIAL — two conflicting response shapes given |
| API-2 | `GET /api/cart` | IMPLIED |
| API-3 | `POST/PATCH/DELETE /api/cart/items[/{id}]` | PARTIAL |
| API-4 | `POST /api/cart/approve` | PARTIAL |
| API-5 | `POST /api/orders` | IMPLIED |
| API-6 | `GET /api/orders/{order_id}` | PARTIAL |
| API-7 | `POST /api/webhooks/razorpay` | FULL |
| API-8 | Uniform error model (11 named error codes for the frontend) | FULL as a list |

## Layer 11 — Payments (Razorpay Test Mode)

| ID | Component | Spec |
| --- | --- | --- |
| PAY-1 | Razorpay client abstraction (env credentials only) | FULL |
| PAY-2 | Razorpay order creation after Policy PASS; store internal↔Razorpay order mapping | FULL |
| PAY-3 | Checkout handoff (public config to frontend, secrets stay server-side) | FULL |
| PAY-4 | Webhook receiver preserving the **raw request body** before parsing | FULL |
| PAY-5 | Signature verification against webhook secret + raw body | FULL |
| PAY-6 | Event-ID dedupe (delivery is at-least-once) | FULL |
| PAY-7 | Order-independent event handling (do not assume business-order arrival) | FULL as a rule |
| PAY-8 | Payment state reconciliation into the database | PARTIAL |
| PAY-9 | Order state machine (CART → PENDING_APPROVAL → APPROVED → POLICY_VALIDATED → ORDER_CREATED → PAYMENT_PENDING → PAYMENT_CONFIRMED, plus 6 failure states) | PARTIAL (names not final) |

## Layer 12 — Frontend (React / Next.js)

Presentation only. Never computes price, stock, compatibility, authorization, or payment
truth.

**Components (13):** `App`, `ChatPage`, `ChatWindow`, `MessageList`, `MessageInput`,
`ProductCard`, `ProductRecommendationList`, `CartPanel`, `CartItem`, `CartSummary`,
`ApprovalPanel`, `CheckoutButton`, `OrderStatus`.

**Services (4):** `api`, `chat`, `cart`, `orders`.
**State slices (3):** `chat`, `cart`, `checkout`.
**Types (4):** `product`, `cart`, `order`, `chat`.

Spec: PARTIAL — framework choice between React and Next.js is left open, and the
proposed tree is framework-agnostic.

## Layer 13 — Quality & evaluation

| ID | Suite | Spec |
| --- | --- | --- |
| QA-1 | Database/model tests | PARTIAL |
| QA-2 | Service tests (catalog, compatibility, inventory, ranking) | IMPLIED |
| QA-3 | LLM integration tests (9 named cases, L§51) | FULL as a list |
| QA-4 | Agent Runtime integration tests (15 checkboxes, AGENT-15) | FULL as a list |
| QA-5 | Policy tests (per-rule, independently testable) | FULL as a rule |
| QA-6 | Payment/webhook integration tests (10 named cases, P§40) | FULL as a list |
| QA-7 | End-to-end scenarios: success, price drift, out of stock, duplicate, prompt injection | FULL |
| QA-8 | Mini evaluation suite over representative shopping queries (SHOULD-WORK) | PARTIAL (no harness) |
| QA-9 | LLM test-double strategy for deterministic CI | IMPLIED — not addressed at all |

---

## The invariants every component is subordinate to

These recur in all six parts and are the real acceptance criteria:

1. **LLM proposes → application validates → user authorizes → Razorpay executes → system audits.**
2. PostgreSQL is the source of truth for product facts; the model never invents
   product IDs, SKUs, names, prices, currency, inventory, compatibility, discounts,
   order status, or payment status.
3. Compatibility and inventory are **hard filters applied before ranking**, never
   scoring dimensions that a cheap incompatible product can outweigh.
4. Ranking is deterministic, explainable, reproducible, and configuration-driven.
5. The model never touches PostgreSQL directly and never touches Razorpay directly.
6. Explicit user approval is required, and it binds to a specific cart **version**.
7. Price and inventory are re-validated live immediately before order creation.
8. Payment truth = verified Razorpay webhook (raw-body signature) + database state.
   Never the frontend callback, never the model, never the user's word.
9. Idempotency protects order creation and webhook processing; price drift forces a
   **fresh** approval and a **fresh** idempotency key.
10. Prompt injection is contained structurally, not by prompt wording — there is no
    unrestricted payment tool to reach.
