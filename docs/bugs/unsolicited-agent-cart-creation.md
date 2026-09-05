# Bug — Agent Built and Proposed an Unsolicited Cart on Informational Queries

**Date:** September 5, 2026  
**Time:** 11:58:18 +0530

### Question

When a customer asks an exploratory or informational question such as "Show me earbuds with noise cancelling", does the AI agent restrict itself to recommending candidates, or does it autonomously add products to the cart and demand purchase approval?

### What I Expected

The assistant should distinguish between *exploring recommendations* and *intent to purchase*. An informational query like "earbuds with noise cancelling" should return product cards and explanatory text, leaving the decision to add to cart entirely to the buyer.

### What Actually Happened

During rehearsal runs for the demo script, asking "earbuds with noise cancelling" resulted in the agent proactively executing `propose_cart` and `request_approval`! It added two pairs of SonicBuds Pro to the cart and responded with:
*"I have added both SonicBuds Pro variants to your cart. Please approve the total of ₹8,998 to proceed to checkout."*

The buyer asked for options and was immediately asked to authorize a payment of nearly ₹9,000 for items they never agreed to purchase!

### Why Was This a Problem?

While the core financial safety invariant held (no money could move without explicit human approval and the model could not create an order row), this behavior was deeply alienating and violated basic commerce UX expectations. Aggressively pushing items into a cart and triggering an approval modal when the user was merely browsing destroyed customer trust.

### Root Cause

In `backend/app/llm/prompts/system_prompt.md` (version 1.3.0), the system prompt defined tools `propose_cart` and `request_approval`, but did not specify clear boundaries regarding *when* they were permitted. The LLM's helpfulness bias led it to assume that completing the full funnel (search -> cart -> approval) in a single turn was the optimal response to any product query.

### Decision

We decided to add an explicit negative constraint to the system prompt (Rule 11) governing cart creation:
The assistant must never call `propose_cart` or `request_approval` unless the user has used explicit purchase phrasing (e.g. "add to cart", "buy this", "I want to purchase", "checkout").

### Fix

In commit `07381be`, updated `system_prompt.md` to version 1.4.0, introducing Rule 11:
> "11. Only build or propose a cart when the buyer explicitly asks you to ('add to cart', 'buy this', 'put that in my cart'). Never create a cart for a buyer who is only browsing, asking questions, or comparing products. Showing a product and adding it are two separate acts."

### Verification

Tested live with the exact prompt that failed earlier:
Query: *"earbuds with noise cancelling"*
Result: The agent called `search_catalog`, returned two product cards for SonicBuds Pro, and answered in prose without calling `propose_cart` or `request_approval`. The cart remained empty.

### Result

PASS. The assistant cleanly separates recommendation discovery from cart creation.

### Evidence

- Git commit: `07381be feat(prompt): stop the agent building a cart nobody asked for; document the demo`
- Files: [`backend/app/llm/prompts/system_prompt.md`](file:///l:/AI_COMMERCE/backend/app/llm/prompts/system_prompt.md), [`backend/app/llm/prompts/__init__.py`](file:///l:/AI_COMMERCE/backend/app/llm/prompts/__init__.py)
- Documented in [`docs/DEMO-SCRIPT.md`](file:///l:/AI_COMMERCE/docs/DEMO-SCRIPT.md).
