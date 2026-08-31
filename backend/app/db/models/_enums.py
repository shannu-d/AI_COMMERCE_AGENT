"""One rendering of "this column holds one of these values".

Both the ORM models and migration ``0004`` build their ``CHECK`` constraints from
the tuples in ``app.domain.commerce``. Rendering the SQL in one helper is what
keeps the two byte-identical: ``tests/db/test_migrations.py`` compares the
migration's DDL against the compiled model metadata clause by clause, and two
hand-written renderings of the same list eventually differ by a space.
"""

from __future__ import annotations

__all__ = ["in_list"]


def in_list(column: str, values: tuple[str, ...]) -> str:
    """``column IN ('A', 'B')`` — the shape every enumerated CHECK takes."""
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"
