# Bug — Add-to-Cart Button Permanently Disabled on Fresh Browsers

**Date:** September 5, 2026  
**Time:** 08:41:37 +0530

### Question

When a customer visits the store for the first time on a fresh browser (with no cookies or localStorage) and browses to a product page, can they click "Add to Cart"?

### What I Expected

A buyer landing on the homepage or navigating to a product page without opening the AI chat should be able to click "Add to Cart". The frontend should ensure a session ID is generated on-the-fly and add the selected variant to the cart.

### What Actually Happened

During our first manual browser walkthrough in an Incognito Chrome window, the "Add to Cart" button rendered permanently **disabled** across the entire site — on product cards, category pages, and the product detail view. Hovering over it gave no explanation. The buyer could not purchase anything by browsing.

### Why Was This a Problem?

This was a critical UX blocker. A new customer visiting the storefront directly could not add products to their cart. Because every automated test had either called `POST /api/sessions` or logged in before testing cart actions, no automated test had ever rendered the component with a `null` session.

### Root Cause

In `frontend/src/features/catalog/useAddToCart.ts`, the hook evaluated the current session ID synchronously at component render time:

```typescript
// Old buggy implementation:
const sessionId = readSessionId(); // returns null on fresh browser!
```

Both `ProductCard.tsx` and `ProductDetail.tsx` contained the following guard:

```tsx
<button disabled={!sessionId || isPending || isOutOfStock} ...>
```

Because an anonymous browser visitor who hasn't opened chat has never had a session minted, `readSessionId()` returned `null`.
Ironically, a helper function named `ensureSessionId()` had already been written in `frontend/src/session.ensure.ts` with docstrings explicitly stating:
*"Mint a session ID if one does not exist in storage."*
However, **nothing in the codebase had imported or called it!**

### Decision

We decided that:
1. The "Add to Cart" button must NOT be disabled based on session presence.
2. The session resolution must happen asynchronously **inside the mutation function**, calling `ensureSessionId()` only when the buyer actually clicks "Add to Cart".

### Fix

In commit `d1ecb2c`:
1. Updated `frontend/src/features/catalog/useAddToCart.ts`:
   ```typescript
   export function useAddToCart(item: ProductCardData, sessionIdOverride?: string) {
     return useMutation({
       mutationFn: async () => {
         const sessionId = sessionIdOverride ?? (await ensureSessionId());
         const cart = await addCartItem({
           session_id: sessionId,
           variant_id: item.variantId,
           quantity: 1,
         });
         return { cart, sessionId };
       },
       ...
   ```
2. Removed the `!sessionId` check from the button's `disabled` attribute across product components.

### Verification

Tested manually in a fresh Incognito browser window with cleared storage:
1. Navigated to `http://localhost:5173/products/aerocase_pro`.
2. Verified "Add to Cart" button was enabled and clickable.
3. Clicked "Add to Cart".
4. Confirmed a new session UUID was minted in `localStorage`, item was added, and cart counter updated to 1.

### Result

PASS. An anonymous first-time visitor can add items to cart seamlessly.

### Evidence

- Git commit: `d1ecb2c fix(frontend): mint the session inside the add-to-cart mutation`
- Files: [`frontend/src/features/catalog/useAddToCart.ts`](file:///l:/AI_COMMERCE/frontend/src/features/catalog/useAddToCart.ts), [`frontend/src/session.ensure.ts`](file:///l:/AI_COMMERCE/frontend/src/session.ensure.ts)
- Documented in [`docs/notes/bugs-found-during-development.md`](file:///l:/AI_COMMERCE/docs/notes/bugs-found-during-development.md) §A2-1.
