"""Verify receipt execution/finality before the chronological walk, not after it.

The original full project verified receipts only after tracing in its validation
runner. With a fail-closed tracer that is too late. This adapter decorator uses
the existing provider receipt verifiers, caches them only within this run, and
preserves unverified failures and acquisition coverage. It never invents a receipt.
"""
from __future__ import annotations
from dataclasses import asdict, replace
from typing import Any
from app.adapters.base import ChainAdapter, TransferPage, NormalizedTransfer
from app.models.enums import CoverageStatus, ConfirmationState


class ReceiptGateAdapter(ChainAdapter):
    def __init__(self, delegate: ChainAdapter):
        self.delegate = delegate
        self.network_key = delegate.network_key
        self.supported_data_modes = delegate.supported_data_modes
        self._verified: dict[str, NormalizedTransfer] = {}
        self.receipts: dict[str, Any] = {}
        self.unverified: list[dict[str, Any]] = []
        self.acquisitions: list[dict[str, Any]] = []
        self.coverage_gaps: list[str] = []

    def validate_address(self, value):
        return self.delegate.validate_address(value)

    def tx_hash_from_reference(self, reference):
        return self.delegate.tx_hash_from_reference(reference)

    async def _verify(self, events):
        pending = [e for e in events if e.event_reference not in self._verified
                   and e.confirmation_state is not ConfirmationState.removed]
        if pending:
            verification = await self.delegate.verify_execution(pending)
            self._verified.update({e.event_reference: e for e in verification.events})
            self.receipts.update({k: r.to_json() for k, r in verification.receipts.items()})
            self.unverified.extend(u.to_json() for u in verification.unverified)
        # A removed log is never upgraded by a receipt for another inclusion.
        return [e if e.confirmation_state is ConfirmationState.removed
                else self._verified.get(e.event_reference, e) for e in events]

    async def fetch_transfers(self, **kwargs):
        page = await self.delegate.fetch_transfers(**kwargs)
        if page.acquisition is not None:
            self.acquisitions.append(asdict(page.acquisition))
            if (not page.next_cursor and page.acquisition.coverage_status
                    in (CoverageStatus.partial, CoverageStatus.unknown, CoverageStatus.failed)):
                self.coverage_gaps.append("Provider returned an incomplete terminal page or unresolved block range.")
        # Cheap seed search explicitly disables enrichment; verify only the
        # matching seed in resolve_seed_event, not unrelated history rows.
        events = page.events if kwargs.get("enrich") is False else await self._verify(page.events)
        return TransferPage(events=events, next_cursor=page.next_cursor, acquisition=page.acquisition)

    async def resolve_seed_event(self, transfer, asset):
        resolved = await self.delegate.resolve_seed_event(transfer, asset)
        if resolved is None:
            return None
        return (await self._verify([resolved]))[0]
