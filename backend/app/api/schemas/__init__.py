"""Request and response models for the HTTP surface.

One module per endpoint group, each model the single definition of its contract:
FastAPI serves the OpenAPI document from these, so the published schema and the
validated shape cannot drift apart.

Contracts are frozen before their consumers are built (ADR-010). A change to one
is a coordinated event rather than a unilateral edit, because the frontend (M14)
is developed against the same shape the agent produces.
"""
