"""Session creation for buyers who browse rather than chat.

**Why this exists.** A `session_id` is server-minted, and until now the only
place that happened was the first chat turn. That made the storefront
unreachable: a buyer who browsed to a product and pressed *Add to cart* had no
session, so the cart routes answered `SESSION_NOT_FOUND` and the entire
non-conversational path — browse, cart, approve, order — could never be walked.

This adds no capability the system did not already have. It calls the same
`SessionService.create` the chat route calls, returns the same anonymous,
unguessable identifier, and grants nothing: a session authorizes no money and
carries no identity (ADR-006 has no `users` table). It simply lets the buyer
start one without having to talk to the agent first.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.services.session_service import SessionService

router = APIRouter(tags=["sessions"])


class SessionResponse(BaseModel):
    """The identifier, and nothing else — there is nothing else to say."""

    session_id: uuid.UUID


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start an anonymous shopping session",
)
def create_session(
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    """Mint a session so a browsing buyer can hold a cart."""
    view = SessionService(db).create(settings.default_merchant_id)
    return SessionResponse(session_id=view.id)
