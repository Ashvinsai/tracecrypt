"""Run one bounded poll of every active watch, then exit (Stage 4, D029).

    # SYNTHETIC or RECORDED_PUBLIC: the source's own declared mode is the mode.
    uv run python ../scripts/poll_watches.py --once \
        --fixture ../fixtures/tron_synthetic_monitoring.json --now 2026-08-01T10:20:00Z

    # LIVE: needs CFA_DATA_MODE=LIVE and CFA_TRON_API_KEY; always the real clock.
    uv run python ../scripts/poll_watches.py --once

One poll per invocation, by design: cron/systemd can schedule it, and a restart
is just the next invocation. This is polling of a provider's indexed history,
not a mempool feed. A LIVE run writes every provider exchange to
``var/monitoring/<capture-id>/raw/`` with a SHA-256 manifest; headers (and so
the API key) are never recorded.

Exit status: 0 when every poll succeeded, 2 when any poll was partial,
truncated, refused, or a provider failure, 1 on a usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.adapters.base import ChainAdapter  # noqa: E402
from app.adapters.fixture import FixtureAdapter  # noqa: E402
from app.adapters.tron import TronGridAdapter  # noqa: E402
from app.core.settings import DataMode, get_settings  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models.casework import Alert, Case, Watch  # noqa: E402
from app.models.chain import Address, Asset, Network  # noqa: E402
from app.models.enums import WatchPollStatus  # noqa: E402
from app.services.alert_notifications import (  # noqa: E402
    build_alert_notification,
    write_notification_outbox,
)
from app.services.live_validation import BundleRecorder  # noqa: E402
from app.services.monitoring import MonitoringError, poll_enabled_watches  # noqa: E402

CAPTURE_ROOT = REPO_ROOT / "var" / "monitoring"


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--now must carry a timezone, e.g. 2026-08-01T10:20:00Z")
    return parsed.astimezone(dt.UTC)


def _write_manifest(directory: Path, poll_json: list[dict[str, Any]], capture_id: str) -> None:
    files = {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    settings = get_settings()
    manifest = {
        "capture_id": capture_id,
        "kind": "monitoring_poll",
        "data_mode": DataMode.LIVE.value,
        "polls": [
            {"poll_run_id": p["poll_run_id"], "watch_id": p["watch_id"], "status": p["status"]}
            for p in poll_json
        ],
        "configuration": {
            "tron_api_base": settings.tron_api_base,
            # Never the key itself, and never a prefix of it.
            "tron_api_key_configured": bool(settings.tron_api_key),
        },
        "files": files,
        "caveat": (
            "A hash establishes that these files have not changed since the poll. "
            "It does not establish that any attribution is correct."
        ),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _new_alert_notifications(db: Any, outcomes: list[Any]) -> list[dict[str, Any]]:
    """Expand only this poll's new alert references into case-scoped packages."""
    notifications: list[dict[str, Any]] = []
    for outcome in outcomes:
        for event_reference in outcome.new_alert_references:
            alert = db.execute(
                select(Alert).where(
                    Alert.watch_id == outcome.watch_id,
                    Alert.event_reference == event_reference,
                )
            ).scalar_one()
            watch = db.get(Watch, alert.watch_id)
            case = db.get(Case, watch.case_id) if watch else None
            network = db.get(Network, watch.network_id) if watch else None
            address = db.get(Address, watch.address_id) if watch else None
            asset = db.get(Asset, watch.asset_id) if watch and watch.asset_id else None
            if not all((watch, case, network, address, asset)):
                raise RuntimeError(
                    f"alert {alert.id} has incomplete case/watch context; "
                    "notification was not written"
                )
            notifications.append(
                build_alert_notification(alert, watch, case, network, address, asset)
            )
    return notifications


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one poll per watch and exit (the only mode; there is no daemon)",
    )
    parser.add_argument("--watch-id", action="append", type=uuid.UUID, default=[])
    parser.add_argument(
        "--fixture", type=Path, help="SYNTHETIC or RECORDED_PUBLIC fixture file to poll"
    )
    parser.add_argument("--now", type=_parse_time, help="injected clock; refused for a LIVE poll")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--no-verify-execution", action="store_true")
    parser.add_argument(
        "--notification-out",
        type=Path,
        help=(
            "write pending local investigator notifications to this directory; "
            "live captures default to <capture>/notifications"
        ),
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    adapter: ChainAdapter
    capture_dir: Path | None = None
    capture: dict[str, Any] | None = None
    if args.fixture is not None:
        if settings.data_mode is DataMode.LIVE:
            print("refusing a fixture poll while CFA_DATA_MODE=LIVE", file=sys.stderr)
            return 1
        fixture = FixtureAdapter(args.fixture)
        adapter, mode = fixture, fixture.data_mode
    else:
        if settings.data_mode is not DataMode.LIVE or not settings.tron_api_key:
            print(
                "no source: pass --fixture, or set CFA_DATA_MODE=LIVE with CFA_TRON_API_KEY "
                "(live monitoring is not configured)",
                file=sys.stderr,
            )
            return 1
        capture_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
        capture_dir = CAPTURE_ROOT / capture_id
        adapter = TronGridAdapter(
            settings.tron_api_base,
            api_key=settings.tron_api_key,
            recorder=BundleRecorder(capture_dir / "raw"),
            max_requests=settings.budget_max_provider_requests,
        )
        mode = DataMode.LIVE
        capture = {"capture_id": capture_id, "directory": str(capture_dir.relative_to(REPO_ROOT))}

    db = SessionLocal()
    notifications: list[dict[str, Any]] = []
    try:
        outcomes = await poll_enabled_watches(
            db,
            adapter,
            observation_mode=mode,
            watch_ids=args.watch_id or None,
            now=args.now,
            max_pages=args.max_pages or settings.monitor_max_pages,
            verify_execution=not args.no_verify_execution,
            secrets=[settings.tron_api_key, settings.secret_key],
            capture=capture,
        )
        notifications = _new_alert_notifications(db, outcomes)
    except MonitoringError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    polls = [o.to_json() for o in outcomes]
    notification_dir = args.notification_out
    if notification_dir is None and capture_dir is not None:
        notification_dir = capture_dir / "notifications"
    notification_manifest = None
    if notification_dir is not None:
        notification_manifest = write_notification_outbox(notification_dir, notifications)
    if capture_dir is not None and capture is not None:
        capture_dir.mkdir(parents=True, exist_ok=True)
        _write_manifest(capture_dir, polls, capture["capture_id"])
    print(
        json.dumps(
            {
                "data_mode": mode.value,
                "observation_method": "polling of indexed provider history; not a mempool feed",
                "watches_polled": len(polls),
                "new_alerts": sum(p["new_alerts"] for p in polls),
                "notifications": (
                    {
                        "directory": str(notification_dir),
                        "pending": notification_manifest["notification_count"],
                    }
                    if notification_manifest is not None
                    else None
                ),
                "polls": polls,
            },
            indent=2,
        )
    )
    if not outcomes:
        print(f"no active {mode.value} watch to poll", file=sys.stderr)
    return 0 if all(o.status is WatchPollStatus.succeeded for o in outcomes) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
