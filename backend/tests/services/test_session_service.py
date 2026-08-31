"""Conversation persistence against a real PostgreSQL (ADR-006, closes C3).

These need a database and say so. ADR-006 rejects in-memory session state
explicitly — it would make the price-drift and duplicate-request scenarios
untestable across processes — so testing this service against anything but
PostgreSQL would be testing the thing the decision rejected.

What the tests are mostly about is the constraints. `conversation_state` has a
CHECK against the enum, `session_messages` has `UNIQUE(session_id, sequence)`,
and both exist so that a bug in this module fails at the database rather than
producing a conversation that quietly makes no sense.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.domain.conversation import ConversationState
from app.services.session_service import SessionService

pytestmark = pytest.mark.requires_db


@pytest.fixture
def sessions(session: Session) -> SessionService:
    return SessionService(session)


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


def test_a_new_session_starts_in_new_session(sessions, merchant_id):
    view = sessions.create(merchant_id)

    assert view.conversation_state is ConversationState.NEW_SESSION
    assert view.intent == {}


def test_a_created_session_can_be_read_back(sessions, merchant_id):
    created = sessions.create(merchant_id)

    fetched = sessions.get(merchant_id, created.id)

    assert fetched is not None
    assert fetched.id == created.id


def test_an_unknown_id_is_none_rather_than_an_error(sessions, merchant_id):
    """ADR-010 turns this into SESSION_NOT_FOUND at the route. The service says
    "no such row", which is a different fact from "something went wrong"."""
    assert sessions.get(merchant_id, uuid.uuid4()) is None


def test_a_session_is_invisible_to_another_merchant(sessions, merchant_id):
    """ADR-002. Scoping excludes; it does not merely filter.

    A session id is a UUID, so guessing one is not the threat — the threat is a
    query that forgot `merchant_id` and would therefore serve one merchant's
    conversation to another.
    """
    created = sessions.create(merchant_id)
    other_merchant = uuid.UUID("00000000-0000-5000-8000-00000000dead")

    assert sessions.get(other_merchant, created.id) is None


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------


def test_state_moves_and_persists(sessions, merchant_id):
    created = sessions.create(merchant_id)

    sessions.set_state(merchant_id, created.id, ConversationState.RECOMMENDING)

    assert sessions.get(merchant_id, created.id).conversation_state is (
        ConversationState.RECOMMENDING
    )


@pytest.mark.parametrize("state", list(ConversationState))
def test_every_enum_value_satisfies_the_check_constraint(sessions, merchant_id, state):
    """The CHECK is built from `CONVERSATION_STATES`, so this proves the column
    and the enum have not drifted apart — including the states no milestone
    before M12 can reach."""
    created = sessions.create(merchant_id)

    sessions.set_state(merchant_id, created.id, state)

    assert sessions.get(merchant_id, created.id).conversation_state is state


def test_a_state_outside_the_enum_is_refused_by_the_database(session, sessions, merchant_id):
    """Defence in depth. `set_state` takes a `ConversationState`, so this can
    only happen through raw SQL — and the constraint stops it there too."""
    from sqlalchemy import text

    created = sessions.create(merchant_id)
    session.flush()

    with pytest.raises((IntegrityError, DBAPIError)):
        session.execute(
            text("UPDATE sessions SET conversation_state = 'PURCHASED' WHERE id = :id"),
            {"id": created.id},
        )
        session.flush()


# --------------------------------------------------------------------------
# Intent (A§37)
# --------------------------------------------------------------------------


def test_intent_round_trips_as_an_object(sessions, merchant_id):
    created = sessions.create(merchant_id)

    sessions.set_intent(merchant_id, created.id, {"budget": {"amount": "1500.00"}})

    assert sessions.get(merchant_id, created.id).intent == {"budget": {"amount": "1500.00"}}


def test_intent_is_replaced_rather_than_merged(sessions, merchant_id):
    """The merge is `app.llm.extractor.merge_intent`, which knows the difference
    between a field the model omitted and one it cleared. A second merge here,
    with a different rule, is how two layers come to disagree about what the
    buyer asked for.
    """
    created = sessions.create(merchant_id)
    sessions.set_intent(merchant_id, created.id, {"a": 1, "b": 2})

    sessions.set_intent(merchant_id, created.id, {"a": 9})

    assert sessions.get(merchant_id, created.id).intent == {"a": 9}


# --------------------------------------------------------------------------
# History (A§38)
# --------------------------------------------------------------------------


def test_messages_are_numbered_from_zero_in_order(sessions, merchant_id):
    created = sessions.create(merchant_id)

    sessions.append_message(merchant_id, created.id, role="user", content="one")
    sessions.append_message(merchant_id, created.id, role="assistant", content="two")

    history = sessions.history(merchant_id, created.id)
    assert [(m.sequence, m.role, m.content) for m in history] == [
        (0, "user", "one"),
        (1, "assistant", "two"),
    ]


def test_history_is_oldest_first_even_when_limited(sessions, merchant_id):
    """The model reads a conversation forwards; a reversed window would be a
    conversation that appears to run backwards."""
    created = sessions.create(merchant_id)
    for i in range(5):
        sessions.append_message(merchant_id, created.id, role="user", content=str(i))

    history = sessions.history(merchant_id, created.id, limit=2)

    assert [m.content for m in history] == ["3", "4"]


def test_tool_rows_are_excluded_from_history_by_default(sessions, merchant_id):
    """A§50 permits retaining tool results *during* a turn. Replaying every one
    into the next turn's prompt is how a context window fills with data the
    structured intent already carries (L§27)."""
    created = sessions.create(merchant_id)
    sessions.append_message(merchant_id, created.id, role="user", content="hi")
    sessions.append_message(
        merchant_id, created.id, role="tool", tool_payload={"tool": "search_catalog"}
    )

    assert [m.role for m in sessions.history(merchant_id, created.id)] == ["user"]


def test_a_tool_row_may_carry_a_payload_and_no_prose(sessions, merchant_id):
    """The CHECK requires content or a payload; a tool result is the payload case."""
    created = sessions.create(merchant_id)

    sessions.append_message(
        merchant_id, created.id, role="tool", tool_payload={"result": {"success": True}}
    )

    rows = sessions.history(merchant_id, created.id, roles=("tool",))
    assert rows[0].tool_payload == {"result": {"success": True}}


def test_a_message_with_neither_content_nor_payload_is_refused(sessions, merchant_id):
    """Recorded nothing is not a message. The service refuses before the database
    has to, so the error names the problem rather than the constraint."""
    created = sessions.create(merchant_id)

    with pytest.raises(ValueError, match="content, a payload, or both"):
        sessions.append_message(merchant_id, created.id, role="user")


def test_appending_to_an_unknown_session_raises(sessions, merchant_id):
    """A foreign key would catch it, but at flush time and with a database
    message. Failing here names the session instead."""
    with pytest.raises(LookupError):
        sessions.append_message(merchant_id, uuid.uuid4(), role="user", content="hi")


def test_history_of_an_unknown_session_is_empty(sessions, merchant_id):
    assert sessions.history(merchant_id, uuid.uuid4()) == []


def test_messages_do_not_leak_between_sessions(sessions, merchant_id):
    first = sessions.create(merchant_id)
    second = sessions.create(merchant_id)
    sessions.append_message(merchant_id, first.id, role="user", content="mine")

    assert sessions.history(merchant_id, second.id) == []
