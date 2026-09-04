"""The Model Context Protocol surface — EASY BUY, made sellable to AI buyers (ADR-024).

This package exposes the merchant to an *external* agent the same way the chat
runtime exposes it to a human's assistant: a read side that is agent-readable
catalogue and compatibility, and a write side that is quote → authorize → pay,
with every money action bounded, gated, explained and audited.

It is **purely additive**. Every tool here calls the same services the HTTP
routes call — `CatalogService`, `RecommendationService`, `CartService`,
`ApprovalService`, `OrderService`, `RazorpayClient` — and touches no money-path
code. Nothing in `app/agent/`, `app/policy/`, `app/payments/` or `app/services/`
changed to add it.
"""

from app.mcp.server import build_server

__all__ = ["build_server"]
