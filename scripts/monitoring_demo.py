"""Offline monitoring demonstration: one new event, one alert, no duplicates (D029).

SYNTHETIC only, no network, no key. Uses its own scratch database under
``var/monitoring-demo/`` (recreated each run) and the fixture
``fixtures/tron_synthetic_monitoring.json``, with an injected clock:

  1. poll at 10:10 -> E1 is new             -> 1 new alert
  2. poll at 10:20 -> E1 repeated, E2 new   -> 1 new alert (approval excluded)
  3. same poll again, same process          -> 0 new alerts
  4. same poll again from a new process     -> 0 new alerts (restart)

Step 4 runs ``scripts/poll_watches.py --once`` as a separate process against the
same database file, so the only thing it shares with steps 1-3 is what was
committed.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO_ROOT / "var" / "monitoring-demo"
DEMO_DB = DEMO_DIR / "demo.db"
FIXTURE = REPO_ROOT / "fixtures" / "tron_synthetic_monitoring.json"

# The engine is created at import time, so the scratch database must be chosen first.
os.environ["CFA_DATABASE_URL"] = f"sqlite+pysqlite:///{DEMO_DB}"
os.environ.setdefault("CFA_DATA_MODE", "SYNTHETIC")
sys.path.insert(0, str(REPO_ROOT / "api"))

from sqlalchemy import func, select  # noqa: E402

from app.adapters.fixture import FixtureAdapter  # noqa: E402
from app.core.settings import DataMode, get_settings  # noqa: E402
from app.db.base import Base, SessionLocal, engine  # noqa: E402
from app.models.casework import Alert, Case, Watch  # noqa: E402
from app.models.chain import Asset, Network  # noqa: E402
from app.models.enums import AssetKind, NetworkFamily  # noqa: E402
from app.models.identity import Organization  # noqa: E402
from app.services.monitoring import create_watch, poll_watch  # noqa: E402

T0 = dt.datetime(2026, 8, 1, 10, 0, tzinfo=dt.UTC)
WATCHED = "TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz"
CONTRACT = "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY"


def _seed() -> None:
    with SessionLocal() as db:
        network = Network(
            key="tron",
            display_name="TRON (synthetic demo)",
            family=NetworkFamily.account,
            native_asset_symbol="TRX",
            is_supported=True,
        )
        db.add(network)
        db.flush()
        db.add(
            Asset(
                network_id=network.id,
                kind=AssetKind.token,
                token_contract=CONTRACT,
                decimals=6,
                display_symbol="USDT-SYN",
                issuer_reference="synthetic fixture; not a real issuer reference",
                is_supported=True,
                data_mode=DataMode.SYNTHETIC,
            )
        )
        org = Organization(name="Demo Cyber Cell (fictional)", slug="demo-monitoring")
        db.add(org)
        db.flush()
        case = Case(
            organization_id=org.id,
            case_reference="DEMO-MONITOR-1",
            title="Synthetic monitoring demonstration",
            data_mode=DataMode.SYNTHETIC,
        )
        db.add(case)
        db.flush()
        create_watch(
            db,
            case=case,
            network_key="tron",
            address=WATCHED,
            token_contract=CONTRACT,
            data_mode=DataMode.SYNTHETIC,
            analysis_start=T0,
            overlap_seconds=600,
            now=T0,
        )
        db.commit()


async def _in_process_poll(minutes: int) -> dict:
    with SessionLocal() as db:
        watch = db.execute(select(Watch)).scalar_one()
        outcome = await poll_watch(
            db,
            watch,
            FixtureAdapter(FIXTURE),
            observation_mode=DataMode.SYNTHETIC,
            now=T0 + dt.timedelta(minutes=minutes),
        )
        return outcome.to_json()


def _restart_poll(minutes: int) -> dict:
    now = (T0 + dt.timedelta(minutes=minutes)).isoformat()
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "poll_watches.py"),
            "--once",
            "--fixture",
            str(FIXTURE),
            "--now",
            now,
        ],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"restart poll failed ({completed.returncode}): {completed.stderr}")
    return json.loads(completed.stdout)["polls"][0]


def _alert_count() -> int:
    with SessionLocal() as db:
        return db.execute(select(func.count()).select_from(Alert)).scalar_one()


async def main() -> int:
    if get_settings().data_mode is DataMode.LIVE:
        print("this demo is SYNTHETIC only; CFA_DATA_MODE=LIVE is refused", file=sys.stderr)
        return 1
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    if DEMO_DB.exists():
        DEMO_DB.unlink()
    Base.metadata.create_all(engine)
    _seed()

    steps = [
        ("poll at 10:10", await _in_process_poll(10)),
        ("poll at 10:20", await _in_process_poll(20)),
        ("same poll again, same process", await _in_process_poll(20)),
    ]
    engine.dispose()
    steps.append(("same poll again, new process (restart)", _restart_poll(20)))

    total = _alert_count()
    print("MODE: SYNTHETIC -- fictional fixture data, injected clock, not a live observation.")
    print("Polling of indexed history; not a mempool feed.\n")
    for label, poll in steps:
        print(
            f"{label:<40} status={poll['status']:<10} new_alerts={poll['new_alerts']} "
            f"duplicates={poll['duplicate_events']} excluded={poll['excluded']} "
            f"new={poll['new_alert_references']}"
        )
    print(f"\ntotal alerts in the database: {total}")

    summary = {
        "data_mode": "SYNTHETIC",
        "note": "Fictional fixture data and an injected clock; not a live observation.",
        "observation_method": "polling of indexed provider history; not a mempool feed",
        "fixture": str(FIXTURE.relative_to(REPO_ROOT)),
        "steps": [{"step": label, **poll} for label, poll in steps],
        "total_alerts": total,
    }
    (DEMO_DIR / "summary.json").write_text(json.dumps(summary, indent=2))

    expected = [1, 1, 0, 0]
    actual = [poll["new_alerts"] for _, poll in steps]
    if actual != expected or total != 2:
        print(f"UNEXPECTED: new alerts per step {actual}, total {total}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
