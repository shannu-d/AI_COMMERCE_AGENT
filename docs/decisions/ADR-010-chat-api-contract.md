# ADR-010: The Chat API Contract

**Status:** Accepted, not implemented (2026-08-30)
**Milestone:** M5 (endpoint), M14 (frontend consumer)
**Source references:** `architecture.md` A§48, F§8, F§9, F§10, F§16, F§25, F§26, F§28
**Related open questions:** E3 (BLOCKING), A7, E5, E6

## Context

Two parts of `architecture.md` specify the same endpoint differently.

A§48, from the Agent Runtime part:

```json
{ "session_id": "session-123", "message": "...", "state": "RECOMMENDING", "trace": [...] }
```

F§8–F§9, from the frontend part:

```json
{ "session_id": "sess_123", "message": "...", "recommendations": [ { "product_id": "...", "name": "...", "price": 49999, "reason": "Best overall" } ] }
```

Both the Agent Runtime and the frontend build against this contract, and it is the one place where
two teams would otherwise write to different shapes. F§9 supplies the reason the structured half
exists:

> This allows the frontend to render proper product cards instead of trying to extract product
> information from prose.

## Problem

One contract for `POST /api/chat`, and the accompanying decisions about what structured commerce
data rides alongside the natural-language message.

## Decision

### The union of both shapes

`POST /api/chat`

**Request**

```json
{
  "session_id": "3f1c...  (UUID, optional — omit on the first turn)",
  "message": "I need a case for my iPhone 16 under ₹1500"
}
```

`session_id` is server-minted. A client-supplied value that does not correspond to an existing
session is rejected with `SESSION_NOT_FOUND` rather than silently creating one, so a typo cannot
strand a conversation.

**Response**

```json
{
  "session_id": "3f1c...",
  "state": "RECOMMENDING",
  "message": "I found two iPhone 16 cases under ₹1,500.",
  "recommendations": [
    {
      "product_id": "...",
      "variant_id": "...",
      "sku": "CASE-IP16-BLK",
      "name": "AeroCase Pro",
      "variant_name": "Black",
      "price": "999.00",
      "currency": "INR",
      "stock_status": "IN_STOCK",
      "attributes": { "material": "TPU", "color": "black" },
      "compatibility": ["iPhone 16"],
      "reason": "Best overall",
      "score": { "final": 0.7968, "preference": 0.80, "price": 0.334, "relevance": 0.90 }
    }
  ],
  "cart": null,
  "trace": null,
  "error": null
}
```

Every field is always present. Absent data is `null` or `[]`, never a missing key, so no client needs
to test for key existence.

### Field rules

**`message`** — natural language only. It carries no commerce fact the structured fields do not also
carry. A client that parses `message` for a price is doing something the contract forbids.

**`recommendations[]`** — always structured, never extracted from prose (F§9). Emitted by the
ranking engine, not by the model. Money is a fixed-scale **string** (`"999.00"`), never a JSON
number (ADR-008). `stock_status` is coarse — `IN_STOCK` / `LOW_STOCK` / `OUT_OF_STOCK` — and exact
quantities never appear in this payload (closes E5).

**`reason`** — written by the ranking engine (closes A7). It is a deterministic label derived from
the score components — `"Best overall"`, `"Best price"`, `"Closest match to your requirements"` —
and it is authoritative. The model may paraphrase it in `message`; it may not author it. A
model-authored reason would be an ungrounded claim about arithmetic the model did not perform.

**`score`** — the component scores that produced the ordering. Present so the ranking is inspectable
and the demo is explainable; a client may ignore it.

**`state`** — the session's conversation state (A§25), for the UI to drive its own affordances. It
is display state. It is never read by the Policy Engine (ADR-007).

**`cart`** — the authoritative cart when one exists: items, `subtotal`, `total`, `currency` and
`cart_version` (F§12, F§13). Always backend-computed. The frontend never sums line items (F§12).

