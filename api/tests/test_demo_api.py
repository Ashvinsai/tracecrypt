"""Tests for the read-only demo JSON facade (``/api/v1/demo``).

Same discipline as the console tests: integration checks hit the real routes
against artifacts on disk and skip (never fail) when this checkout has no
``var/`` bundle. Nothing needs a session, a provider, or a live chain.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.demo_artifacts import (
    _resolve_dir,
    list_candidate_reports,
    list_cctp_bundles,
    list_evidence_bundles,
    list_routing_bundles,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_VALIDATION = REPO_ROOT / "var" / "live-validation"


def _has_trace_bundle() -> bool:
    return any(LIVE_VALIDATION.glob("*/trace.json")) or (REPO_ROOT / "var" / "trace.json").is_file()


requires_trace = pytest.mark.skipif(
    not _has_trace_bundle(), reason="saved trace artifacts are not present"
)
requires_cctp = pytest.mark.skipif(
    not any(b["protocol"] == "circle_cctp_v2" for b in list_cctp_bundles()),
    reason="no saved CCTP bundle is present",
)
requires_routing = pytest.mark.skipif(
    not list_routing_bundles()["bundles"], reason="no saved routing bundle is present"
)
requires_candidates = pytest.mark.skipif(
    not list_candidate_reports(), reason="no saved candidate report is present"
)
requires_evidence = pytest.mark.skipif(
    not list_evidence_bundles(), reason="no saved evidence bundle is present"
)


def test_presets_are_listed_without_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/demo/presets")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["count"] == len(data["presets"])
    assert data["count"] >= 1


def test_unknown_preset_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/demo/presets/does-not-exist").status_code == 404


@requires_trace
def test_preset_detail_carries_trace_and_graph(client: TestClient) -> None:
    presets = client.get("/api/v1/demo/presets").json()["data"]["presets"]
    with_trace = next(p for p in presets if p["has_trace"])
    response = client.get(f"/api/v1/demo/presets/{with_trace['id']}")
    assert response.status_code == 200
    detail = response.json()["data"]
    assert detail["data_mode"] in ("LIVE", "RECORDED_PUBLIC", "SYNTHETIC")
    assert detail["trace"] is not None
    assert detail["graph"] is not None
    assert "wallets" in detail["graph"]["stats"]


def test_preset_detail_never_serializes_provider_secrets(client: TestClient) -> None:
    from app.core.settings import get_settings

    secret = get_settings().tron_api_key
    presets = client.get("/api/v1/demo/presets").json()["data"]["presets"]
    for preset in presets:
        body = client.get(f"/api/v1/demo/presets/{preset['id']}").text
        if secret:
            assert secret not in body
        # Only the boolean ``*_api_key_configured`` flag may mention a key.
        assert '"api_key"' not in body


@requires_cctp
def test_cctp_bundle_reports_api_attestation_not_local_signature(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/demo/cctp")
    assert response.status_code == 200
    bundles = response.json()["data"]["bundles"]
    assert bundles
    for bundle in bundles:
        link = bundle["link"]
        assert link["linkage_status"] in ("COMPLETE", "INCOMPLETE", "FAILED", "AMBIGUOUS")
        # Circle API metadata must not masquerade as local cryptographic proof.
        assert link["attestation_source"] == "circle_iris_api"
        assert link["attestation_signature_verified"] is False
        assert "limitations" in link


@requires_cctp
def test_cctp_bundle_integrity_verifies_and_hides_secrets(client: TestClient) -> None:
    body = client.get("/api/v1/demo/cctp").text.lower()
    for needle in ("api_key", "apikey", "authorization", "bearer "):
        assert needle not in body
    for bundle in client.get("/api/v1/demo/cctp").json()["data"]["bundles"]:
        integrity = bundle["integrity"]
        if integrity["available"]:
            assert integrity["failed"] == 0
            assert integrity["missing"] == 0


@requires_routing
def test_routing_is_labeled_decision_support_not_evidence(client: TestClient) -> None:
    response = client.get("/api/v1/demo/routing")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["bundles"]
    bundle = data["bundles"][0]
    assert bundle["manifest"]["artifact_class"] == "DECISION_SUPPORT_METADATA"
    assert "not blockchain evidence" in bundle["manifest"]["caveat"].lower()
    assert bundle["summary"]["notice"].startswith("DECISION SUPPORT METADATA")
    assert bundle["summary"]["unsafe_action_execution_rate"] == 0.0


@requires_candidates
def test_candidates_are_never_reported_as_verified_service_control(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/demo/candidates")
    assert response.status_code == 200
    reports = response.json()["data"]["reports"]
    assert reports
    for entry in reports:
        assert entry["report"]["report_type"] == "vasp_candidate_neighborhood"
        for candidate in entry["report"].get("candidates", []):
            assert candidate["relationship_type"] != "service_control"
            assert candidate["review_status"] != "accepted"
            assert candidate["not_service_control_reason"]


@requires_evidence
def test_evidence_manifest_verifies(client: TestClient) -> None:
    response = client.get("/api/v1/demo/evidence")
    assert response.status_code == 200
    bundles = response.json()["data"]["bundles"]
    assert bundles
    integrity = bundles[0]["integrity"]
    assert integrity["available"] is True
    assert integrity["failed"] == 0
    assert integrity["missing"] == 0
    assert "caveat" in integrity


def test_run_id_resolution_rejects_traversal() -> None:
    root = LIVE_VALIDATION
    assert _resolve_dir(root, "../data") is None
    assert _resolve_dir(root, "a/b") is None
    assert _resolve_dir(root, "") is None
    assert _resolve_dir(root, "..") is None


def test_demo_facade_paths_cannot_escape_their_roots() -> None:
    # Every returned run id must be a plain directory name under var/.
    for collection in (
        list_cctp_bundles(),
        list_candidate_reports(),
        list_evidence_bundles(),
        list_routing_bundles()["bundles"],
    ):
        for entry in collection:
            run_id = entry["run_id"]
            assert "/" not in run_id and ".." not in run_id


def test_run_id_resolution_rejects_absolute_and_symlink_escapes(tmp_path) -> None:
    from app.services.demo_artifacts import _resolve_dir

    root = tmp_path / "root"
    root.mkdir()
    (root / "good").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("not for the demo")

    assert _resolve_dir(root, "good") is not None
    assert _resolve_dir(root, str(outside)) is None  # absolute path
    assert _resolve_dir(root, "/etc") is None
    assert _resolve_dir(root, "../../etc") is None

    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        return  # symlinks unavailable in this environment; the checks above still ran
    assert _resolve_dir(root, "escape") is None  # resolves outside root


#: The demo facade is a local prototype surface. In production it must not be
#: registered at all -- hiding it in the frontend is not enforcement.
_DEMO_PATHS = (
    "/api/v1/demo/presets",
    "/api/v1/demo/cctp",
    "/api/v1/demo/routing",
    "/api/v1/demo/evidence",
    "/api/v1/demo/candidates",
    "/api/v1/demo/capabilities",
    "/investigator",
)


def test_demo_facade_is_absent_in_production(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.core.settings import get_settings
    from app.main import create_app

    monkeypatch.setenv("CFA_APP_ENV", "prod")
    monkeypatch.setenv("CFA_SECRET_KEY", "h" * 48)
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as prod_client:
            for path in _DEMO_PATHS:
                response = prod_client.get(path)
                assert response.status_code == 404, f"{path} was served in prod"
    finally:
        get_settings.cache_clear()


def test_demo_facade_is_present_outside_production(client: TestClient) -> None:
    # The counterpart to the prod test: this checkout (app_env=test) serves it.
    assert client.get("/api/v1/demo/presets").status_code == 200


def test_demo_responses_never_contain_configured_secrets(client: TestClient) -> None:
    """Fetch every demo response and assert no configured secret value leaks.

    Only counts are asserted; no secret is printed.
    """
    from app.core.settings import get_settings

    settings = get_settings()
    secrets = [
        value
        for value in (
            settings.tron_api_key,
            settings.ethereum_rpc_url,
            settings.bsc_rpc_url,
            settings.base_rpc_url,
            settings.clm_api_key,
            settings.secret_key,
        )
        if value
    ]

    bodies: list[tuple[str, str]] = []
    for path in (
        "/api/v1/demo/presets",
        "/api/v1/demo/cctp",
        "/api/v1/demo/routing",
        "/api/v1/demo/candidates",
        "/api/v1/demo/evidence",
        "/api/v1/demo/capabilities",
        "/api/v1/meta",
    ):
        bodies.append((path, client.get(path).text))
    for preset in client.get("/api/v1/demo/presets").json()["data"]["presets"]:
        path = f"/api/v1/demo/presets/{preset['id']}"
        bodies.append((path, client.get(path).text))

    leaks = 0
    markers = ("CFA_TRON_API_KEY", "CFA_CLM_API_KEY", "Authorization", "Bearer ", "cfa_session")
    for _path, body in bodies:
        for secret in secrets:
            if secret in body:
                leaks += 1
        for marker in markers:
            if marker in body:
                leaks += 1
    assert leaks == 0, f"{leaks} secret/header marker(s) leaked into demo responses"


def test_every_demo_run_id_is_allow_listed() -> None:
    from app.services.demo_artifacts import RUN_ID

    entries: list[dict] = []
    entries += list_cctp_bundles()
    entries += list_candidate_reports()
    entries += list_evidence_bundles()
    entries += list_routing_bundles()["bundles"]
    for entry in entries:
        assert RUN_ID.fullmatch(entry["run_id"]), entry["run_id"]

