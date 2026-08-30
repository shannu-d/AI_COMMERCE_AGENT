"""compatibility_targets: the identifier vocabulary (ADR-003).

Deliberately a second migration rather than part of ``0001``.

``architecture.md`` specifies seven catalog tables and this is not one of them.
It exists because the specification has a gap it never names: compatibility is
matched by exact string against ``compatibility_rules.target_identifier``, the
model is forbidden from deciding compatibility, and yet the model is what
produces that string from a buyer's free text. Nothing maps "I just got an
iPhone 16" onto ``iphone_16``, and nothing distinguishes a resolution failure
from a genuine no-match.

Keeping it separate means ``0001`` remains exactly the specified schema and can
be inspected, diffed and reviewed on its own terms, while this addition is
traceable to the decision that motivated it.

Revision ID: 0002
Revises: 0001
Created: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CANONICAL_TOKEN = r"^[a-z0-9]+([-_][a-z0-9]+)*$"


def upgrade() -> None:
    op.create_table(
        "compatibility_targets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # What the identifier *is*: a phone model, a laptop model, a port.
        # compatibility_rules.target_type is a different axis — how a product
        # relates to it — and includes the broader 'device'.
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("canonical_identifier", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        # Already-normalized tokens. Normalization alone is insufficient:
        # normalize("iphone16") is "iphone16", which is not "iphone_16".
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_compatibility_targets"),
        sa.UniqueConstraint(
            "target_type",
            "canonical_identifier",
            name="uq_compatibility_targets_target_type_canonical_identifier",
        ),
        sa.CheckConstraint(
            "target_type IN ('phone_model', 'laptop_model', 'device_port')",
            name="target_type_is_known",
        ),
        sa.CheckConstraint(
            f"canonical_identifier ~ '{CANONICAL_TOKEN}'",
            name="identifier_is_canonical_token",
        ),
    )
    # Alias lookup is the query pattern this table exists for, which is the
    # condition D§24 sets for adding a GIN index.
    op.create_index(
        "ix_compatibility_targets_aliases",
        "compatibility_targets",
        ["aliases"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_table("compatibility_targets")