**`trace`** — the agent trace of A§39: intent, tool calls, tool results, ranking, decisions.
Returned **per turn and not persisted** (closes E6); the audit log is the durable record (A§40).
`null` unless `AGENT_TRACE_ENABLED` is set, so it is available for the demo and off by default. It
never contains secrets, raw database rows or prompt text.

**`error`** — `null` on success; otherwise `{ "code": ..., "message": ..., "details": {...} }` using
the codes of F§25: `VALIDATION_ERROR`, `PRODUCT_NOT_FOUND`, `VARIANT_NOT_FOUND`, `OUT_OF_STOCK`,
`PRICE_CHANGED`, `APPROVAL_REQUIRED`, `POLICY_FAILED`, `ORDER_CREATION_FAILED`, `PAYMENT_FAILED`,
`PAYMENT_PENDING`, `SERVER_ERROR`. Never a Python exception, never a database message (F§25).

### HTTP status codes

`200` for any turn the agent completed, including one that ends in a business failure — a policy
refusal is a successful conversational turn with an `error` body. `4xx` is reserved for malformed
requests and unknown sessions; `5xx` for genuine server faults. This keeps a `PRICE_CHANGED`
outcome, which the frontend must render as a recovery flow, out of the client's network-error path.

### The rest of the surface

The endpoints of F§26 are adopted verbatim, with no duplicates (F§26: "Do not create duplicate APIs
if equivalent services already exist"):

```
POST   /api/chat
GET    /api/cart
POST   /api/cart/items
PATCH  /api/cart/items/{id}
DELETE /api/cart/items/{id}
POST   /api/cart/approve
POST   /api/orders
GET    /api/orders/{order_id}
POST   /api/webhooks/razorpay
GET    /api/health
```

`GET /api/health` is added by M0 for liveness and to report configuration and database reachability.

### No streaming

F§28 discourages it. Responses are complete JSON documents. A loading indicator is the frontend's
job.

## Alternatives considered

**Adopt A§48's shape and let the frontend parse products out of prose.** Rejected by F§9 — it is the
exact failure that section exists to prevent, and it would make the UI depend on the model's
sentence structure.

**Adopt F§8's shape and drop `state` and `trace`.** Rejected: `state` drives the UI's approval and
checkout affordances, and `trace` is a named SHOULD-WORK feature (A§39).

**Separate endpoints — `/api/chat` for text and `/api/recommendations` for data.** Rejected: two
round-trips per turn, and two sources of truth for one agent turn that can disagree.

**Money as a JSON number.** Rejected by ADR-008. `1798.00` becomes a float in most JSON parsers
before any validation can intervene.

**Return `4xx` for policy failures.** Rejected: it conflates a business outcome the UI must render
carefully with a transport error the UI would normally retry or discard.

## Consequences

**Enables.** The frontend renders product cards from typed data with no parsing; the agent and the
frontend are developed in parallel against a frozen shape; the demo can show the trace without a
second endpoint.

**Forecloses.** Token-by-token streaming, and any client that wants only prose — the response is
larger than a chat reply needs to be.

**Costs.** Every turn serializes cart and recommendation state even when unchanged. At this scale
that is negligible and it removes an entire class of client-side cache-staleness bugs.

## Implementation implications

- The contract is written to `docs/contracts/api-endpoints.md` and frozen before M5 and M14 begin.
  A change to it is a coordinated event, not a unilateral edit.
- Request and response are Pydantic models in `app/api/schemas/chat.py`, and the same models
  generate the OpenAPI document FastAPI serves.
- `AGENT_TRACE_ENABLED` is typed configuration, default `false`.
- Money fields serialize through a shared `Money` type that emits a fixed-scale string.
- **M5 tests:** every response validates against the response model; `recommendations` is populated
  from the ranker, never from model output; an unknown `session_id` returns `SESSION_NOT_FOUND`;
  `trace` is `null` when disabled.
- **M14 test:** the frontend renders a product card without reading `message`.

## Status

**Accepted, not implemented.** M5 implements the endpoint; M14 consumes it.
