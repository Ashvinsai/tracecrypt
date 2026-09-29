"""A16, A17, C03: synthetic data stays synthetic (D009, T13, T4)."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy.orm import Session

from app.adapters.base import AssetRef, Direction, ProviderError, ProviderErrorClass
from app.adapters.fixture import FixtureAdapter
from app.core.settings import DataMode
from app.models.chain import Asset
from app.models.enums import AssetKind
from app.services.fixtures import FixtureLoadError, load_fixture_into_db
from tests.conftest import FIXTURE_FILE

REAL_CONTRACT = "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY"
SPOOF_CONTRACT = "TUJmRrUmPrJZgqhRGjGKwbAzqZx3EHpoW2"


def test_fixture_loader_refuses_live(db: Session, tron) -> None:
    """A16: the loader will not write fixture rows under a LIVE data mode."""
    with pytest.raises(FixtureLoadError, match="LIVE"):
        load_fixture_into_db(db, FIXTURE_FILE, network=tron, data_mode=DataMode.LIVE)


def test_fixture_adapter_refuses_live_mode() -> None:
    """A17: the adapter refuses to serve a process that declares itself live."""
    adapter = FixtureAdapter(FIXTURE_FILE)
    with pytest.raises(ProviderError) as caught:
        adapter.assert_mode_allowed(DataMode.LIVE)
    assert caught.value.error_class is ProviderErrorClass.unsupported


def test_fixture_declaring_live_is_rejected(tmp_path) -> None:
    """A fixture file cannot promote itself to live by editing one field."""
    doc = json.loads(FIXTURE_FILE.read_text())
    doc["data_mode"] = "LIVE"
    path = tmp_path / "dishonest.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ProviderError, match="never live"):
        FixtureAdapter(path)


def test_recorded_fixture_requires_capture_time(tmp_path) -> None:
    """Replay must identify its capture time; it cannot masquerade as live."""
    doc = json.loads(FIXTURE_FILE.read_text())
    doc["data_mode"] = "RECORDED_PUBLIC"
    doc.pop("capture_time", None)
    path = tmp_path / "undated.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ProviderError, match="capture_time"):
        FixtureAdapter(path)


async def test_spoofed_token_contract_is_distinct_asset(db: Session, tron) -> None:
    """C03/T4: a contract wearing the same ticker is a different asset (D003)."""
    for contract in (REAL_CONTRACT, SPOOF_CONTRACT):
        db.add(
            Asset(
                network_id=tron.id,
                kind=AssetKind.token,
                token_contract=contract,
                decimals=6,
                display_symbol="USDT-SYN",
                is_supported=contract == REAL_CONTRACT,
                data_mode=DataMode.SYNTHETIC,
            )
        )
    db.flush()

    adapter = FixtureAdapter(FIXTURE_FILE)
    supported = await adapter.fetch_transfers(
        address="TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
        asset=AssetRef("tron", REAL_CONTRACT, 6, "USDT-SYN"),
        direction=Direction.outgoing,
        analysis_cutoff=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
    )
    spoofed = await adapter.fetch_transfers(
        address="TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
        asset=AssetRef("tron", SPOOF_CONTRACT, 6, "USDT-SYN"),
        direction=Direction.outgoing,
        analysis_cutoff=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
    )

    supported_refs = {e.event_reference for e in supported.events}
    spoof_refs = {e.event_reference for e in spoofed.events}
    assert supported_refs and spoof_refs
    assert supported_refs.isdisjoint(spoof_refs)
    # The million-unit spoof transfer never appears under the supported asset.
    assert "tron:tx_spoof:0" in spoof_refs
    assert "tron:tx_spoof:0" not in supported_refs


def test_loaded_fixture_rows_are_marked_synthetic(db: Session, tron) -> None:
    """T13: every row the loader writes declares itself synthetic."""
    result = load_fixture_into_db(db, FIXTURE_FILE, network=tron, data_mode=DataMode.SYNTHETIC)
    assert result.events_loaded > 0
    for asset in db.query(Asset).all():
        assert asset.data_mode is DataMode.SYNTHETIC
