"""`POST /api/webhooks/razorpay` — where payment truth enters (M12; ADR-012).

**This route must not bind a Pydantic body model.** FastAPI's automatic body
binding consumes and re-encodes the request, and a signature checked against
re-encoded bytes proves nothing (P§24). The handler takes `Request` and reads
`await request.body()` itself, before anything parses it.

That constraint is easy to undo by accident — adding a typed body parameter looks
like an improvement — so a standing test asserts this route's signature has no
Pydantic model in it.

**`200` is the default answer.** Razorpay retries anything else. A duplicate, an
unknown event type and an event for an unknown order are all *correctly handled*
outcomes and get `200`. Only a failed signature gets `400`; only a genuine
internal fault gets `500`, because that is the one case where a retry is wanted.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session as DbSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.services.audit_service import AuditService
from app.services.webhook_service import WebhookService, WebhookSignatureError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

#: Razorpay's signature header.
SIGNATURE_HEADER = "X-Razorpay-Signature"


@router.post(
    "/webhooks/razorpay",
    summary="Verified payment events from Razorpay",
    responses={
        200: {"description": "Processed, ignored as a duplicate, or recorded for reconciliation."},
        400: {"description": "The signature did not verify. No state was changed."},
    },
)
async def razorpay_webhook(
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """One delivery.

    `async` and `Request`-typed on purpose: the raw bytes are needed, and no
    parameter here may be a Pydantic model.
    """
    raw_body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER)
    secret = (
        None
        if settings.razorpay_webhook_secret is None
        else settings.razorpay_webhook_secret.get_secret_value()
    )

    try:
        outcome = WebhookService(db).process(raw_body, signature, secret or "")
    except WebhookSignatureError as error:
        # P§23: an unverified webhook is not a webhook, it is an anonymous HTTP
        # request. The response says nothing about *why* - a caller probing for
        # a valid signature learns nothing from the difference between "no
        # header" and "wrong digest".
        #
        # Deliberately **no rollback**. Verification runs before the body is
        # parsed and long before anything is written, so there is nothing of
        # this request's to undo - and a rollback here could only discard work
        # that belongs to whatever else shares the transaction.
        # The rejection is recorded even though nothing else is: an audit that
        # showed only successful deliveries would hide exactly the events
        # somebody reads the log to find.
        AuditService(db).webhook_signature_rejected()
        db.commit()
        logger.warning("webhook signature rejected", extra={"reason": str(error)})
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"status": "rejected"}
    except Exception:
        # A genuine fault. 500 is correct here precisely because Razorpay will
        # retry it, which is what we want when the failure is ours.
        db.rollback()
        logger.exception("webhook processing faulted")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"status": "error"}

    db.commit()
    return {"status": outcome.status.value.lower(), "event_id": outcome.event_id}
