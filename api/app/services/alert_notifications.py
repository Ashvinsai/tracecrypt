"""Local-only investigator notification packages for persisted monitor alerts.

This module deliberately stops at a durable evidence outbox. It does not send
email, call a webhook, publish to a queue, or contact an agency. A later
delivery worker can consume the explicit ``LOCAL_EVIDENCE_OUTBOX`` contract
after authentication, retry, acknowledgement, and agency-specific controls
are approved.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.models.casework import Alert, Case, Watch
from app.models.chain import Address, Asset, Network
from app.services.monitoring import LIMITATIONS, alert_to_json

NOTIFICATION_FORMAT_VERSION = "1"
CHANNEL = "LOCAL_EVIDENCE_OUTBOX"
_CAVEAT = (
    "This is a pending local investigator notification derived from an observed "
    "alert. It is not a fraud finding, ownership claim, freeze instruction, or "
    "external delivery acknowledgement."
)


def build_alert_notification(
    alert: Alert,
    watch: Watch,
    case: Case,
    network: Network,
    address: Address,
    asset: Asset,
) -> dict[str, Any]:
    """Build one complete, case-scoped notification from stored alert facts."""
    evidence = dict(alert.evidence or {})
    return {
        "notification_format_version": NOTIFICATION_FORMAT_VERSION,
        "notification_type": "investigator_alert",
        "delivery": {
            "channel": CHANNEL,
            "status": "pending",
            "external_send": False,
        },
        "case": {
            "id": str(case.id),
            "case_reference": case.case_reference,
            "title": case.title,
        },
        "watch": {
            "id": str(watch.id),
            "network": network.key,
            "address": address.canonical_address,
            "token_contract": asset.token_contract,
            "display_symbol": asset.display_symbol,
            "data_mode": watch.data_mode.value,
        },
        "alert": alert_to_json(alert),
        "evidence_package": {
            "event_reference": alert.event_reference,
            "event": evidence.get("event"),
            "acquisition": evidence.get("acquisition"),
            "execution_status": alert.execution_status.value,
            "confirmation_state": alert.confirmation_state.value,
            "limitations": evidence.get("limitations", list(LIMITATIONS)),
            "state_history": evidence.get("state_history", []),
        },
        "caveat": _CAVEAT,
    }


def write_notification_outbox(
    directory: Path, notifications: list[dict[str, Any]]
) -> dict[str, Any]:
    """Write pending notifications and a checksum manifest to a local directory."""
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for notification in notifications:
        alert_id = str(notification["alert"]["id"])
        filename = f"alert-{alert_id}.json"
        path = directory / filename
        path.write_text(json.dumps(notification, indent=2, sort_keys=True) + "\n")
        files[filename] = hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "notification_format_version": NOTIFICATION_FORMAT_VERSION,
        "channel": CHANNEL,
        "notification_count": len(notifications),
        "files": files,
        "caveat": _CAVEAT,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
