"""The chain adapter contract.

Every provider — live, recorded, or fixture — implements this. The fixture
provider is a real implementation of this interface, not a shortcut that returns
canned trace results (D007). If the engine can be satisfied without an adapter,
the engine is untested.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.settings import DataMode
from app.models.enums import (
    AcquisitionStatus,
    ConfirmationState,
    CoverageStatus,
    EventKind,
    ExecutionStatus,
)
from app.services.addresses import CanonicalAddress


class Direction(StrEnum):
    outgoing = "outgoing"
    incoming = "incoming"
    both = "both"


class ProviderErrorClass(StrEnum):
    authentication = "authentication"
    quota = "quota"
    rate_limit = "rate_limit"
    timeout = "timeout"
    http_error = "http_error"
    parse_error = "parse_error"
    unsupported = "unsupported"
    #: The provider answered HTTP 200 with an error body. TRON documents this
    #: for the receipt endpoints: an exception returns only an ``Error`` field.
    provider_error = "provider_error"
    #: A caller-authorized request budget was reached. Never converted into an
    #: empty successful result -- an unexplored remainder is not an absence.
    budget_exhausted = "budget_exhausted"


class ProviderError(RuntimeError):
    """A provider failure. Never convertible into an empty successful history (T3)."""

    def __init__(self, error_class: ProviderErrorClass, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


@dataclass(frozen=True)
class AssetRef:
    """Network-scoped asset identity. A bare symbol is never an identity (D003)."""

    network_key: str
    token_contract: str | None
    decimals: int
    display_symbol: str


@dataclass(frozen=True)
class NormalizedTransfer:
    """One transfer event as the adapter observed it. Nothing here is inferred."""

    event_reference: str
    tx_hash: str
    event_kind: EventKind
    asset: AssetRef
    from_address: str | None
    to_address: str | None
    amount_base_units: int
    execution_status: ExecutionStatus
    confirmation_state: ConfirmationState
    block_height: int | None = None
    block_hash: str | None = None
    parent_block_hash: str | None = None
    block_time: dt.datetime | None = None
    index_in_block: int | None = None
    event_index: int | None = None
    #: True when the source could not supply ordering; the index is never invented (D005).
    ordering_ambiguous: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.amount_base_units, bool) or not isinstance(self.amount_base_units, int):
            raise TypeError("amount_base_units must be an int in base units")

    @property
    def is_zero_value(self) -> bool:
        return self.amount_base_units == 0

    @property
    def chain_sequence(self) -> str | None:
        if self.ordering_ambiguous:
            return None
        if self.block_height is None or self.index_in_block is None or self.event_index is None:
            return None
        return f"{self.block_height:012d}:{self.index_in_block:06d}:{self.event_index:06d}"


@dataclass
class AcquisitionRecord:
    """Provenance of one provider interaction, stored whether it succeeded or not."""

    provider: str
    endpoint: str
    requested_at: dt.datetime
    status: AcquisitionStatus
    coverage_status: CoverageStatus
    data_mode: DataMode
    analysis_cutoff: dt.datetime
    parser_version: str
    observed_at: dt.datetime | None = None
    error_class: str | None = None
    capture_time: dt.datetime | None = None
    request_params_hash: str = ""
    response_hash: str | None = None


@dataclass(frozen=True)
class ExecutionReceipt:
    """What a receipt endpoint said about one transaction.

    ``execution_status`` and ``confirmation_state`` answer different questions:
    whether the contract executed, and whether the block holding it is
    solidified. A transaction can be a successful execution that is not yet
    final, and neither answer is allowed to imply the other.
    """

    tx_hash: str
    execution_status: ExecutionStatus
    confirmation_state: ConfirmationState
    solidified: bool
    source_path: str
    note: str
    receipt_result: str | None = None
    block_number: int | None = None
    block_time: dt.datetime | None = None
    fee: int | None = None
    #: Optional, chain-specific finality classification beyond ``confirmation_state``'s
    #: four values -- e.g. EVM's "finalized" / "safe" / "head_unfinalized" / "unknown".
    #: ``None`` for adapters (TRON) that have nothing finer-grained to add; never
    #: required, never a substitute for ``confirmation_state``.
    finality_detail: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "execution_status": self.execution_status.value,
            "confirmation_state": self.confirmation_state.value,
            "solidified": self.solidified,
            "source_path": self.source_path,
            "note": self.note,
            "receipt_result": self.receipt_result,
            "block_number": self.block_number,
            "block_time": self.block_time.isoformat() if self.block_time else None,
            "fee": self.fee,
            "finality_detail": self.finality_detail,
        }


@dataclass(frozen=True)
class Unverified:
    """One event whose execution could not be established, and why."""

    event_reference: str
    tx_hash: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "event_reference": self.event_reference,
            "tx_hash": self.tx_hash,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExecutionVerification:
    """Events with whatever the receipts established, plus what they did not."""

    events: list[NormalizedTransfer]
    receipts: dict[str, ExecutionReceipt]
    unverified: list[Unverified]

    def to_json(self) -> dict[str, Any]:
        return {
            "receipts": {tx: r.to_json() for tx, r in self.receipts.items()},
            "unverified": [u.to_json() for u in self.unverified],
        }


@dataclass(frozen=True)
class Reconciliation:
    """Whether the event detail describes the transfer we think it does."""

    event_reference: str
    matched: bool
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "event_reference": self.event_reference,
            "matched": self.matched,
            "reason": self.reason,
        }


@dataclass
class TransferPage:
    events: list[NormalizedTransfer] = field(default_factory=list)
    next_cursor: str | None = None
    acquisition: AcquisitionRecord | None = None


class ChainAdapter(ABC):
    network_key: str
    supported_data_modes: frozenset[DataMode]

    @abstractmethod
    def validate_address(self, value: str) -> CanonicalAddress: ...

    @abstractmethod
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
        enrich: bool | None = None,
    ) -> TransferPage:
        """Return one page. A provider failure raises ``ProviderError``.

        Implementations must never return an empty page to represent a failure.
        ``analysis_start`` bounds the query from below as well as above, when a
        provider supports it -- a lower bound alongside the existing cutoff, not
        a replacement for it. ``enrich`` overrides an adapter's own default for
        this call only, so a caller that is about to check events by hand (a
        cheap raw-row scan for a known transaction id) can skip the more
        expensive per-transaction enrichment this page would otherwise do.
        """

    #: A network-scoped hook: given a reference this adapter produced, return
    #: the transaction id it names, or ``None`` if the reference is not one of
    #: this adapter's own or cannot be read back. The default supports no
    #: reference format, so a caller that wants to match by transaction id
    #: before paying for enrichment can check for ``None`` and fall back to a
    #: full, enrichment-driven scan instead (generic across adapters).
    @classmethod
    def tx_hash_from_reference(cls, reference: str) -> str | None:
        return None

    async def resolve_seed_event(
        self, transfer: NormalizedTransfer, asset: AssetRef
    ) -> NormalizedTransfer | None:
        """Enrich exactly one already-located transaction (B).

        Only called by a caller that got a non-``None`` result from
        ``tx_hash_from_reference``, so an adapter overriding that classmethod
        to actually resolve something is expected to override this too. The
        base implementation is never reached in practice; it exists so the
        interface is complete for an adapter that has not implemented either.
        """
        raise NotImplementedError(
            f"{type(self).__name__} supports tx_hash_from_reference but not "
            "resolve_seed_event"
        )

    def assert_mode_allowed(self, mode: DataMode) -> None:
        """Refuse to run under a data mode this adapter must not serve (D009)."""
        if mode not in self.supported_data_modes:
            raise ProviderError(
                ProviderErrorClass.unsupported,
                f"{type(self).__name__} refuses to serve data_mode={mode.value}",
            )
