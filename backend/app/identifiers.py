"""Deterministic identifiers for seeded rows.

Primary keys are UUIDs (architecture.md D§21). Rows the application creates at
runtime get a database-generated ``gen_random_uuid()``. Rows that come from the
seed catalog get a *deterministic* UUID derived from a stable natural key, for
three reasons:

* seeding becomes idempotent — re-running it addresses the same rows rather
  than inserting duplicates (ADR-002);
* tests can name a seeded row without first querying for it;
* ``DEFAULT_MERCHANT_ID`` has a known value before the database exists, so
  merchant scoping can be configured without a bootstrap step (ADR-002).

UUIDv5 is used because it is a pure function of its inputs: the same natural key
always yields the same UUID, on every machine and in every process.
"""

from __future__ import annotations

import uuid

# A URL-shaped namespace under a domain reserved for documentation and examples
# (RFC 2606), so these identifiers can never collide with a real deployment's.
_SEED_BASE = "https://circuitcraft.example"


def seed_id(kind: str, key: str) -> uuid.UUID:
    """Return the stable UUID for a seeded row.

    ``kind`` is the entity type ("merchant", "product", "variant", ...) and
    ``key`` its natural key within that type — a slug, a SKU, or a composite.
    Both are lowercased so that a change of casing upstream cannot silently
    produce a second row for the same logical entity.

    >>> seed_id("merchant", "circuitcraft") == seed_id("MERCHANT", "CircuitCraft")
    True
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{_SEED_BASE}/{kind.lower()}/{key.lower()}")


#: The CircuitCraft merchant identifier, referenced by configuration and by the
#: seed loader. Both derive it from this one call rather than repeating a literal.
DEFAULT_MERCHANT_ID: uuid.UUID = seed_id("merchant", "circuitcraft")
