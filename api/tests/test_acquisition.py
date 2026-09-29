"""A14 / C04: a provider failure is a failure, never an empty history (T3)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from app.adapters.base import AssetRef, Direction, ProviderError, ProviderErrorClass
from app.adapters.fixture import FixtureAdapter
from app.core.settings import DataMode
from app.models.chain import Acquisition
from app.models.enums import AcquisitionStatus, CoverageStatus
from tests.conftest import FIXTURE_FILE

FAILING_ADDRESS = "TRhdfnc7u5pXTZmm2vWnjQu8C7sYgZ2U9P"
SUPPORTED_ASSET = AssetRef("tron", "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY", 6, "USDT-SYN")


async def test_failure_is_not_empty_history(db: Session) -> None:
    """A14: the adapter raises, and the stored acquisition says 'failed'."""
    adapter = FixtureAdapter(FIXTURE_FILE)
    with pytest.raises(ProviderError) as caught:
        await adapter.fetch_transfers(
            address=FAILING_ADDRESS,
            asset=SUPPORTED_ASSET,
            direction=Direction.outgoing,
            analysis_cutoff=dt.datetime.now(dt.UTC),
        )
    assert caught.value.error_class is ProviderErrorClass.quota

    record = Acquisition(
        source="fixture",
        provider="fixture:tron_synthetic_case_alpha.json",
        endpoint="fixture://tron/transfers",
        request_params_hash="deadbeef",
        requested_at=dt.datetime.now(dt.UTC),
        status=AcquisitionStatus.failed,
        coverage_status=CoverageStatus.failed,
        error_class=caught.value.error_class.value,
        analysis_cutoff=dt.datetime.now(dt.UTC),
        parser_version="fixture-0.1.0",
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(record)
    db.flush()
    db.expire(record)

    stored = db.get(Acquisition, record.id)
    assert stored is not None
    assert stored.status is AcquisitionStatus.failed
    assert stored.coverage_status is CoverageStatus.failed
    assert stored.coverage_status is not CoverageStatus.complete_within_scope


async def test_successful_page_records_coverage_and_provenance() -> None:
    adapter = FixtureAdapter(FIXTURE_FILE, page_size=3)
    page = await adapter.fetch_transfers(
        address="TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
        asset=SUPPORTED_ASSET,
        direction=Direction.outgoing,
        analysis_cutoff=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
    )
    assert page.acquisition is not None
    assert page.acquisition.status is AcquisitionStatus.succeeded
    assert page.acquisition.data_mode is DataMode.SYNTHETIC
    assert page.acquisition.request_params_hash
    assert page.events


async def test_pagination_does_not_duplicate_events() -> None:
    """C01 in spirit: walking every page yields each event exactly once."""
    adapter = FixtureAdapter(FIXTURE_FILE, page_size=2)
    seen: list[str] = []
    cursor = None
    for _ in range(50):
        page = await adapter.fetch_transfers(
            address="TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
            asset=SUPPORTED_ASSET,
            direction=Direction.outgoing,
            analysis_cutoff=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
            cursor=cursor,
            limit=2,
        )
        seen.extend(e.event_reference for e in page.events)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen))


async def test_analysis_cutoff_bounds_the_range() -> None:
    """C05: nothing after the declared cutoff is returned."""
    adapter = FixtureAdapter(FIXTURE_FILE)
    early = await adapter.fetch_transfers(
        address="TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
        asset=SUPPORTED_ASSET,
        direction=Direction.outgoing,
        analysis_cutoff=dt.datetime(2026, 8, 1, 10, 12, tzinfo=dt.UTC),
    )
    late = await adapter.fetch_transfers(
        address="TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
        asset=SUPPORTED_ASSET,
        direction=Direction.outgoing,
        analysis_cutoff=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
    )
    assert len(early.events) < len(late.events)
    assert all(
        e.block_time is None or e.block_time <= dt.datetime(2026, 8, 1, 10, 12, tzinfo=dt.UTC)
        for e in early.events
    )
