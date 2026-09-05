# Bug — Cart Serialization Divergence Caused Browser MALFORMED_RESPONSE Errors

**Date:** September 5, 2026  
**Time:** 08:41:55 +0530

### Question

When the AI chat agent returns a turn to the frontend for a buyer who already has items in their cart, does the browser accept and render the turn, or does the frontend validation reject it?

### What I Expected

I expected that when a user asks the assistant a question while holding items in their cart, `POST /api/chat` returns a valid JSON payload matching the frontend's Zod `ChatResponse` schema, including the embedded `cart` object, allowing the conversation and the cart bar to remain synchronized.

### What Actually Happened

Whenever the buyer's cart was non-empty, the browser discarded the completed agent turn with a UI error:
`MALFORMED_RESPONSE: Unable to parse agent response.`
The message text and recommended product cards were completely thrown away by the frontend runtime. If the cart was empty, the turn succeeded.

### Why Was This a Problem?

This rendered the chat interface completely broken as soon as a customer actually started shopping. The moment an item was added to the cart, any further interaction with the AI assistant resulted in `MALFORMED_RESPONSE`.

### Root Cause

The frontend schema in `frontend/src/api/schemas.ts` defined `Cart` with mandatory fields:
```typescript
export const CartSchema = z.object({
  cart_id: z.string().uuid(),
  cart_version: z.number().int(),
  status: z.enum(["ACTIVE", "ORDERED", "ABANDONED"]),
  items: z.array(...),
  subtotal: z.string(),
  total: z.string(),
  currency: z.string(),
  price_changes: z.array(...)
});
```

However, in `backend/app/agent/service.py`, `serialize_cart` produced a dictionary that omitted `status`, and omitted `price_changes` whenever there was no price drift. 

Meanwhile, the REST endpoint `GET /api/cart` used `CartResponse.of()`, which patched `status="ACTIVE"` and `price_changes=[]` onto the dictionary before returning. But the agent route `POST /api/chat` called `serialize_cart` directly, bypassing `CartResponse.of()`. This created two divergent serializations of the exact same domain object in the backend!

### Decision

We decided that there must be only ONE canonical serialization function for carts. `serialize_cart` must always emit all required fields (`status` and `price_changes`), and `CartResponse.of()` must not monkey-patch fields on top of it.

### Fix

In commit `447791e`:
1. Updated `app/agent/service.py::serialize_cart` to always include `status=cart.status.value` and `price_changes=... or []`.
2. Cleaned up `CartResponse.of` so it does not add any extra fields.
3. Added a backend contract test that directly parses `frontend/src/api/schemas.ts` to ensure every required field in the TypeScript schema is present in the backend serializer.

### Verification

Ran the contract test:
`tests/api/test_cart.py::test_chat_and_rest_cart_schemas_match_frontend_contract`
Verified that both the REST `/api/cart` and chat `/api/chat` payloads contain identical keys matching the frontend Zod definition. Tested in the browser: queries with an active cart now display responses without errors.

### Result

PASS. The chat payload satisfies the frontend contract with 100% field parity.

### Evidence

- Git commit: `447791e fix(api): serialize one cart one way, whichever door it comes through`
- Files: [`backend/app/agent/service.py`](file:///l:/AI_COMMERCE/backend/app/agent/service.py), [`frontend/src/api/schemas.ts`](file:///l:/AI_COMMERCE/frontend/src/api/schemas.ts)
- Regression test: [`backend/tests/api/test_cart.py::test_chat_and_rest_cart_schemas_match_frontend_contract`](file:///l:/AI_COMMERCE/backend/tests/api/test_cart.py)
