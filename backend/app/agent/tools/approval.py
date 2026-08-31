"""`request_approval` (T7, M8; ADR-007, ADR-009, P§9, L§21).

The most carefully limited tool in the system, because it is the one whose name
suggests it can do the thing the whole architecture forbids.

`architecture.md` lists `request_approval()` among the model-callable tools while
defining approval everywhere else as an explicit human act. ADR-007 resolves that
by **re-scoping rather than removing**: the tool asks, and asking is a legitimate
thing for an agent to do. It moves the conversation to `WAITING_FOR_APPROVAL`,
surfaces the authoritative cart for confirmation, and writes an approval row with
`status = 'PENDING'`.

**It cannot write `APPROVED`, and not because it declines to.** The service method
it calls — `ApprovalService.request` — has no `status` parameter, and the value it
writes is a literal in that method's body. There is no argument, no overload and
no refactor of this module that produces an authorization. `POST /api/cart/approve`
is the only path that can, and it exists precisely so that the authorization
signal originates from a buyer's deliberate action rather than from a model's
judgement about what "yeah, sure" meant.

P§9 is the sentence this enforces: "The system must not interpret 'Show me the
cart' as approval. Similarly: 'How much is it?' is not approval."
"""

from __future__ import annotations

from typing import Any

from app.agent.context import AgentContext, TurnMemory
from app.agent.errors import ToolError, ToolErrorCode
from app.agent.tools.cart import serialize_cart
from app.domain.conversation import ConversationState
from app.llm.tool_schemas import RequestApprovalArgs
from app.services.approval_service import ApprovalError

__all__ = ["request_approval"]


def request_approval(
    context: AgentContext, memory: TurnMemory, args: RequestApprovalArgs
) -> dict[str, Any]:
    """T7. Ask the buyer to confirm the current cart. Authorizes nothing.

    The cart is re-read here rather than taken from anything the model holds, so
    what the buyer is asked to confirm is the authoritative total as it is at
    this instant — not the one a `propose_cart` returned earlier in the turn and
    which a later call may have changed.
    """
    session_id = memory.require_session()

    cart = context.carts.get_active(context.merchant_id, session_id)
    if cart is None or cart.is_empty:
        raise ToolError(
            ToolErrorCode.INVALID_ARGUMENTS,
            "there is nothing in the cart to confirm",
        )
    if cart.has_unavailable_items:
        # RULE 5. Asking a buyer to approve something nobody can sell them is
        # asking them to authorize a failure.
        raise ToolError(
            ToolErrorCode.OUT_OF_STOCK,
            "something in the cart is no longer available; the cart needs to change first",
        )

    try:
        approval = context.approvals.request(session_id, cart)
    except ApprovalError as error:
        raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, error.message) from error

    context.sessions.set_state(
        context.merchant_id, session_id, ConversationState.WAITING_FOR_APPROVAL
    )

    payload = serialize_cart(cart)
    payload["approval"] = {
        "approval_id": str(approval.id),
        # PENDING, always. Stated in the payload so the model sees the word it
        # is not allowed to change, rather than inferring anything from silence.
        "status": approval.status.value,
        "expires_at": approval.expires_at.isoformat(),
        "cart_version": approval.cart_version,
    }
    payload["awaiting_user_confirmation"] = True
    # Said plainly, because it is the one thing the model must not get wrong and
    # the one thing a fluent answer could easily imply otherwise.
    payload["note"] = (
        "This records that confirmation was requested. It is not approval. "
        "Only the buyer can approve, in the application."
    )
    return payload
