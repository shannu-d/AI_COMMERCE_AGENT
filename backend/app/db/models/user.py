"""``users`` and ``auth_tokens`` — ADR-023.

ADR-006 deferred authentication and said what adding it would look like: *"a
`users` table and a nullable foreign key"*. This is that, and no more.

**One table, two roles.** `merchants` remains the *business* that owns a
catalogue; a merchant login is a person who administers one, which is a `users`
row pointing at it. The pairing is a CHECK, not a service rule:

    (role = 'MERCHANT' AND merchant_id IS NOT NULL)
 OR (role = 'CUSTOMER' AND merchant_id IS NULL)

so a customer with a merchant, or a merchant without one, is unstorable.

**Only a hash is stored.** ``password_hash`` holds an argon2id digest. There is
no plaintext column, no reversible encoding, and nothing here is ever logged —
the redaction filter already masks ``password``.

**A token is a row, and the row holds only its hash.** ``auth_tokens.token_hash``
is the SHA-256 of the bearer value; the value itself exists once, in the login
response. A leaked database therefore does not yield usable tokens. Logout and
revocation are ``revoked_at``; expiry is ``expires_at``. That revocability is the
reason ADR-023 chose an opaque server-side token over a JWT.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk
from app.db.models._enums import in_list
from app.domain.identity import USER_ROLES, UserRole

if TYPE_CHECKING:
    from app.db.models.merchant import Merchant


class User(Base, TimestampMixin):
    """A person who can sign in. Customer or merchant administrator."""

    __tablename__ = "users"
    __table_args__ = (
        # Email is the login handle, stored lowercased by the service so the
        # uniqueness the database enforces is the uniqueness a human expects.
        UniqueConstraint("email"),
        CheckConstraint(in_list("role", USER_ROLES), name="role_is_known"),
        # The role/merchant pairing, in the database rather than in a service.
        CheckConstraint(
            "(role = 'MERCHANT' AND merchant_id IS NOT NULL) "
            "OR (role = 'CUSTOMER' AND merchant_id IS NULL)",
            name="merchant_role_has_a_merchant",
        ),
        CheckConstraint("email = lower(email)", name="email_is_lowercase"),
        CheckConstraint("length(password_hash) > 0", name="password_hash_is_present"),
        Index("ix_users_merchant_id", "merchant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    #: argon2id. Never a plaintext password, never a reversible encoding.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Set for a MERCHANT, null for a CUSTOMER. The only source of a merchant id
    #: for the dashboard routes (ADR-023).
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    merchant: Mapped[Merchant | None] = relationship()
    tokens: Mapped[list[AuthToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email!r} {self.role}>"


class AuthToken(Base):
    """One issued bearer token, stored as a hash.

    No ``updated_at``: the row is written once and then only stamped
    (``last_used_at``) or retired (``revoked_at``).
    """

    __tablename__ = "auth_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint("expires_at > issued_at", name="expiry_follows_issue"),
        Index("ix_auth_tokens_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: SHA-256 of the bearer value. The value itself is returned once, at login,
    #: and never stored — a database copy yields no usable token.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Set by logout, or by revoking every token for a user. A revoked row is
    #: kept rather than deleted so "when did this session end" stays answerable.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="tokens")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuthToken user={self.user_id} expires={self.expires_at}>"


#: Re-exported so callers do not import the enum from two places.
__all__ = ["AuthToken", "User", "UserRole"]
