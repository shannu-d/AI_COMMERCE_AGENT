"""The seed validator's vocabularies must equal the database's.

The seed schema states its enumerations as ``Literal[...]`` for good Pydantic
error messages; the models state the same enumerations as tuples that are
rendered into CHECK constraints. Nothing previously tied the two together, and
they can drift in either direction with different, both bad, consequences:

* widen the model tuple without the Literal, and the validator rejects catalog
  data the database would happily accept;
* widen the Literal without the model tuple, and the validator accepts data that
  fails at INSERT — the failure the seed validator exists to prevent, arriving
  in exactly the form it was meant to stop.

Comparing the sets makes either drift a test failure.
"""

from __future__ import annotations

from typing import Literal, get_args, get_type_hints

from app.db.models import (
    COMPATIBILITY_TARGET_KINDS,
    COMPATIBILITY_TARGET_TYPES,
    PRODUCT_RELATIONSHIP_TYPES,
)
from app.seed.schema import CompatibilitySeed, CompatibilityTargetSeed, RelationshipSeed


def literal_values(model: type, field: str) -> set[str]:
    annotation = get_type_hints(model)[field]
    assert getattr(annotation, "__origin__", None) is Literal or get_args(annotation), (
        f"{model.__name__}.{field} is no longer a Literal; this test needs updating"
    )
    return set(get_args(annotation))


def test_compatibility_rule_target_types_match() -> None:
    assert literal_values(CompatibilitySeed, "target_type") == set(COMPATIBILITY_TARGET_TYPES)


def test_compatibility_target_kinds_match() -> None:
    assert literal_values(CompatibilityTargetSeed, "target_type") == set(COMPATIBILITY_TARGET_KINDS)


def test_relationship_types_match() -> None:
    assert literal_values(RelationshipSeed, "type") == set(PRODUCT_RELATIONSHIP_TYPES)


def test_rule_target_types_are_a_superset_of_target_kinds() -> None:
    """ADR-003: the two vocabularies are different axes, deliberately.

    A target's ``target_type`` says what the identifier *is*; a rule's says how
    a product *relates* to it, and adds the broader ``device`` used for
    chargers. Every kind must still be usable as a rule type, or a seeded target
    could never be referenced by a rule of the same type.
    """
    assert set(COMPATIBILITY_TARGET_KINDS) < set(COMPATIBILITY_TARGET_TYPES)
    assert set(COMPATIBILITY_TARGET_TYPES) - set(COMPATIBILITY_TARGET_KINDS) == {"device"}
