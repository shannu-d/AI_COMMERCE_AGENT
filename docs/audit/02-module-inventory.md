# 02 — Module Inventory

Status vocabulary: **FULL** (complete and correct) · **PARTIAL** (works, something unverified) ·
**BLOCKED** (cannot be verified here) · **MISSING** · **BROKEN**.
Runtime column records whether *this audit* exercised it against the live application.

## Backend application (`backend/app/`, 103 files, 15,433 lines)

| Module | Location | Purpose | Status | Tests | Runtime Verified |
| --- | --- | --- | --- | --- | --- |
| Configuration | `config.py` | Typed settings, secret redaction, startup validation | FULL | 227 (with LLM) | ✅ fresh process loads Groq + Razorpay |
| Logging | `logging_config.py` | Structured logs, secret filter | FULL | ✓ | ✅ observed in backend log |
| App factory | `main.py` | FastAPI wiring, CORS | FULL | ✓ | ✅ boots on 8001 and 8002 |
| Domain types | `domain/` (10 files) | Frozen value objects, 3 state enums | FULL | ✓ | ✅ |
| ORM models | `db/models/` (14) | 20 tables | FULL | 88 db | ✅ schema matches live DB |
| Migrations | `db/migrations/` (4) | 0001 catalog, 0002 targets, 0003 sessions, 0004 commerce | FULL | ✓ | ✅ applied; round-trip proven by suite |
| Repositories | `repositories/` (6) | Query layer | FULL | ✓ | ✅ |
| Catalog service | `services/catalog_service.py` | Product/variant reads | FULL | 217 services | ✅ via live chat |
| Compatibility service | `services/compatibility_service.py` | ADR-003 resolution pipeline | FULL | ✓ | ✅ iPhone 16 resolved live |
| Inventory service | `services/inventory_service.py` | Stock truth | FULL | ✓ | ✅ LOW_STOCK rendered live |
| Ranking engine | `ranking/` (6) | Deterministic scoring | FULL | 136 | ✅ ranks 1–3 live |
| Recommendation service | `services/recommendation_service.py` | Only M3 code that queries | FULL | ✓ | ✅ `EXACT_MATCH` in logs |
| Session service | `services/session_service.py` | Session + message history | FULL | ✓ | ✅ 4 sessions created |
| Cart service | `services/cart_service.py` | Versioned cart, authoritative totals | FULL | ✓ | ✅ cart v2, total ₹999.00 |
| Approval service | `services/approval_service.py` | Bind approval to cart+version+total | FULL | ✓ | ✅ APPROVED + SUPERSEDED |
| Policy engine | `policy/engine.py` | 10 rules, pure, reason codes | FULL | 35 | ✅ `POLICY_PASS` audited |
| Order service | `services/order_service.py` | Order state machine, idempotency | FULL | ✓ | ✅ order created, replay safe |
| Money conversion | `payments/money.py` | Decimal ↔ integer minor units | FULL | 17 payments | ✅ 999.00 → 99900 |
| Razorpay client | `payments/razorpay_client.py` | Provider boundary | IMPLEMENTED | 17 (doubles) | ❌ **BLOCKED — SDK absent** |
| Razorpay SDK adapter | `payments/sdk.py` | Only module importing the SDK | **BLOCKED** | n/a | ❌ `razorpay` not installed |
| Webhook service | `services/webhook_service.py` | HMAC verify, dedupe, persist | FULL | ✓ | ✅ 400 / 200 / ignored |
| Audit service | `services/audit_service.py` | 12 named events | FULL | ✓ | ✅ 10 rows, ordered trail |
| LLM client | `llm/client.py` | **Only** module importing `groq` | FULL | 147 llm | ✅ live call succeeded |
| LLM extractor | `llm/extractor.py` | Intent extraction, one bounded repair | FULL | ✓ | ✅ |
| Tool schemas | `llm/tool_schemas.py` | 8 schemas; `create_order` forbidden | FULL | ✓ | ✅ |
| Agent runtime | `agent/runtime.py` | Turn loop | FULL | 111 agent | ✅ live turns |
| Tool executor | `agent/executor.py` | A§19 ordering, tier check | FULL | ✓ | ✅ |
| Tool registry | `agent/registry.py` | 7 handlers wired | FULL | ✓ | ✅ |
| Agent tools | `agent/tools/` (5) | catalog, compatibility, inventory, cart, approval | FULL | ✓ | ✅ |
| API routes | `api/routes/` (5) | 11 endpoints | FULL | 96 api | ✅ all exercised |
| Seed | `seed/` | 32-SKU CircuitCraft catalogue | FULL | 32 | ✅ 21 products live |

## Frontend (`frontend/src/`, 30 files, 3,120 lines)

| Module | Location | Purpose | Status | Tests | Runtime Verified |
| --- | --- | --- | --- | --- | --- |
| API client | `api/client.ts` | Single fetch seam, Zod at boundary | FULL | 11 | ✅ |
| API schemas | `api/schemas.ts` | Money regex, 11 error codes, 20 states | FULL | ✓ | ✅ |
| Endpoints | `api/endpoints.ts` | 9 typed calls | FULL | ✓ | ✅ |
| Session | `session.ts` | sessionStorage + memory fallback | FULL | ✓ | ✅ |
| Assistant UI runtime | `features/agent/` (3) | `ChatModelAdapter`, bridge | FULL | 7 | ✅ browser |
| Chat window | `features/chat/ChatWindow.tsx` | Transcript, `role="log"` | FULL | 13 | ✅ browser |
| `useChat` | `features/chat/useChat.ts` | **Superseded**; retained for `Turn` type | PARTIAL | ✓ | n/a |
| Recommendation cards | `features/chat/RecommendationCard.tsx` | Structured-only rendering | FULL | ✓ | ✅ 3 cards |
| Cart panel | `features/cart/CartPanel.tsx` | Backend totals only | FULL | ✓ | ✅ v2 ₹999.00 |
| Approval dialog | `features/checkout/ApprovalDialog.tsx` | Modal, focus, Escape | FULL | 11 a11y | ✅ opened |
| Checkout | `features/checkout/razorpay.ts` | Razorpay Checkout | **BLOCKED** | ✓ | ❌ backend cannot issue |
| Order page | `pages/OrderPage.tsx` | Polls to terminal state | FULL | ✓ | ⚠️ not driven |
| Shop page | `pages/ShopPage.tsx` | Single screen | FULL | ✓ | ✅ |

## Infrastructure

| Item | Location | Status | Note |
| --- | --- | --- | --- |
| CI workflow | `.github/workflows/ci.yml` | IMPLEMENTED | **Never run — no git remote configured** |
| Docker compose | `docker-compose.yml` | IMPLEMENTED | Docker unavailable on this machine |
| ADRs | `docs/decisions/` | FULL | 19 + template, index consistent |
| Stray empty dir | `app/` (repo root) | DEBT | 0 files, untracked; not the real package |

## Counts

103 backend modules · 30 frontend modules · 11 endpoints · 7 registered tools · 20 tables ·
4 migrations · **31 significant modules audited in the table above**.
