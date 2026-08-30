"""``compatibility_targets`` — ADR-003. Not in architecture.md.

This table closes the gap the specification leaves open (open question B1).

``compatibility_rules.target_identifier`` is matched by exact string. The buyer
writes "I just got an iPhone 16", "iphone16", "my new iphone". The specification
forbids the model from deciding compatibility (R§5, L§18) — yet the model is the
component that produces that string. Nothing in the document maps free text onto
``iphone_16``, and nothing detects when the mapping failed. A model that emits
``iphone_16_pro`` against a catalog that knows only ``iphone_16`` returns zero
compatible products, which from the outside is indistinguishable from a catalog
that genuinely has none.

So resolution becomes data:

    user text → [LLM] phrase → [app] normalize → [app] resolve here → canonical id

``target_type`` here classifies **what the identifier is** — a phone model, a
laptop model, a port. ``compatibility_rules.target_type`` classifies **how a
product relates to it**, and includes the broader ``device``. Keeping the two
axes apart is what lets the specification's own examples (``phone_model`` for
cases, ``device`` for chargers, ``device_port`` for cables) coexist without
being conflated.

An identifier that resolves to nothing, or to more than one active row, is a
question for the buyer — never a guess (ADR-003).

Created by migration 0002, deliberately separate from the seven specified tables
in 0001, so the specified schema stays auditable in isolation.
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import CANONICAL_TOKEN_REGEX, Base, TimestampMixin, uuid_pk

#: What kind of thing an identifier names (ADR-003).
COMPATIBILITY_TARGET_KINDS: Final[tuple[str, ...]] = (
    "phone_model",
    "laptop_model",
    "device_port",
)


class CompatibilityTarget(Base, TimestampMixin):
    __tablename__ = "compatibility_targets"
    __table_args__ = (
        UniqueConstraint("target_type", "canonical_identifier"),
        CheckConstraint(
            "target_type IN ("
            + ", ".join(f"'{value}'" for value in COMPATIBILITY_TARGET_KINDS)
            + ")",
            name="target_type_is_known",
        ),
        CheckConstraint(
            f"canonical_identifier ~ '{CANONICAL_TOKEN_REGEX}'",
            name="identifier_is_canonical_token",
        ),
        # Alias lookup is the query pattern this table exists for, which is
        # exactly the condition D§24 sets for adding a GIN index.
        Index("ix_compatibility_targets_aliases", "aliases", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Additional already-normalized tokens that resolve to this target.
    #: Normalization alone is not enough: normalize("iphone16") is "iphone16",
    #: which does not equal "iphone_16".
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    def __repr__(self) -> str:
        return f"<CompatibilityTarget {self.target_type}={self.canonical_identifier!r}>"
