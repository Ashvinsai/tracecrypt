"""API-level tests for the MOCK complaint queue routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.identity import User
from tests.conftest import login


def test_list_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/complaints/mock").status_code == 401


def test_list_returns_every_fixture_complaint_labeled_mock(
    client: TestClient, user_a: User
) -> None:
    login(client, user_a)
    response = client.get("/api/v1/complaints/mock")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_channel"] == "MOCK_LOCAL_QUEUE"
    assert "not NCRP" in data["note"] or "Not NCRP" in data["note"]
    assert len(data["complaints"]) >= 3
    for complaint in data["complaints"]:
        assert complaint["source_channel"] == "MOCK_LOCAL_QUEUE"
        assert "FICTIONAL" in complaint["reporter_contact"]


def test_get_one_complaint_by_reference(client: TestClient, user_a: User) -> None:
    login(client, user_a)
    response = client.get("/api/v1/complaints/mock/MOCK-Q-2026-000101")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["complaint_reference"] == "MOCK-Q-2026-000101"
    assert data["network_key"] == "tron"


def test_get_unknown_complaint_is_404(client: TestClient, user_a: User) -> None:
    login(client, user_a)
    response = client.get("/api/v1/complaints/mock/MOCK-DOES-NOT-EXIST")
    assert response.status_code == 404


def test_seed_draft_is_never_submitted_and_matches_the_complaint(
    client: TestClient, user_a: User
) -> None:
    login(client, user_a)
    response = client.get("/api/v1/complaints/mock/MOCK-Q-2026-000101/seed-draft")
    assert response.status_code == 200
    draft = response.json()["data"]
    assert draft["mode"] == "incident"
    assert draft["network_key"] == "tron"
    assert draft["address"] == "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
    assert draft["transfer_event_reference"] == "tron:tx_seed_multi:0"
    assert "asset_id" not in draft
    assert "nothing has been submitted" in draft["note"]


def test_seed_draft_for_unknown_complaint_is_404(client: TestClient, user_a: User) -> None:
    login(client, user_a)
    response = client.get("/api/v1/complaints/mock/MOCK-DOES-NOT-EXIST/seed-draft")
    assert response.status_code == 404


def test_seed_draft_from_a_mock_complaint_traces_end_to_end(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    """The whole point of this queue: a complaint's seed draft should be a
    real, traceable input against this project's existing SYNTHETIC fixture,
    not just a shape that looks plausible."""
    login(client, user_a)
    draft = client.get(
        "/api/v1/complaints/mock/MOCK-Q-2026-000101/seed-draft"
    ).json()["data"]

    trace_response = client.post(
        "/api/v1/traces",
        json={
            "network_key": draft["network_key"],
            "address": draft["address"],
            "token_contract": draft["token_contract"],
            "seed_event_reference": draft["transfer_event_reference"],
            "mode": draft["mode"],
        },
    )
    assert trace_response.status_code == 200
    data = trace_response.json()["data"]
    services = [b for b in data["branch_endings"] if b["endpoint_class"] == "known_service"]
    assert services and services[0]["label"]["entity_name"] == "Northwind Exchange (FICTIONAL)"
