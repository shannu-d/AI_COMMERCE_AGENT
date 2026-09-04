# ADR-024 — An MCP surface that makes EASY BUY sellable to AI buyers

**Status:** Accepted · **Date:** 2026-09-04 · **Supersedes:** nothing · **Superseded by:** nothing

Relates to ADR-001 (the invariant), ADR-009 (agent tool boundaries — `create_order`
is not a tool), ADR-011 (the Razorpay order boundary), ADR-012 (a verified webhook
is payment truth), ADR-010 (the chat contract), ADR-018 (Groq is the model).

---

## Context

The Razorpay Buildathon Track 1 ("AI Growth & Agentic Commerce") asks for an
agent that either grows a merchant's revenue or **makes the merchant transactable
by an AI buyer, end to end**, and points at NPCI's UAP and the ACP / AP2 / x402
protocol race as the reason it matters now.

This project already makes the merchant transactable by a *human's* assistant:
`POST /api/chat` runs a Groq agent with bounded tools, and the money path
(`cart → approval → Policy Engine → order → Razorpay → webhook → audit`) is
live-verified. What it did not have was a way for **someone else's** agent — an
autonomous AI buyer — to discover the catalogue and complete a purchase without a
browser and without a human clicking through Checkout.

## Problem

Expose EASY BUY to an external AI buyer over a standard protocol, end to end,
**without weakening the invariant and without touching the money-path code that is
already verified.**

## Decision

### 1. A Model Context Protocol server, as a separate entrypoint

`app/mcp/` is a FastMCP (protocol v1) server run with `python -m app.mcp`
(streamable-HTTP by default, `--stdio` for a desktop MCP client). The FastAPI
application never imports it, so the API still boots without the `mcp` package,
and `app/mcp/` is not on the deterministic-package list — it is a client of the
services, in the same position `app/api/` is.

### 2. It calls the existing services and changes no money-path code

Every tool opens its own unit-of-work session and calls `CatalogService`,
`RecommendationService`, `CompatibilityService`, `CartService`, `ApprovalService`,
`OrderService` and `RazorpayClient` exactly as the HTTP routes do. Nothing in
`app/agent/`, `app/policy/`, `app/payments/` or `app/services/` was modified to
add this surface. A boundary test already in the suite
(`test_the_runtime_is_the_only_place_the_two_sides_meet`) still passes because
`app/mcp/` does not import `app.llm`.

### 3. The tools

**Read (agent-readable catalogue):** `list_categories`, `browse_catalog`,
`search_catalog` (deterministic ranking — the engine chooses and orders, and each
result carries the reason and score), `get_product`, `get_compatible_products`
(compatibility resolved from the merchant's rules; an unresolvable device is a
question back to the buyer, never an empty match). A resource,
`easybuy://catalog`, serves the whole catalogue as one JSON feed.

**Write:** `create_quote(items)` → `authorize_and_pay(quote_reference,
authorized_amount)` → `get_order_status(order_id)`.

### 4. How an AI buyer authorizes — the mandate is the `authorize_and_pay` call

`architecture.md`'s invariant has a **user authorizes** step. When the buyer is an
AI, that step is the `authorize_and_pay` tool call itself, and three things make
it a real authorization rather than a rubber stamp:

- **It is a distinct call from `create_quote`.** Discovery and quoting move no
  money; a separate, explicit act does.
- **It must carry `authorized_amount`** — the exact total from the quote. This is
  the AP2/x402 shape: the mandate names the figure. `ApprovalService.approve`
  checks it against the live cart total, and `OrderService` runs the full Policy
  Engine (ten rules, live price and stock re-read inside the order transaction).
- **A drift is a refusal, not a charge.** If the price moved between quote and
  authorization, the call returns `{"status": "rejected", "code": "TOTAL_CHANGED"}`
  or `{"status": "rejected", "stage": "policy", "reason_codes": [...]}`. Nothing
  is created at an unauthorized amount — the same guarantee ADR-014 gives the
  browser.

`create_order` is still not a tool. The provider order is created by
`OrderService.attach_provider_order` behind the Policy Engine, and
`authorize_and_pay` returns a Razorpay checkout handoff (`order_id`,
`razorpay_order_id`, the public key, the amount in minor units, and a `pay_url`).

### 5. Payment truth is unchanged

`authorize_and_pay` never reports a payment as complete. `get_order_status`
returns `paid: true` only when `orders.status` is `PAYMENT_CONFIRMED`, which only
a signature-verified Razorpay webhook sets (ADR-012). The buyer polls; the webhook
decides.

### 6. Authentication

For this milestone the MCP server is unauthenticated and single-merchant
(`settings.default_merchant_id`), matching the public storefront browse routes.
Money still cannot move without the explicit `authorize_and_pay` mandate and the
Policy Engine. A real deployment needs buyer authentication and per-buyer
spending mandates (AP2) — recorded as a limitation, not built here.

## Alternatives considered

| Rejected | Why |
| --- | --- |
| Mount MCP inside the FastAPI app | Couples the API's boot to the `mcp` package and its transport; a separate entrypoint keeps the API exactly as it was verified. |
| Expose `search_catalog` etc. as the *same* functions the agent registers | The agent tools take an `AgentContext`/`TurnMemory` built by the runtime; the MCP tools take plain arguments. Sharing the services is the right seam, not sharing the tool signatures. |
| Let `authorize_and_pay` also confirm payment (return "paid") | Breaks ADR-012. The webhook is the only payment truth, for an AI buyer exactly as for a human. |
| A Razorpay Payment Link instead of the existing order path | A new provider API surface and a new webhook event type on submission day, for no gain — the existing `order` + Checkout path is already verified. |
| Full ACP/AP2/x402 protocol implementation | Out of scope for the time available; the `authorize_and_pay` mandate is the shape those protocols formalise, and this ADR is where that is recorded. |

## Consequences

**Enables.** An external AI buyer can discover EASY BUY's catalogue over a
standard protocol and complete a real Razorpay test-mode purchase, with every
money action bounded (spending limit, one authorization call), gated (the
mandate, the Policy Engine), explained (reason codes, ranking reasons) and
audited (the same `audit_events` trail the browser produces).

**Forecloses.** Nothing. The surface is additive and removable.

**Costs.** One more dependency (`mcp`, dev/optional in spirit — the API does not
need it) and one more process to run for a demo.

## Implementation

- `app/mcp/server.py` — `build_server(sessionmaker=None)`; 8 tools + 1 resource.
- `app/mcp/__main__.py` — `python -m app.mcp [--stdio] [--port N]`.
- `tests/mcp/test_mcp_server.py` — the read tools are grounded, a quote moves no
  money, authorization needs the exact amount, a wrong amount is refused with a
  code, a correct one reaches an internal order, an unknown SKU is refused, and
  the resource is a full feed. Runs against the seeded database, hermetic at the
  payment boundary.
- `pyproject.toml` — `mcp>=1.9,<2`.
