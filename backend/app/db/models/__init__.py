"""ORM models.

Importing this package registers every table on ``Base.metadata``. Alembic's
``env.py`` imports it for exactly that reason, so a model that is not re-exported
here is invisible to autogenerate.

Phase 1 — catalog (M1), specified at column level in architecture.md D§4–D§16.
Phase 2 — commerce (M6), designed in ADR-006 and not implemented yet.
"""
