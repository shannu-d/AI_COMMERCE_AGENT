"""Compatibility domain types (ADR-003).

The important type here is ``TargetResolution``. Resolution either succeeds or
it does not, and "it did not" is a **first-class result the caller must handle**,
not an exception to swallow and not a `None` to paper over with a default.

That distinction is the whole point of ADR-003. Two situations look identical
from the outside and mean completely different things:

* the device was understood and the catalog genuinely has nothing compatible —
  a legitimate answer (R§14);
* the device was not understood — a question for the buyer.

Collapsing them is how a compatibility miss disguises itself as a no-match, so
the resolver returns ``ResolvedTarget`` or ``UnresolvedTarget`` and never
guesses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class ResolutionFailure(StrEnum):
    """Why a device phrase could not be turned into a canonical identifier."""

    #: The text normalized to nothing at all — "???" or an empty string.
    EMPTY = "EMPTY"
    #: Normalized cleanly, but no active target matches it by identifier or alias.
    UNKNOWN_TARGET = "UNKNOWN_TARGET"
    #: More than one active target matches. ADR-003 requires a clarification
    #: rather than a coin flip, so this is never resolved by picking one.
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"


@dataclass(frozen=True, slots=True)
class CompatibilityTargetView:
    """A row of the identifier vocabulary."""

    id: uuid.UUID
    target_type: str
    canonical_identifier: str
    display_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """A device phrase successfully canonicalized.

    ``canonical_identifier`` is the value matched against
    ``compatibility_rules.target_identifier``. It came from the database, not
    from the model.
    """

    canonical_identifier: str
    target_type: str
    display_name: str
    #: What the caller actually said, and what it normalized to — kept so the
    #: agent can echo the buyer's own words back while using the canonical id.
    requested_text: str
    normalized_text: str

    resolved: bool = field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class UnresolvedTarget:
    """A device phrase that could not be canonicalized. Ask; do not guess."""

    reason: ResolutionFailure
    requested_text: str
    normalized_text: str
    #: Populated on AMBIGUOUS_TARGET, so the caller can offer real choices
    #: instead of an open question.
    candidates: tuple[CompatibilityTargetView, ...] = ()

    resolved: bool = field(default=False, init=False)


#: Callers branch on ``.resolved`` — or match on the type — and must handle both.
TargetResolution = ResolvedTarget | UnresolvedTarget
