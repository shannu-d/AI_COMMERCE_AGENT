"""Catalog seed data and its loader.

``data/catalog.json`` holds the CircuitCraft catalog. ``schema.py`` validates it
as data — every rule that can be checked without a database is checked there, so
a malformed catalog fails before it reaches PostgreSQL and fails with a message
that names the row. ``circuitcraft.py`` loads it.

Loading is idempotent: every seeded row has a deterministic UUID derived from
its natural key (``app.identifiers``), so re-running the loader addresses the
same rows instead of inserting duplicates.
"""
