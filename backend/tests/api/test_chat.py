"""`POST /api/chat` — the contract ADR-010 froze.

The endpoint is exercised with both halves faked: the model at the `LLMClient`
protocol (ADR-015) and the database session at the `get_db` dependency. That
combination is what makes an HTTP-level test of the agent runnable with no key,
no network and no PostgreSQL — and it is the same seam the layers below use, one
level up.

What is under test is the *contract*: which fields exist, which status code a
business failure gets, and that the structured half of the response is built
from the ranker rather than from what the model happened to say.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.agent.errors import ApiErrorCode
from app.api.routes.chat import get_llm_client
from app.db.session import get_db
from app.llm.errors import LLMRateLimitError
from app.main import create_app
from tests.agent.conftest import (
    FakeClient,
    StubCarts,
    StubCatalog,
    StubCompatibility,
    StubInventory,
    StubRecommendations,
    StubSessions,
    make_ranked,
    make_recommendation,
    make_variant,
    text_reply,
    tool_reply,
)


class FakeDbSession:
    """Stands in for a SQLAlchemy session at the dependency boundary.

    The route only ever calls `commit` and `rollback` on it; every read goes
    through a service. Recording those two is enough to assert the transaction
    behaviour the route promises.
    """

    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


@pytest.fixture
def stubs():
    return {
        "catalog": StubCatalog(),
        "carts": StubCarts(),
        "compatibility": StubCompatibility(),
        "inventory": StubInventory(),
        "recommendations": StubRecommendations(),
        "sessions": StubSessions(),
    }


@pytest.fixture
def chat_client(monkeypatch, stubs):
    """A `TestClient` whose agent runs against stubs.

    `AgentContext.from_session` is the one place the route builds real services
    from a database session, so replacing it is what swaps the whole trusted
    side out at once — without the route knowing anything happened.
    """
    from app.agent import context as context_module

    def fake_from_session(cls, db, merchant_id):
        return cls(
            merchant_id=merchant_id,
            catalog=stubs["catalog"],
            carts=stubs["carts"],
            compatibility=stubs["compatibility"],
            inventory=stubs["inventory"],
            recommendations=stubs["recommendations"],
            sessions=stubs["sessions"],
        )

    monkeypatch.setattr(
        context_module.AgentContext,
        "from_session",
        classmethod(fake_from_session),
    )

    app = create_app()
    db = FakeDbSession()
    app.dependency_overrides[get_db] = lambda: db

    def install(*responses):
        app.dependency_overrides[get_llm_client] = lambda: FakeClient(*responses)
        return TestClient(app), db

    return install


# --------------------------------------------------------------------------
# The response shape
# --------------------------------------------------------------------------


def test_every_field_is_present_even_when_empty(chat_client):
    """ADR-010: absent data is `null` or `[]`, never a missing key.

    A client that had to test for key existence would be a client whose
    rendering depended on which branch the agent happened to take.
    """
    client, _ = chat_client(text_reply("Which phone do you have?"))

    body = client.post("/api/chat", json={"message": "I need a case"}).json()

    assert set(body) == {
        "session_id",
        "state",
        "message",
        "recommendations",
        "cart",
        "trace",
        "error",
    }
    assert body["recommendations"] == []
    assert body["cart"] is None
    assert body["trace"] is None
    assert body["error"] is None


def test_a_first_turn_mints_a_session(chat_client):
    """Server-minted, never client-chosen (ADR-010)."""
    client, _ = chat_client(text_reply("hello"))

    body = client.post("/api/chat", json={"message": "hi"}).json()

    assert uuid.UUID(body["session_id"])


def test_an_unknown_session_is_rejected_rather_than_created(chat_client):
    """ADR-010's named M5 test. A typo must not strand a conversation."""
    client, db = chat_client(text_reply("hello"))

    response = client.post("/api/chat", json={"session_id": str(uuid.uuid4()), "message": "hi"})

    assert response.status_code == 404
    assert "SESSION_NOT_FOUND" in response.json()["detail"]["message"]
    assert db.rolled_back == 1


def test_recommendations_are_typed_and_money_is_a_string(chat_client, stubs):
    """ADR-008: `"999.00"`, never `999.0`.

    Asserted on the raw response text, because a `Decimal` field would still be
    serialized as a JSON number by most encoders and the whole point is that a
    client's parser never sees one.
    """
    stubs["recommendations"].result = make_recommendation(
        make_ranked(make_variant(sku="CASE-IP16-BLK", price="999.00"))
    )
    client, _ = chat_client(
        tool_reply("search_catalog", {"category": "phone_case"}),
        text_reply("Here is one."),
    )

    response = client.post("/api/chat", json={"message": "a case under 1500"})
    body = response.json()

    assert body["recommendations"][0]["price"] == "999.00"
    assert '"price":"999.00"' in response.text.replace(" ", "")


