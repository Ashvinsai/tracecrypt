"""B07: every response declares its data mode and request id (D009)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.identity import User
from tests.conftest import login


def test_meta_envelope(client: TestClient, user_a: User, tron, synthetic_usdt) -> None:
    login(client, user_a)
    response = client.get("/api/v1/meta")
    assert response.status_code == 200

    meta = response.json()["meta"]
    assert meta["data_mode"] == "SYNTHETIC"
    assert meta["request_id"]
    assert meta["engine_version"]
    assert meta["analysis_cutoff"]
    assert response.headers["x-data-mode"] == "SYNTHETIC"
    assert response.headers["x-request-id"] == meta["request_id"]


def test_meta_capabilities_match_operational_status(
    client: TestClient, user_a: User, monkeypatch
) -> None:
    """Legacy flags and detailed capability rows derive from the same status."""
    from app.routes import health
    from app.services.operational_status import capability_details, legacy_capabilities

    settings = health.get_settings()
    monkeypatch.setattr(health, "load_readiness", lambda: None)
    monkeypatch.setattr(health, "load_anomaly_evaluation", lambda: None)
    monkeypatch.setattr(health, "summarize_presets", lambda: [])
    monkeypatch.setattr(
        health, "has_recorded_successful_live_validation", lambda **_kwargs: False
    )
    monkeypatch.setattr(health, "has_recorded_cctp_live_validation", lambda: False)
    evm_states = {
        "ethereum": {"rpc_configured": False, "historical_live_run_recorded": False},
        "bsc": {"rpc_configured": False, "historical_live_run_recorded": False},
    }
    monkeypatch.setattr(health, "evm_network_states", lambda _settings: evm_states)

    login(client, user_a)
    data = client.get("/api/v1/meta").json()["data"]
    capabilities = data["capabilities"]
    details = data["capability_details"]
    detail_by_key = {row["key"]: row for row in details}
    expected = capability_details(
        readiness=None,
        saved_run_count=0,
        live_key_configured=bool(settings.tron_api_key),
        configured_data_mode=settings.data_mode.value,
        historical_live_run_recorded=False,
        evm_networks=evm_states,
    )

    assert capabilities == legacy_capabilities(details)
    assert details == expected
    assert capabilities["tracing_engine"] is True
    assert capabilities["label_registry"] is True
    assert capabilities["live_tracing"] is False
    assert detail_by_key["chronological_tracing"]["implementation_status"] == "implemented"
    assert detail_by_key["label_registry"]["implementation_status"] == "implemented"
    assert detail_by_key["government_connectors"]["status"] == "not_configured"
    assert detail_by_key["government_connectors"]["implementation_status"] == "not_built"
    assert detail_by_key["government_connectors"]["configuration_status"] == "not_configured"
    assert detail_by_key["multi_chain"]["status"] == "partial"
    assert detail_by_key["evm_token_tracing"]["implementation_status"] == "implemented"
    assert detail_by_key["evm_token_tracing"]["live_verified"] is False
    assert detail_by_key["bridge_tracing"]["status"] == "partial"
    assert detail_by_key["bridge_tracing"]["implementation_status"] == "partial"
    assert detail_by_key["ml_anomaly_ranking"]["trained_real_model"] is False


def test_meta_does_not_claim_live_acquisition_without_requirements(
    client: TestClient, user_a: User
) -> None:
    login(client, user_a)
    data = client.get("/api/v1/meta").json()["data"]
    live = {row["key"]: row for row in data["capability_details"]}["live_acquisition"]

    assert data["capabilities"]["live_tracing"] is False
    assert live["status"] != "available"
    assert live["implementation_status"] == "implemented"
    assert live["configuration_status"] == "not_configured"
    assert live["live_verified"] is False


def test_supplied_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/healthz", headers={"x-request-id": "trace-me-123"})
    assert response.headers["x-request-id"] == "trace-me-123"
