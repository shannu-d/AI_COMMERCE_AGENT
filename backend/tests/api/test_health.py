"""The health endpoint.

M0 exit criteria: the application starts and a basic health endpoint works.
These tests boot the real application through its lifespan, so a failure here
means the app genuinely does not start.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import __version__


def test_application_boots_and_health_responds(client: TestClient) -> None:
    response = client.get("/api/health")

    # 200 with a database, 503 without one. Both are the endpoint working.
    assert response.status_code in (200, 503)

    body = response.json()
    assert body["app"]
    assert body["version"] == __version__
    assert body["environment"] == "test"
    assert set(body["database"]) == {"configured", "reachable", "error_kind"}


def test_health_reports_ok_when_the_database_is_reachable(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        lambda: (True, None),
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == {"configured": True, "reachable": True, "error_kind": None}


def test_health_reports_degraded_when_the_database_is_unreachable(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        lambda: (False, "OperationalError"),
    )

    response = client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"]["reachable"] is False
    assert body["database"]["error_kind"] == "OperationalError"


def test_health_never_discloses_connection_details(client: TestClient, monkeypatch) -> None:
    """A health endpoint is usually unauthenticated.

    ``check_database_connection`` returns an exception class name and never a
    message, because a psycopg connection error can carry the connection URL and
    the URL carries a password.
    """
    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        lambda: (False, "OperationalError"),
    )

    raw = client.get("/api/health").text.lower()

    for leak in ("password", "postgresql://", "postgresql+psycopg://", "@localhost", "5432"):
        assert leak not in raw


def test_openapi_is_served_outside_production(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200