def test_the_reason_is_the_engines_label_not_the_models_prose(chat_client, stubs):
    """ADR-010, closing A7. The model may paraphrase it; it may not author it."""
    stubs["recommendations"].result = make_recommendation(make_ranked(make_variant()))
    client, _ = chat_client(
        tool_reply("search_catalog", {"category": "phone_case"}),
        text_reply("This one is great because I like it."),
    )

    body = client.post("/api/chat", json={"message": "a case"}).json()

    assert body["recommendations"][0]["reason"] == "Best overall"
    assert body["recommendations"][0]["reason_code"] == "BEST_OVERALL"


def test_a_product_the_model_invented_is_not_in_the_structured_half(chat_client, stubs):
    """F§9's whole reason for existing: the frontend renders cards from data."""
    stubs["recommendations"].result = make_recommendation(make_ranked(make_variant(sku="REAL-SKU")))
    client, _ = chat_client(
        tool_reply("search_catalog", {"category": "phone_case"}),
        text_reply("I recommend the GhostCase at Rs 99 (SKU GHOST-1)."),
    )

    body = client.post("/api/chat", json={"message": "a case"}).json()

    assert [r["sku"] for r in body["recommendations"]] == ["REAL-SKU"]
    assert "GHOST-1" not in str(body["recommendations"])


def test_no_recommendation_carries_a_stock_quantity(chat_client, stubs):
    """ADR-010, closing E5: coarse status only in a buyer-facing payload."""
    stubs["recommendations"].result = make_recommendation(make_ranked(make_variant()))
    client, _ = chat_client(
        tool_reply("search_catalog", {"category": "phone_case"}), text_reply("here")
    )

    body = client.post("/api/chat", json={"message": "a case"}).json()

    assert body["recommendations"][0]["stock_status"] == "IN_STOCK"
    assert "quantity" not in body["recommendations"][0]


# --------------------------------------------------------------------------
# Status codes (ADR-010)
# --------------------------------------------------------------------------


def test_a_failed_turn_is_still_a_200(chat_client):
    """A business or model failure is a successful conversational turn with an
    `error` body. Returning 4xx would put an outcome the frontend must render as
    a recovery flow into the client's network-error path.
    """
    client, _ = chat_client(LLMRateLimitError("rate limited"))

    response = client.post("/api/chat", json={"message": "hi"})

    assert response.status_code == 200
    assert response.json()["error"]["code"] == ApiErrorCode.SERVER_ERROR.value


def test_an_error_body_never_carries_the_providers_message(chat_client):
    """F§25: never a Python exception, never a provider string."""
    client, _ = chat_client(LLMRateLimitError("upstream said 429 slow down"))

    body = client.post("/api/chat", json={"message": "hi"}).json()

    assert "429" not in body["error"]["message"]
    assert "upstream" not in body["error"]["message"]


def test_a_malformed_body_is_a_422(chat_client):
    client, _ = chat_client(text_reply("hi"))

    assert client.post("/api/chat", json={}).status_code == 422
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_an_unexpected_field_is_refused(chat_client):
    """`extra="forbid"`. A client sending `merchant_id` is a client trying to
    choose one, and ADR-002 resolves the merchant server-side."""
    client, _ = chat_client(text_reply("hi"))

    response = client.post("/api/chat", json={"message": "hi", "merchant_id": str(uuid.uuid4())})

    assert response.status_code == 422


def test_a_successful_turn_commits_once(chat_client):
    client, db = chat_client(text_reply("hi"))

    client.post("/api/chat", json={"message": "hi"})

    assert db.committed == 1


# --------------------------------------------------------------------------
# The published contract
# --------------------------------------------------------------------------


def test_the_endpoint_is_published_in_the_openapi_document():
    """M14 builds against this document, so it has to describe the real shape."""
    schema = create_app().openapi()

    assert "/api/chat" in schema["paths"]
    assert "post" in schema["paths"]["/api/chat"]


def test_the_error_code_enum_in_the_schema_is_f25s_closed_list():
    """A code outside F§25 would be one no client knows how to render."""
    from app.agent.errors import API_ERROR_CODES

    schema = create_app().openapi()
    published = schema["components"]["schemas"]["ApiErrorCode"]["enum"]

    assert sorted(published) == sorted(API_ERROR_CODES)
