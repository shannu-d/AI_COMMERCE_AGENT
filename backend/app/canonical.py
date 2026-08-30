"""Canonical token normalization.

One pure function, with no I/O, no configuration and no model involvement, so
it can be exhaustively tested against a table of inputs.

It is the second stage of the compatibility pipeline in ADR-003:

    user text → [LLM] phrase → [app] normalize → [app] resolve → canonical id

The model extracts a human-readable phrase such as "iPhone 16". This turns that
into ``iphone_16``. What it deliberately cannot do is bridge a gap that is not
punctuation or case: ``normalize_token("iphone16")`` is ``"iphone16"``, which is
not ``"iphone_16"``. That is what the alias column on ``compatibility_targets``
is for.

It lives at the application root rather than inside a service because both the
seed validator (M1) and the compatibility service (M2) need it, and a second
implementation would eventually disagree with the first.
"""

from __future__ import annotations

import re
import unicodedata

#: The shape every canonical token has, matching the CHECK constraints on
#: ``categories.slug``, ``products.slug``, ``compatibility_rules.target_type``,
#: ``compatibility_rules.target_identifier`` and
#: ``compatibility_targets.canonical_identifier``.
CANONICAL_TOKEN_PATTERN = re.compile(r"^[a-z0-9]+([-_][a-z0-9]+)*$")

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def normalize_token(text: str) -> str:
    """Reduce free text to a canonical lowercase token.

    Lowercases, strips accents, and collapses every run of non-alphanumeric
    characters into a single underscore.

    >>> normalize_token("iPhone 16")
    'iphone_16'
    >>> normalize_token("  IPHONE--16  ")
    'iphone_16'
    >>> normalize_token("Café")
    'cafe'
    >>> normalize_token("iphone16")
    'iphone16'
    """
    # NFKD splits accented characters into base plus combining mark; dropping
    # the marks turns "é" into "e" rather than into nothing.
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    collapsed = _NON_ALPHANUMERIC.sub("_", ascii_only.lower())
    return collapsed.strip("_")


def is_canonical_token(text: str) -> bool:
    """Whether ``text`` is already in canonical form.

    A token can be well-formed without being what ``normalize_token`` would
    produce from some other input, so this checks the shape rather than
    round-tripping.
    """
    return bool(CANONICAL_TOKEN_PATTERN.fullmatch(text))
