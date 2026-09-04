"""Identity domain types — ADR-023.

Two roles and nothing else. A `CUSTOMER` shops; a `MERCHANT` administers exactly
one merchant's catalogue. The pairing is enforced by a CHECK constraint on
``users`` rather than only by a service, so a merchant row without a merchant, or
a customer row with one, cannot be stored at all.

The values live here rather than in ``app.db.models`` because both the ORM model
and migration ``0005`` build their CHECK from the same tuple — the same
arrangement ``app.domain.commerce`` uses, and what keeps
``tests/db/test_migrations.py`` able to compare the two renderings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

__all__ = [
    "USER_ROLES",
    "AuthenticatedUser",
    "UserRole",
]


class UserRole(StrEnum):
    """Who a `users` row is.

    Deliberately closed and deliberately small. A third role (support, admin)
    would be a decision about what it may reach, and that decision does not
    exist yet — an unused role in the enum would be a permission nobody reviewed.
    """

    CUSTOMER = "CUSTOMER"
    MERCHANT = "MERCHANT"


USER_ROLES: tuple[str, ...] = tuple(role.value for role in UserRole)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The principal a request is acting as.

    Frozen, and built only by the token-verifying dependency. Nothing that
    arrives from a client — a body field, a query parameter, a header other than
    the verified bearer token — may construct one of these.

    ``merchant_id`` is set for a `MERCHANT` and `None` for a `CUSTOMER`. It is
    the **only** source of a merchant id for the dashboard routes (ADR-023 §6);
    a route that reads a merchant from anywhere else is a defect.
    """

    id: UUID
    email: str
    role: UserRole
    merchant_id: UUID | None
    display_name: str | None
    created_at: datetime

    @property
    def is_merchant(self) -> bool:
        return self.role is UserRole.MERCHANT

    @property
    def is_customer(self) -> bool:
        return self.role is UserRole.CUSTOMER
