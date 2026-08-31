"""Conversation state transitions (A§25, A§26, ADR-010).

The enum itself lives in `app/domain/conversation.py`, because the ORM model and
the runtime both need it and neither may depend on the other. What lives here is
the part that is genuinely the runtime's: deciding which state a finished turn
leaves the conversation in.

**This is display state and nothing else.** ADR-010 says the UI drives its
affordances from it; ADR-007 says the Policy Engine never reads it. The
distinction matters because the three state machines share value names. A session
whose `conversation_state` is `APPROVED` authorizes nothing — only a row in
`approvals` does — and no function in this module can produce an authorization,
because none of them writes anything.

The transitions M5 can produce are few, and that is correct rather than
incomplete: a read-only agent searches, recommends, asks for clarification, or
fails. Selecting a product, proposing a cart and waiting for approval arrive with
M7 and M8, and `REACHABLE_FROM` records which milestone owns each.
"""

from __future__ import annotations

from app.domain.conversation import ConversationState

__all__ = ["next_state"]


def next_state(*, memory_has_results: bool, tool_failed: bool) -> ConversationState:
    """Where a completed turn leaves the conversation.

    Ordering is deliberate. Results win over a failed tool: a turn that searched
    twice, had one call fail and still produced grounded recommendations is a
    turn that recommended something, and showing the buyer an error state
    alongside real results would misdescribe what happened.

    A turn with neither results nor a failure is a conversation still being
    understood — the model asked the buyer something, which A§51 lists as its own
    termination condition and which the buyer sees as a question rather than as
    an empty result set.
    """
    if memory_has_results:
        return ConversationState.RECOMMENDING
    if tool_failed:
        return ConversationState.TOOL_ERROR
    return ConversationState.NEED_CLARIFICATION
