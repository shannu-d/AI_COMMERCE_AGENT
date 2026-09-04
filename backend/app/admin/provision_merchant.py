"""Provision a merchant administrator (ADR-023).

    python -m app.admin.provision_merchant --email owner@example.com

**This is the only way a MERCHANT account comes into existence, and it is
deliberately not an HTTP route.** Self-service registration makes customers; a
request body that could ask for a role is the one thing a registration endpoint
most often gets wrong, so there is no such field and no route behind one. An
administrator is created by whoever administers the deployment — which is what
this command is.

**The password is never an argument.** It is read from a hidden prompt, or from
`MERCHANT_ADMIN_PASSWORD` for a non-interactive run. A `--password` flag would
put a live credential into shell history, into `ps` output, and into any CI log
that echoes its commands. Nothing here prints the value, and only the argon2id
digest is ever stored.

Idempotent in the useful sense: running it twice for the same address does not
create a second account and does not silently reset the first. Use
`--reset-password` to deliberately change one, which also revokes every live
token for that user — a password change that left old sessions signed in would
not be a password change.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Merchant, User
from app.db.session import get_sessionmaker
from app.services.auth_service import MIN_PASSWORD_LENGTH, AuthError, AuthService

#: Read for a non-interactive run (CI, a container entrypoint). Never logged.
PASSWORD_ENV = "MERCHANT_ADMIN_PASSWORD"


def _read_password(*, confirm: bool) -> str:
    """From the environment, or a hidden prompt. Never from an argument."""
    from_env = os.environ.get(PASSWORD_ENV)
    if from_env:
        return from_env
    if not sys.stdin.isatty():
        raise SystemExit(f"No terminal to prompt on. Set {PASSWORD_ENV} for a non-interactive run.")
    password = getpass.getpass("Password: ")
    if confirm and password != getpass.getpass("Repeat: "):
        raise SystemExit("The passwords did not match. Nothing was written.")
    return password


def _resolve_merchant(session, wanted: str | None) -> Merchant:
    """The merchant this administrator will own.

    Defaults to the configured one, because a single-merchant deployment is what
    this project ships. A name or id may be given explicitly for a second tenant.
    """
    if wanted:
        try:
            row = session.get(Merchant, uuid.UUID(wanted))
        except ValueError:
            row = session.execute(
                select(Merchant).where(Merchant.name == wanted)
            ).scalar_one_or_none()
        if row is None:
            raise SystemExit(f"No merchant matches {wanted!r}.")
        return row

    settings = get_settings()
    row = session.get(Merchant, settings.default_merchant_id)
    if row is None:
        raise SystemExit(
            "The configured merchant is not in the database. "
            "Run `python -m app.seed.circuitcraft` first."
        )
    return row


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.admin.provision_merchant",
        description="Create (or repair) a merchant administrator account.",
    )
    parser.add_argument("--email", required=True, help="The administrator's login address.")
    parser.add_argument("--name", default=None, help="Display name. Optional.")
    parser.add_argument(
        "--merchant",
        default=None,
        help="Merchant id or name. Defaults to the configured merchant.",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Set a new password for an existing account and revoke its live tokens.",
    )
    args = parser.parse_args(argv)

    factory = get_sessionmaker()
    with factory() as session:
        merchant = _resolve_merchant(session, args.merchant)
        service = AuthService(session)
        email = args.email.strip().lower()
        existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()

        if existing is not None and not args.reset_password:
            print(f"{email} already exists ({existing.role}). Nothing changed.")
            print("Pass --reset-password to set a new password for it.")
            return 0

        password = _read_password(confirm=True)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

        try:
            if existing is None:
                user = service.create_merchant_user(
                    email=email,
                    password=password,
                    merchant_id=merchant.id,
                    display_name=args.name,
                )
                session.commit()
                print(f"Created {user.email} as a MERCHANT administrator of {merchant.name!r}.")
            else:
                if existing.role != "MERCHANT":
                    raise SystemExit(
                        f"{email} is a {existing.role} account. "
                        "A role is never changed in place; use a different address."
                    )
                # Through the same hasher every login uses — there is one place
                # that turns a password into a digest, and this is not a second.
                service.set_password(existing.id, password)
                revoked = service.revoke_all(existing.id)
                session.commit()
                print(f"Reset the password for {email}. Revoked {revoked} live token(s).")
        except AuthError as error:
            session.rollback()
            raise SystemExit(f"Could not provision the account: {error.message}") from error

    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
