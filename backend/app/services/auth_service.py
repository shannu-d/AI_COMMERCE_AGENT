"""Authentication — registration, login, logout, token verification (ADR-023).

**The only module that hashes or verifies a password, and the only one that
mints or checks a bearer token.** One place means the rules can only be wrong
once, and a boundary test asserts nothing else imports `argon2`.

Three properties this file exists to hold:

*A password is never stored, logged, or returned.* `argon2id` in, digest out.
There is no plaintext column, no reversible encoding, and the redaction filter
already masks the field name should one ever reach a log record.

*A token is never stored either — only its SHA-256.* The bearer value exists
once, in the response to `login`. A copy of `auth_tokens` therefore yields
nothing usable, and revocation is a column rather than a cache to invalidate.
SHA-256 rather than argon2 here on purpose: the token is 256 bits of
`secrets.token_urlsafe` entropy, so it is not guessable and does not need a slow
KDF — while every authenticated request pays for this lookup.

*Registration and login fail identically.* A wrong password, an unknown email
and an inactive account all answer the same way, so neither endpoint becomes an
oracle for which emails exist.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuthToken, Session, User
from app.domain.identity import AuthenticatedUser, UserRole

logger = logging.getLogger(__name__)

__all__ = ["MIN_PASSWORD_LENGTH", "AuthError", "AuthService", "IssuedToken"]

#: Long enough to matter, short enough not to push people toward reuse. There is
#: deliberately no maximum: argon2 does not truncate, and a cap would only
#: discourage passphrases.
MIN_PASSWORD_LENGTH = 10

#: How long an issued token is good for. Short enough that a leaked token is not
#: forever, long enough that a shopping session is not interrupted.
DEFAULT_TOKEN_TTL = timedelta(hours=12)

_hasher = PasswordHasher()


class AuthError(Exception):
    """An authentication or registration failure, with a machine code.

    The messages here are deliberately incurious: `INVALID_CREDENTIALS` is the
    answer to a wrong password, an unknown email and a disabled account alike.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A freshly minted token. The only time the raw value exists."""

    token: str
    expires_at: datetime
    user: AuthenticatedUser


def _now() -> datetime:
    return datetime.now(UTC)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalise_email(raw: object) -> str:
    if not isinstance(raw, str) or "@" not in raw or len(raw.strip()) > 320:
        raise AuthError("VALIDATION_ERROR", "a valid email address is required")
    email = raw.strip().lower()
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        raise AuthError("VALIDATION_ERROR", "a valid email address is required")
    return email


def _to_principal(user: User) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        role=UserRole(user.role),
        merchant_id=user.merchant_id,
        display_name=user.display_name,
        created_at=user.created_at,
    )


class AuthService:
    """Identity operations. Never trusts a caller-supplied user or role."""

    def __init__(self, session: DbSession, *, token_ttl: timedelta = DEFAULT_TOKEN_TTL) -> None:
        self._session = session
        self._ttl = token_ttl

    # -- registration ------------------------------------------------------

    def register_customer(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> AuthenticatedUser:
        """Create a CUSTOMER.

        **A merchant cannot be created through this path**, and there is no
        `role` parameter that could express one — self-service registration
        makes shoppers, never administrators. A merchant account is provisioned
        by `create_merchant_user` (an operator task), so privilege cannot be
        granted by a request body.
        """
        return self._create(
            email=email,
            password=password,
            role=UserRole.CUSTOMER,
            merchant_id=None,
            display_name=display_name,
        )

    def create_merchant_user(
        self,
        *,
        email: str,
        password: str,
        merchant_id: uuid.UUID,
        display_name: str | None = None,
    ) -> AuthenticatedUser:
        """Provision a MERCHANT administrator for one merchant.

        Not reachable from any public route. The merchant id is supplied by the
        operator invoking this, never by a browser.
        """
        return self._create(
            email=email,
            password=password,
            role=UserRole.MERCHANT,
            merchant_id=merchant_id,
            display_name=display_name,
        )

    def _create(
        self,
        *,
        email: str,
        password: str,
        role: UserRole,
        merchant_id: uuid.UUID | None,
        display_name: str | None,
    ) -> AuthenticatedUser:
        address = _normalise_email(email)
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            raise AuthError(
                "VALIDATION_ERROR",
                f"password must be at least {MIN_PASSWORD_LENGTH} characters",
            )
        if self._by_email(address) is not None:
            # Same code and shape as a bad login, so this is not an oracle for
            # which addresses are registered.
            raise AuthError("INVALID_CREDENTIALS", "that account could not be created")

        name = (
            display_name.strip() if isinstance(display_name, str) and display_name.strip() else None
        )
        if name is not None and len(name) > 120:
            raise AuthError("VALIDATION_ERROR", "display name is too long")

        user = User(
            id=uuid.uuid4(),
            email=address,
            password_hash=_hasher.hash(password),
            role=role.value,
            merchant_id=merchant_id,
            display_name=name,
            is_active=True,
        )
        self._session.add(user)
        self._session.flush()
        logger.info("user registered", extra={"role": role.value})
        return _to_principal(user)

    # -- login / logout ----------------------------------------------------

    def login(self, *, email: str, password: str) -> IssuedToken:
        """Verify a password and mint a token.

        Every failure — unknown email, wrong password, disabled account — raises
        the same `INVALID_CREDENTIALS`. A missing user still costs a hash
        verification against a dummy digest, so response time does not reveal
        whether the address exists.
        """
        try:
            address = _normalise_email(email)
        except AuthError:
            _waste_a_verification()
            raise AuthError("INVALID_CREDENTIALS", "email or password is incorrect") from None

        user = self._by_email(address)
        if user is None or not user.is_active:
            _waste_a_verification()
            raise AuthError("INVALID_CREDENTIALS", "email or password is incorrect")

        try:
            _hasher.verify(user.password_hash, password if isinstance(password, str) else "")
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            raise AuthError("INVALID_CREDENTIALS", "email or password is incorrect") from None

        # Transparent rehash if the cost parameters have moved on since signup.
        if _hasher.check_needs_rehash(user.password_hash):
            user.password_hash = _hasher.hash(password)

        return self._issue(user)

    def logout(self, token: str) -> None:
        """Revoke one token. Idempotent: an unknown or spent token is a no-op."""
        row = self._token_row(token)
        if row is not None and row.revoked_at is None:
            row.revoked_at = _now()
            self._session.flush()

    def revoke_all(self, user_id: uuid.UUID) -> int:
        """Revoke every live token for a user. Returns how many were live."""
        rows = list(
            self._session.execute(
                select(AuthToken).where(
                    AuthToken.user_id == user_id, AuthToken.revoked_at.is_(None)
                )
            )
            .scalars()
            .all()
        )
        now = _now()
        for row in rows:
            row.revoked_at = now
        self._session.flush()
        return len(rows)

    # -- verification ------------------------------------------------------

    def authenticate(self, token: str | None) -> AuthenticatedUser | None:
        """Resolve a bearer token to a principal, or `None`.

        Returns `None` — never raises — for every failure mode: absent,
        malformed, unknown, revoked, expired, or belonging to a disabled user.
        The caller decides whether that is a 401 or an anonymous request, which
        is what lets one function serve both `optional_user` and
        `require_customer`.
        """
        if not token or not isinstance(token, str):
            return None
        row = self._token_row(token)
        if row is None or row.revoked_at is not None:
            return None
        if row.expires_at <= _now():
            return None
        user = self._session.get(User, row.user_id)
        if user is None or not user.is_active:
            return None
        row.last_used_at = _now()
        return _to_principal(user)

    # -- session ownership -------------------------------------------------

    def claim_session(self, user_id: uuid.UUID, session_id: uuid.UUID | None) -> bool:
        """Attach an anonymous session — and therefore its cart — to a user.

        This is the whole of ADR-023's "login claims the session": the cart row
        is already the right one, it simply gains an owner, so there is no merge
        algorithm and no data movement.

        A session already owned by *someone else* is never re-pointed; the
        caller keeps shopping in a fresh session instead. Returns whether the
        claim happened.
        """
        if session_id is None:
            return False
        session = self._session.get(Session, session_id)
        if session is None:
            return False
        if session.user_id is not None and session.user_id != user_id:
            return False
        if session.user_id == user_id:
            return True
        session.user_id = user_id
        self._session.flush()
        logger.info("session claimed on login", extra={"session_id": str(session_id)})
        return True

    def owns_session(self, user: AuthenticatedUser | None, session_id: uuid.UUID) -> bool:
        """May this principal act on this session?

        * An **anonymous** session (``user_id IS NULL``) is actionable by
          anyone holding its unguessable id — that is exactly the pre-auth
          contract, and it is what keeps logged-out shopping working.
        * An **owned** session is actionable only by its owner.

        So authentication narrows access; it never widens it.
        """
        session = self._session.get(Session, session_id)
        if session is None:
            return False
        if session.user_id is None:
            return True
        return user is not None and session.user_id == user.id

    # -- internals ---------------------------------------------------------

    def _by_email(self, email: str) -> User | None:
        return self._session.execute(select(User).where(User.email == email)).scalar_one_or_none()

    def _token_row(self, token: str) -> AuthToken | None:
        return self._session.execute(
            select(AuthToken).where(AuthToken.token_hash == _digest(token))
        ).scalar_one_or_none()

    def _issue(self, user: User) -> IssuedToken:
        # 32 bytes of entropy, URL-safe. The raw value is returned once and
        # never stored.
        raw = secrets.token_urlsafe(32)
        issued = _now()
        expires = issued + self._ttl
        self._session.add(
            AuthToken(
                id=uuid.uuid4(),
                token_hash=_digest(raw),
                user_id=user.id,
                issued_at=issued,
                expires_at=expires,
            )
        )
        self._session.flush()
        return IssuedToken(token=raw, expires_at=expires, user=_to_principal(user))


#: A constant argon2 digest, verified against when no user was found, so a login
#: for an unknown address costs the same as one for a known address.
_DUMMY_HASH = _hasher.hash("a-password-that-is-never-anyones")


def _waste_a_verification() -> None:
    try:
        _hasher.verify(_DUMMY_HASH, "not-the-password")
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass
