"""Fixture adapter: a real ``ChainAdapter`` reading recorded JSON (D007).

Serves SYNTHETIC and RECORDED_PUBLIC only. It refuses to run when the process
declares LIVE, so a demo can never be mistaken for a live trace (D009).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from app.adapters.base import (
    AcquisitionRecord,
    AssetRef,
    ChainAdapter,
    Direction,
    NormalizedTransfer,
    ProviderError,
    ProviderErrorClass,
    TransferPage,
)
from app.core.settings import DataMode
from app.models.enums import (
    AcquisitionStatus,
    ConfirmationState,
    CoverageStatus,
    EventKind,
    ExecutionStatus,
)
from app.services.addresses import CanonicalAddress, canonicalize

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"


def _parse_time(value: str | None) -> dt.datetime | None:
    if value is None:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


class FixtureAdapter(ChainAdapter):
    supported_data_modes = frozenset({DataMode.SYNTHETIC, DataMode.RECORDED_PUBLIC})

    def __init__(
        self,
        fixture_path: Path | str,
        *,
        network_key: str = "tron",
        page_size: int = 50,
    ) -> None:
        self.network_key = network_key
        self.page_size = page_size
        self._path = Path(fixture_path)
        with self._path.open() as fh:
            self._doc: dict[str, Any] = json.load(fh)

        declared = DataMode(self._doc.get("data_mode", DataMode.SYNTHETIC.value))
        if declared is DataMode.LIVE:
            raise ProviderError(
                ProviderErrorClass.unsupported,
                f"fixture {self._path.name} declares data_mode=LIVE; fixtures are never live",
            )
        self.data_mode = declared
        self.capture_time = _parse_time(self._doc.get("capture_time"))
        if self.data_mode is DataMode.RECORDED_PUBLIC and self.capture_time is None:
            raise ProviderError(
                ProviderErrorClass.parse_error,
                "RECORDED_PUBLIC fixtures must declare capture_time",
            )
        #: Injected provider failures, keyed by address, for T3 regression tests.
        self._failures: dict[str, str] = self._doc.get("provider_failures", {})
        self._events: list[dict[str, Any]] = self._doc.get("events", [])

    def validate_address(self, value: str) -> CanonicalAddress:
        return canonicalize(self.network_key, value)

    def _to_normalized(self, raw: dict[str, Any]) -> NormalizedTransfer:
        asset = AssetRef(
            network_key=self.network_key,
            token_contract=raw["asset"].get("token_contract"),
            decimals=raw["asset"]["decimals"],
            display_symbol=raw["asset"]["display_symbol"],
        )
        ordering_ambiguous = bool(raw.get("ordering_ambiguous", False))
        event_index = raw.get("event_index")
        if event_index is None and not ordering_ambiguous:
            # The source gave us no index and did not admit ambiguity. We do not
            # invent one; we record the ambiguity instead (D005).
            ordering_ambiguous = True
        return NormalizedTransfer(
            event_reference=raw["event_reference"],
            tx_hash=raw["tx_hash"],
            event_kind=EventKind(raw.get("event_kind", EventKind.transfer.value)),
            asset=asset,
            from_address=raw.get("from_address"),
            to_address=raw.get("to_address"),
            amount_base_units=int(raw["amount_base_units"]),
            execution_status=ExecutionStatus(raw.get("execution_status", "success")),
            confirmation_state=ConfirmationState(raw.get("confirmation_state", "confirmed")),
            block_height=raw.get("block_height"),
            block_hash=raw.get("block_hash"),
            parent_block_hash=raw.get("parent_block_hash"),
            block_time=_parse_time(raw.get("block_time")),
            index_in_block=raw.get("index_in_block"),
            event_index=event_index,
            ordering_ambiguous=ordering_ambiguous,
        )

    async def fetch_transfers(
        self,
        *,
        address: str,
        asset: AssetRef,
        direction: Direction,
        analysis_cutoff: dt.datetime,
        analysis_start: dt.datetime | None = None,
        cursor: str | None = None,
        limit: int = 200,
        enrich: bool | None = None,  # noqa: ARG002 -- fixture data is already fully resolved
    ) -> TransferPage:
        canonical = self.validate_address(address).canonical
        requested_at = dt.datetime.now(dt.UTC)
        params = json.dumps(
            {
                "address": canonical,
                "contract": asset.token_contract,
                "direction": direction.value,
                "cursor": cursor,
                "limit": limit,
                "cutoff": analysis_cutoff.isoformat(),
                "start": analysis_start.isoformat() if analysis_start else None,
            },
            sort_keys=True,
        )
        params_hash = hashlib.sha256(params.encode()).hexdigest()[:32]

        if canonical in self._failures:
            # A failure is recorded as a failure. It never becomes "no activity" (T3).
            raise ProviderError(ProviderErrorClass(self._failures[canonical]), canonical)

        selected = [
            raw
            for raw in self._events
            if raw["asset"].get("token_contract") == asset.token_contract
            and self._matches(raw, canonical, direction)
            and self._within_cutoff(raw, analysis_cutoff)
            and self._at_or_after_start(raw, analysis_start)
        ]
        selected.sort(
            key=lambda r: (
                r.get("block_height") or 0,
                r.get("index_in_block") or 0,
                r.get("event_index") or 0,
            )
        )

        start = int(cursor) if cursor else 0
        page_size = min(limit, self.page_size)
        window = selected[start : start + page_size]
        next_cursor = str(start + page_size) if start + page_size < len(selected) else None

        events = [self._to_normalized(raw) for raw in window]
        acquisition = AcquisitionRecord(
            provider=f"fixture:{self._path.name}",
            endpoint=f"fixture://{self.network_key}/transfers",
            requested_at=requested_at,
            observed_at=dt.datetime.now(dt.UTC),
            status=AcquisitionStatus.succeeded,
            coverage_status=(
                CoverageStatus.partial if next_cursor else CoverageStatus.complete_within_scope
            ),
            data_mode=self.data_mode,
            analysis_cutoff=analysis_cutoff,
            parser_version="fixture-0.1.0",
            capture_time=self.capture_time,
            request_params_hash=params_hash,
            response_hash=hashlib.sha256(json.dumps(window, sort_keys=True).encode()).hexdigest()[
                :32
            ],
        )
        return TransferPage(events=events, next_cursor=next_cursor, acquisition=acquisition)

    @staticmethod
    def _matches(raw: dict[str, Any], canonical: str, direction: Direction) -> bool:
        if direction is Direction.outgoing:
            return raw.get("from_address") == canonical
        if direction is Direction.incoming:
            return raw.get("to_address") == canonical
        return canonical in (raw.get("from_address"), raw.get("to_address"))

    @staticmethod
    def _within_cutoff(raw: dict[str, Any], cutoff: dt.datetime) -> bool:
        block_time = _parse_time(raw.get("block_time"))
        return block_time is None or block_time <= cutoff

    @staticmethod
    def _at_or_after_start(raw: dict[str, Any], start: dt.datetime | None) -> bool:
        if start is None:
            return True
        block_time = _parse_time(raw.get("block_time"))
        return block_time is None or block_time >= start
