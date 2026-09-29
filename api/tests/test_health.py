"""B01: liveness is open; readiness reports rather than throws."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_open(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_component_state(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert set(body["checks"]) == {"database", "redis"}
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] in ("ok", "not configured")
