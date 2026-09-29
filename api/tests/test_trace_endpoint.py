"""Stage 1 vertical slice, end to end through the API.

Seed event -> fixture adapter -> tracer -> CSV anchors -> JSON result -> HTML.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.settings import DataMode
from app.models.chain import Asset, Network
from app.models.enums import AssetKind
from app.models.identity import User
from tests.conftest import login

VICTIM = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
SERVICE = "TBvGC1Nd8i5wmj185HTdoTWAZPmRUTFBZz"
SUPPORTED_CONTRACT = "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY"
SPOOF_CONTRACT = "TUJmRrUmPrJZgqhRGjGKwbAzqZx3EHpoW2"
SEED_EVENT = "tron:tx_seed_multi:0"


def request_body(**overrides) -> dict:
    body = {
        "network_key": "tron",
        "address": VICTIM,
        "token_contract": SUPPORTED_CONTRACT,
        "seed_event_reference": SEED_EVENT,
        "mode": "incident",
        "analysis_cutoff": "2027-01-01T00:00:00Z",
    }
    body.update(overrides)
    return body


def _spoof_asset(db: Session, network: Network) -> Asset:
    asset = Asset(
        network_id=network.id,
        kind=AssetKind.token,
        token_contract=SPOOF_CONTRACT,
        decimals=6,
        display_symbol="USDT-SYN",
        is_supported=True,
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(asset)
    db.flush()
    return asset


def test_trace_reaches_the_sourced_service_anchor(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    response = client.post("/api/v1/traces", json=request_body())
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["meta"]["data_mode"] == "SYNTHETIC"
    data = body["data"]

    assert data["seed"]["event_reference"] == SEED_EVENT
    assert data["scope"]["case_flow_linkage"] == "established"

    seed_transfer = data["seed_transfer"]
    assert seed_transfer is not None, "the case-link transfer must be in the result"
    assert seed_transfer["hop_depth"] == 0
    assert seed_transfer["event_reference"] == SEED_EVENT
    assert seed_transfer["from_address"] == VICTIM
    assert isinstance(seed_transfer["amount_base_units"], str)

    services = [b for b in data["branch_endings"] if b["endpoint_class"] == "known_service"]
    assert services, "the trace should reach the sourced anchor"
    assert services[0]["address"] == SERVICE
    assert services[0]["label"]["entity_name"] == "Northwind Exchange (FICTIONAL)"
    assert services[0]["label"]["source_reference"]
    assert services[0]["label"]["methodology"]


def test_amounts_are_strings_and_exact(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    data = client.post("/api/v1/traces", json=request_body()).json()["data"]
    for transfer in data["observed_transfers"]:
        assert isinstance(transfer["amount_base_units"], str)
        assert re.fullmatch(r"-?\d+", transfer["amount_base_units"])
        base = int(transfer["amount_base_units"])
        whole, _, frac = transfer["amount_display"].partition(".")
        assert int(whole + frac) == base


def test_candidate_is_reported_without_terminating_the_trace(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    data = client.post("/api/v1/traces", json=request_body()).json()["data"]
    candidates = [b for b in data["branch_endings"] if b["endpoint_class"] == "deposit_candidate"]
    assert candidates, "the fixture routes funds through a candidate address"
    followed = {t["from_address"] for t in data["observed_transfers"]}
    assert candidates[0]["address"] in followed, "tracing must continue past a candidate"


def test_every_ending_defaults_to_allocation_unknown(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    data = client.post("/api/v1/traces", json=request_body()).json()["data"]
    assert data["branch_endings"]
    assert all(b["case_amount_basis"] == "allocation_unknown" for b in data["branch_endings"])


def test_spoofed_contract_traces_a_different_asset(
    client: TestClient, db: Session, user_a: User, tron, synthetic_usdt
) -> None:
    """A contract wearing the same ticker yields a different trace, not the same one."""
    _spoof_asset(db, tron)
    login(client, user_a)

    supported = client.post("/api/v1/traces", json=request_body()).json()["data"]
    spoofed = client.post(
        "/api/v1/traces",
        json=request_body(token_contract=SPOOF_CONTRACT, seed_event_reference="tron:tx_spoof:0"),
    ).json()["data"]

    supported_refs = {t["event_reference"] for t in supported["observed_transfers"]}
    spoof_refs = {t["event_reference"] for t in spoofed["observed_transfers"]}
    assert supported_refs.isdisjoint(spoof_refs)


def test_address_only_mode_asserts_no_case_linkage(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    data = client.post(
        "/api/v1/traces",
        json=request_body(mode="address_discovery", seed_event_reference=None),
    ).json()["data"]
    assert data["scope"]["case_flow_linkage"] == "not_established"


def test_unknown_seed_event_is_rejected_not_silently_ignored(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    response = client.post(
        "/api/v1/traces", json=request_body(seed_event_reference="tron:does-not-exist:0")
    )
    assert response.status_code == 422
    assert "was not found" in response.json()["error"]["message"]


def test_trace_requires_authentication(client: TestClient, tron, synthetic_usdt) -> None:
    assert client.post("/api/v1/traces", json=request_body()).status_code == 401


def test_evidence_report_renders_and_states_its_mode(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    response = client.post("/api/v1/traces/report", json=request_body())
    assert response.status_code == 200
    page = response.text

    flat = " ".join(page.split())  # the caveat wraps across source lines
    assert "SYNTHETIC" in page and "NOT LIVE CHAIN DATA" in page
    assert "Northwind Exchange (FICTIONAL)" in page
    assert "allocation_unknown" in page
    assert "not a legal instrument" in flat
    assert "Hop 0 is the seed transfer" in flat
    assert "Label provenance" in page

    # No fabricated probability anywhere in the rendered content. Checked
    # against the body only: the stylesheet legitimately uses percentages.
    body = page.split("</style>", 1)[1]
    assert "%" not in body
    assert "confidence" not in body.lower()


def test_evidence_export_bundle_matches_the_report_and_verifies_its_own_hashes(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    response = client.post("/api/v1/traces/export", json=request_body())
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        assert names == {
            "evidence.json",
            "evidence.html",
            "evidence.pdf",
            "transfers.csv",
            "branch_endings.csv",
            "labels.csv",
            "limitations.csv",
            "manifest.json",
        }

        manifest = json.loads(zf.read("manifest.json"))
        for name, expected_sha256 in manifest["files"].items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == expected_sha256

        # Same trace result and same template as the plain report: the two
        # views must never disagree about what the chain showed. (The two
        # pages are not byte-identical -- each call re-traces and stamps its
        # own "Generated at"/request id -- so the check is on content, not
        # on the page as a whole.)
        bundle_html = zf.read("evidence.html").decode()
        flat_bundle = " ".join(bundle_html.split())
        assert "Northwind Exchange (FICTIONAL)" in bundle_html
        assert "SYNTHETIC" in bundle_html and "NOT LIVE CHAIN DATA" in bundle_html
        assert "not a legal instrument" in flat_bundle
        assert "Hop 0 is the seed transfer" in flat_bundle

        exported_result = json.loads(zf.read("evidence.json"))
        services = [
            b for b in exported_result["branch_endings"] if b["endpoint_class"] == "known_service"
        ]
        assert services and services[0]["label"]["entity_name"] == "Northwind Exchange (FICTIONAL)"

        assert zf.read("evidence.pdf").startswith(b"%PDF")


def draft_request_body(**overrides) -> dict:
    body = request_body()
    body.update(
        request_kind="asset_restriction",
        target_address=SERVICE,
        requesting_agency="State Cyber Cell, Testland",
        requesting_officer="Inspector A. Sharma",
        case_reference="FIR-2026-00042",
        alleged_incident_summary="Victim reports a fraudulent investment scheme.",
    )
    body.update(overrides)
    return body


def test_legal_request_draft_against_the_confirmed_deposit_service_is_drafted(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    """The fixture's SERVICE anchor is address_role=deposit (data/anchors.csv),
    so an asset-restriction draft against it is the happy path, not a refusal."""
    login(client, user_a)
    response = client.post("/api/v1/traces/legal-request-draft", json=draft_request_body())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "drafted"
    assert data["refusal_reason"] is None
    assert data["target"]["address"] == SERVICE
    assert data["target"]["address_role"] == "deposit"
    assert "DRAFT" in data["draft_marker"]
    assert data["checklist_source"]["provider"] == "OKX"


def test_legal_request_draft_report_renders_html(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    response = client.post(
        "/api/v1/traces/legal-request-draft/report", json=draft_request_body()
    )
    assert response.status_code == 200
    flat = " ".join(response.text.split())
    assert "DRAFT" in response.text
    assert "not legal process" in flat
    assert "Northwind Exchange" in response.text


def test_legal_request_draft_requires_a_reached_target_address(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    response = client.post(
        "/api/v1/traces/legal-request-draft",
        json=draft_request_body(target_address="TNeverReachedByThisTrace00000000000"),
    )
    assert response.status_code == 422
    assert "not a branch ending" in response.json()["error"]["message"]


def test_legal_request_draft_requires_non_blank_investigator_fields(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    response = client.post(
        "/api/v1/traces/legal-request-draft",
        json=draft_request_body(requesting_officer="   "),
    )
    assert response.status_code == 422
    assert "requesting_officer" in response.json()["error"]["message"]


def test_legal_request_draft_rejects_an_unknown_request_kind(
    client: TestClient, user_a: User, tron, synthetic_usdt
) -> None:
    login(client, user_a)
    response = client.post(
        "/api/v1/traces/legal-request-draft",
        json=draft_request_body(request_kind="freeze_everything"),
    )
    assert response.status_code == 422


def test_report_escapes_hostile_label_text(
    client: TestClient, user_a: User, tron, synthetic_usdt, tmp_path
) -> None:
    """F02: text from a data file renders inert."""
    from app.reports.evidence import render_evidence_html

    result = {
        "seed": {
            "address": "<script>alert(1)</script>",
            "event_reference": None,
            "network_key": "tron",
            "asset": {"token_contract": None, "display_symbol": "X", "decimals": 6},
        },
        "scope": {
            "data_mode": "SYNTHETIC",
            "analysis_cutoff": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "engine_version": "0.1.0",
            "label_set_version": "0",
            "coverage_status": "partial",
            "case_flow_linkage": "not_established",
        },
        "observed_transfers": [],
        "branch_endings": [],
        "limitations": [],
        "budget_use": {
            "hops_used": 0,
            "hop_limit": 8,
            "events_examined": 0,
            "event_limit": 10,
            "traversal_requests": 0,
            "traversal_request_limit": 10,
            "elapsed_seconds": 0.0,
        },
        "acquisitions": [],
        "disclaimer": "<img src=x onerror=alert(1)>",
    }
    page = render_evidence_html(result)
    body = page.split("</style>", 1)[1]
    # Escaped, therefore inert. The literal characters may still appear as text;
    # what must not appear is a tag the browser would act on.
    assert "<script" not in body
    assert "<img" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body


def test_report_renders_an_older_saved_budget_schema() -> None:
    """A saved trace can predate a budget-field rename. The report must fall
    back to the older provider_* names instead of raising."""

    from app.reports.evidence import render_evidence_html

    result = {
        "seed": {
            "address": "TSeed",
            "event_reference": "tron:tx:0",
            "network_key": "tron",
            "asset": {"token_contract": None, "display_symbol": "USDT", "decimals": 6},
        },
        "scope": {
            "data_mode": "RECORDED_PUBLIC",
            "analysis_cutoff": "2026-08-10T15:59:55+00:00",
            "started_at": "2026-09-20T00:00:00+00:00",
            "finished_at": "2026-09-20T00:00:01+00:00",
            "engine_version": "0.1.0",
            "label_set_version": "0",
            "coverage_status": "complete_within_scope",
            "case_flow_linkage": "established",
        },
        "observed_transfers": [],
        "branch_endings": [],
        "limitations": [],
        "budget_use": {
            "hops_used": 0,
            "hop_limit": 8,
            "events_examined": 0,
            "event_limit": 5000,
            "provider_requests": 3,
            "provider_request_limit": 400,
            "elapsed_seconds": 0.0,
        },
        "acquisitions": [],
        "disclaimer": "not a legal instrument",
    }
    page = render_evidence_html(result)
    assert "3/400 traversal requests" in page
