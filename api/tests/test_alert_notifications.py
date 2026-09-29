"""Local investigator-notification outbox tests."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

from app.core.settings import DataMode
from app.models.casework import Alert, Case, Watch
from app.models.chain import Address, Asset, Network
from app.models.enums import (
    AlertState,
    AssetKind,
    ConfirmationState,
    ExecutionStatus,
    NetworkFamily,
)
from app.services.alert_notifications import (
    build_alert_notification,
    write_notification_outbox,
)


def test_local_notification_contains_case_context_and_integrity_manifest(
    tmp_path: Path,
) -> None:
    now = dt.datetime(2026, 9, 26, tzinfo=dt.UTC)
    organization_id = uuid.uuid4()
    case_id = uuid.uuid4()
    watch_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    network_id = uuid.uuid4()
    address_id = uuid.uuid4()
    asset_id = uuid.uuid4()

    case = Case(
        id=case_id,
        organization_id=organization_id,
        case_reference="CASE-001",
        title="Synthetic investigator notification",
        data_mode=DataMode.SYNTHETIC,
    )
    network = Network(
        id=network_id,
        key="tron",
        display_name="TRON",
        family=NetworkFamily.account,
        native_asset_symbol="TRX",
        is_supported=True,
    )
    address = Address(
        id=address_id,
        network_id=network_id,
        canonical_address="TWatchedAddress",
        original_input="TWatchedAddress",
        address_format="tron_base58",
        data_mode=DataMode.SYNTHETIC,
    )
    asset = Asset(
        id=asset_id,
        network_id=network_id,
        kind=AssetKind.token,
        token_contract="TTokenContract",
        decimals=6,
        display_symbol="USDT",
        is_supported=True,
        data_mode=DataMode.SYNTHETIC,
    )
    watch = Watch(
        id=watch_id,
        case_id=case_id,
        network_id=network_id,
        address_id=address_id,
        asset_id=asset_id,
        data_mode=DataMode.SYNTHETIC,
        created_at=now,
    )
    alert = Alert(
        id=alert_id,
        watch_id=watch_id,
        rule_key="new_supported_token_transfer",
        rule_version="1",
        dedupe_key="new_supported_token_transfer:tron:TX1:0",
        event_reference="tron:TX1:0",
        data_mode=DataMode.SYNTHETIC,
        state=AlertState.active,
        execution_status=ExecutionStatus.success,
        confirmation_state=ConfirmationState.confirmed,
        block_time=now,
        first_observed_at=now,
        evidence={
            "event": {"tx_hash": "TX1", "amount_base_units": "100"},
            "limitations": ["not a fraud finding"],
        },
    )

    notification = build_alert_notification(alert, watch, case, network, address, asset)

    assert notification["notification_type"] == "investigator_alert"
    assert notification["delivery"] == {
        "channel": "LOCAL_EVIDENCE_OUTBOX",
        "status": "pending",
        "external_send": False,
    }
    assert notification["case"]["case_reference"] == "CASE-001"
    assert notification["watch"]["address"] == "TWatchedAddress"
    assert notification["alert"]["event_reference"] == "tron:TX1:0"

    manifest = write_notification_outbox(tmp_path / "outbox", [notification])
    path = tmp_path / "outbox" / f"alert-{alert_id}.json"
    assert path.is_file()
    assert manifest["notification_count"] == 1
    assert manifest["files"][path.name] == __import__("hashlib").sha256(
        path.read_bytes()
    ).hexdigest()
    assert json.loads(path.read_text())["delivery"]["external_send"] is False
