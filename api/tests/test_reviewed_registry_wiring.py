"""The reviewed label sets, reached through the application's own entry points.

`test_candidate_review.py` proves a decision changes what the registry returns.
That is not the same claim as "the investigator's request changes", because the
API could be reading a different registry entirely — which it was until D019.
So these tests go through `POST /trace`, with the same fixture adapter the
Stage 1 slice uses, and assert on what the investigator receives.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.settings import AppEnv, DataMode, LabelSource, Settings, get_settings
from app.main import app as fastapi_app
from app.models.identity import User
from app.services.anchor_import import Destination, DisclosureKind, SourceDocument, import_anchors
from app.services.candidate_review import ReviewAction, ReviewRequest, review_candidates
from app.services.trace_service import TraceUnavailable, load_labels
from tests.conftest import login

VICTIM = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
SERVICE = "TBvGC1Nd8i5wmj185HTdoTWAZPmRUTFBZz"
CANDIDATE = "TC5LeXwG3r6shFz9KjnJpyaddvg2acWYNK"
CONTRACT = "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY"
SEED_EVENT = "tron:tx_seed_multi:0"

DISCLOSED = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
RETRIEVED = dt.datetime(2026, 9, 20, tzinfo=dt.UTC)
SOURCE_URL = "https://example-exchange.test/proof-of-reserves"

COLUMNS = "network,address,entity_name,entity_type,assertion_type,address_role\n"


def import_claim(
    tmp_path: Path,
    data_dir: Path,
    *,
    address: str = SERVICE,
    network: str = "tron",
    entity: str = "Example Exchange",
    assertion: str = "service_control",
    role: str = "cold_reserve",
    kind: DisclosureKind = DisclosureKind.signed_address_verification,
    url: str = SOURCE_URL,
    name: str = "disclosure.csv",
) -> None:
    source = tmp_path / name
    source.write_text(COLUMNS + f"{network},{address},{entity},exchange,{assertion},{role}\n")
    aggregated = kind is DisclosureKind.aggregator_tagpack
    import_anchors(
        SourceDocument(
            path=source,
            url=url,
            upstream_source="https://example-exchange.test/original" if aggregated else None,
            reuse_terms="CC-BY-4.0" if aggregated else None,
            disclosure_kind=kind,
            disclosure_date=DISCLOSED,
            retrieved_at=RETRIEVED,
            methodology="Opened the signed verification page and read the TRON entry.",
            label_set_version="wiring-test-1",
        ),
        network_key=network,
        out_dir=data_dir,
        write=True,
    )


def accept(data_dir: Path, address: str = SERVICE, *, url: str = SOURCE_URL) -> None:
    report = review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key="tron",
                address=address,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="Opened the disclosure; the address is listed and dated.",
                evidence_inspected=(url,),
                decided_at=dt.datetime(2026, 9, 21, tzinfo=dt.UTC),
            )
        ],
        write=True,
    )
    assert not report.refusals, report.refusals


def reviewed_settings(data_dir: Path) -> Settings:
    """Synthetic observations, reviewed labels: the wiring under test, offline."""
    return Settings(
        app_env=AppEnv.test,
        data_mode=DataMode.SYNTHETIC,
        secret_key="test-secret-key-that-is-long-enough-for-the-validator",
        label_source=LabelSource.reviewed_sets,
        label_dir=str(data_dir),
    )


@pytest.fixture
def reviewed_client(client: TestClient, tmp_path: Path):
    """The app, serving traces from a reviewed label directory under tmp_path."""
    data_dir = tmp_path / "data"
    settings = reviewed_settings(data_dir)
    fastapi_app.dependency_overrides[get_settings] = lambda: settings
    yield client, tmp_path, data_dir
    fastapi_app.dependency_overrides.pop(get_settings, None)


def trace(client: TestClient, **overrides) -> dict:
    body = {
        "network_key": "tron",
        "address": VICTIM,
        "token_contract": CONTRACT,
        "seed_event_reference": SEED_EVENT,
        "mode": "incident",
        "analysis_cutoff": "2027-01-01T00:00:00Z",
    }
    body.update(overrides)
    response = client.post("/api/v1/traces", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def services(data: dict) -> list[dict]:
    return [b for b in data["branch_endings"] if b["endpoint_class"] == "known_service"]


def test_an_unreviewed_claim_does_not_become_a_supported_service(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(tmp_path, data_dir)

    data = trace(client)

    assert not services(data), "an imported, unreviewed claim must not attribute a service"
    assert data["scope"]["label_snapshot"]["source"] == "reviewed_sets"
    assert data["scope"]["label_snapshot"]["accepted_service_claims"] == 0


def test_accepting_the_claim_changes_what_the_same_request_returns(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(tmp_path, data_dir)
    assert not services(trace(client))

    accept(data_dir)
    data = trace(client)

    (service,) = services(data)
    assert service["address"] == SERVICE
    label = service["label"]
    assert label["entity_name"] == "Example Exchange"
    assert label["source_reference"] == SOURCE_URL
    assert label["reviewed_by"] == "investigator-1"
    assert len(label["source_hash"]) == 64
    assert label["review_reference"].startswith(label["source_hash"][:16])
    assert label["label_source"] == "reviewed_sets"


def test_a_claim_withdrawn_by_review_is_not_used_by_a_new_trace(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(tmp_path, data_dir)
    accept(data_dir)
    assert services(trace(client))

    review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key="tron",
                address=SERVICE,
                action=ReviewAction.quarantine,
                reviewer="investigator-2",
                rationale="The publisher withdrew the disclosure.",
            )
        ],
        write=True,
    )

    data = trace(client)
    assert not services(data)
    (file_snapshot,) = [
        f for f in data["scope"]["label_snapshot"]["files"] if f["name"] == "verified_anchors.csv"
    ]
    assert file_snapshot["rows_withdrawn"] == 1


def test_an_expired_claim_is_not_used_although_it_is_accepted(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(tmp_path, data_dir)
    accept(data_dir)

    path = data_dir / "verified_anchors.csv"
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0])
    for row in rows:
        if row["address"] == SERVICE:
            # The disclosure stopped applying before the observed transfer.
            row["valid_to"] = "2026-02-01T00:00:00Z"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    assert not services(trace(client))


def test_a_saved_report_keeps_the_evidence_it_used(
    reviewed_client, user_a: User, tron, synthetic_usdt, tmp_path: Path
) -> None:
    """A reopened report must not depend on what the CSV says later."""
    client, sources_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(sources_path, data_dir)
    accept(data_dir)

    saved = trace(client)
    report = client.post(
        "/api/v1/traces/report",
        json={
            "network_key": "tron",
            "address": VICTIM,
            "token_contract": CONTRACT,
            "seed_event_reference": SEED_EVENT,
            "mode": "incident",
            "analysis_cutoff": "2027-01-01T00:00:00Z",
        },
    )
    assert report.status_code == 200
    saved_html = report.text
    saved_json = json.dumps(saved)

    # The label set changes afterwards; the saved artefacts must not.
    (data_dir / "verified_anchors.csv").unlink()

    assert "Example Exchange" in saved_html
    assert "investigator-1" in saved_html
    assert services(saved)[0]["label"]["source_hash"] in saved_html
    assert "Example Exchange" in saved_json
    # And a fresh request now genuinely has nothing to attribute.
    assert not services(trace(client))


def test_a_deposit_candidate_cannot_become_a_supported_terminal(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(
        tmp_path,
        data_dir,
        address=CANDIDATE,
        assertion="deposit_candidate",
        role="deposit",
        kind=DisclosureKind.authorized_observation,
        url="local: forwarding behaviour in the recorded window",
        name="candidate.csv",
    )
    accept(data_dir, CANDIDATE, url="local: forwarding behaviour in the recorded window")

    data = trace(client)

    assert not services(data)
    candidates = [b for b in data["branch_endings"] if b["endpoint_class"] == "deposit_candidate"]
    assert candidates and candidates[0]["address"] == CANDIDATE
    assert candidates[0]["attribution_status"] == "candidate"


def test_a_conflicted_claim_does_not_terminate_a_branch(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(tmp_path, data_dir)
    import_claim(
        tmp_path,
        data_dir,
        entity="Rival Custody",
        url="https://rival.test/reserves",
        name="rival.csv",
    )
    report = review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key="tron",
                address=SERVICE,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="Preferring the signed verification over the rival page.",
                evidence_inspected=(SOURCE_URL,),
                source_reference=SOURCE_URL,
                conflict_acknowledged=True,
            )
        ],
        write=True,
    )
    assert not report.refusals

    data = trace(client)

    # The accepted one attributes; the conflicted one is not loaded at all.
    (service,) = services(data)
    assert service["label"]["entity_name"] == "Example Exchange"
    labels_seen = {b["label"]["entity_name"] for b in data["branch_endings"] if b.get("label")}
    assert "Rival Custody" not in labels_seen


def test_a_claim_on_another_network_is_not_used(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(
        tmp_path,
        data_dir,
        network="ethereum",
        address=SERVICE,
        name="ethereum.csv",
        url="https://example-exchange.test/eth",
    )
    review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key="ethereum",
                address=SERVICE,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="Accepted for Ethereum only.",
                evidence_inspected=("https://example-exchange.test/eth",),
            )
        ],
        write=True,
    )

    assert not services(trace(client))


def test_the_api_and_the_cli_read_the_same_registry(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(tmp_path, data_dir)
    accept(data_dir)

    from_api = trace(client)["scope"]["label_snapshot"]
    # The same call the CLI makes, through the same provider.
    from_cli = load_labels(reviewed_settings(data_dir)).snapshot()

    assert from_api == from_cli
    assert from_api["source"] == "reviewed_sets"


def test_live_mode_refuses_an_empty_reviewed_set_rather_than_falling_back(
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env=AppEnv.test,
        data_mode=DataMode.LIVE,
        secret_key="test-secret-key-that-is-long-enough-for-the-validator",
        label_dir=str(tmp_path / "empty"),
        tron_api_key="not-a-real-key",
    )

    with pytest.raises(TraceUnavailable, match="no accepted service claim"):
        load_labels(settings)


def test_live_mode_cannot_be_configured_to_read_the_synthetic_set() -> None:
    with pytest.raises(ValueError, match="fictional label set"):
        Settings(
            app_env=AppEnv.test,
            data_mode=DataMode.LIVE,
            secret_key="test-secret-key-that-is-long-enough-for-the-validator",
            label_source=LabelSource.synthetic_fixture,
        )


def test_synthetic_mode_still_reads_the_fixture_set_by_default(
    client: TestClient, user_a: User, tron, synthetic_usdt, db: Session
) -> None:
    """The demo path is unchanged, and says which set it used."""
    login(client, user_a)

    data = trace(client)

    assert data["scope"]["label_snapshot"]["source"] == "synthetic_fixture"
    (service,) = services(data)
    assert service["label"]["entity_name"] == "Northwind Exchange (FICTIONAL)"
    assert service["label"]["reviewed_by"] is None


def test_the_review_sets_are_never_read_from_independent_review(
    reviewed_client, user_a: User, tron, synthetic_usdt
) -> None:
    """A lead is material for a human, not a label for a tracer."""
    client, tmp_path, data_dir = reviewed_client
    login(client, user_a)
    import_claim(
        tmp_path,
        data_dir,
        kind=DisclosureKind.aggregator_tagpack,
        url="https://aggregator.test/tags",
        name="aggregated.csv",
    )
    assert (data_dir / f"{Destination.independent_review.value}.csv").is_file()
    review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key="tron",
                address=SERVICE,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="Accepted as a lead worth following.",
                evidence_inspected=("https://aggregator.test/tags",),
            )
        ],
        write=True,
    )

    data = trace(client)

    assert not services(data)
    assert [f["name"] for f in data["scope"]["label_snapshot"]["files"]] == []
