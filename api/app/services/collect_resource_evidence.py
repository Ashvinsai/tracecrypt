"""Stage 2C2: resource-provider and TRX-funding evidence for one candidate.

Three genuinely distinct relationships, stored separately and never merged:

1. ``token_transfer``      candidate D -> accepted anchor H
2. ``resource_delegation``  resource provider R -> candidate D (Stake 2.0)
3. ``trx_funding``          TRX funder F -> candidate D (native TRX)

None of these implies common ownership. A resource sponsor, a TRX funder, and
a token-transfer counterparty are three separate facts about three separate
possible relationships, and keeping them separate is the point: this module
never writes verified_anchors.csv, never touches deposit_candidates.csv's
review fields, never touches review_log.csv, and provides no path from a
provider or a funder to an owner or service label. Results land in their own
file, data/resource_evidence.csv.

Resource-delegation evidence carries an explicit ``temporal_status``:

- ``"historical"`` -- drawn from a specific ``DelegateResourceContract``/
  ``UnDelegateResourceContract`` operation found in the candidate's own
  transaction history, carrying that operation's own ``block_time``.
- ``"current_state_only"`` -- drawn from ``getdelegatedresourceaccountindexv2``
  or ``getdelegatedresourcev2``, which report only what exists right now.
  Applying a current-state fact to an earlier moment -- the candidate's own
  historical token-transfer time, for instance -- is exactly the inference
  this module refuses to make; every current-state row's coverage window is
  the acquisition instant itself, never anything earlier.

TRX-funding evidence is always historical: every row comes from a specific
``TransferContract`` operation with its own real ``block_time``.

Bounded the same way Stage 1's seed search and Stage 2C's candidate search
are bounded: one candidate, one time window for the historical scan,
provider/funder limits, a request budget enforced at the adapter's own
request boundary, and every raw response saved before any row is written.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.adapters.base import Direction, ProviderError, ProviderErrorClass
from app.adapters.tron import DELEGATE_CONTRACT_TYPES, TRX_TRANSFER_CONTRACT_TYPE, TronGridAdapter
from app.core.settings import Settings
from app.services.labels import LabelRegistry
from app.services.live_validation import BundleRecorder

EVIDENCE_COLUMNS = [
    "network",
    "candidate_address",
    "relationship_type",
    "counterparty_address",
    "asset_or_resource_type",
    "tx_or_operation_id",
    "amount_base_units",
    "block_number",
    "block_time",
    "evidence_reference",
    "acquisition_mode",
    "coverage_start",
    "coverage_end",
    "coverage_complete",
    "temporal_status",
    "interpretation_limitations",
    "operation_type",
]

RELATIONSHIP_TOKEN_TRANSFER = "token_transfer"  # noqa: S105 -- a relationship name, not a secret
RELATIONSHIP_RESOURCE_DELEGATION = "resource_delegation"
RELATIONSHIP_TRX_FUNDING = "trx_funding"

TEMPORAL_HISTORICAL = "historical"
TEMPORAL_CURRENT_STATE_ONLY = "current_state_only"

#: Distinguishes a resource_delegation row's actual operation without parsing
#: interpretation_limitations text. Additive only -- relationship_type stays
#: "resource_delegation" for all four; this never becomes a fifth
#: relationship type of its own.
OPERATION_DELEGATE = "delegate"
OPERATION_UNDELEGATE = "undelegate"
OPERATION_CURRENT_INDEX = "current_index"
OPERATION_CURRENT_DETAIL = "current_detail"

_CURRENT_STATE_LIMITATION = (
    "Reflects a relationship observed at acquisition time only. It is not "
    "evidence that this relationship existed at any earlier moment, "
    "including the candidate's own historical token-transfer time."
)
_LOCK_EXPIRY_LIMITATION = (
    " A lock expiry, if present, is a delegation-cannot-be-cancelled-before "
    "date, never a delegation start date."
)


class ResourceEvidenceError(RuntimeError):
    """The collection cannot proceed. Never a silent skip."""


@dataclass(frozen=True)
class KnownTokenTransfer:
    """The already-established candidate -> anchor transfer.

    Supplied by the caller, never re-acquired here: collect_candidates
    already found and the accepted anchor's own review already verified this
    fact. Recording it here only lets one evidence file hold all three
    relationship types together; it does not re-derive or re-check anything.
    """

    counterparty_address: str
    tx_hash: str
    event_reference: str
    amount_base_units: int
    block_time: dt.datetime
    asset_symbol: str = "USDT"


@dataclass(frozen=True)
class ResourceEvidenceRequest:
    candidate_address: str
    network_key: str = "tron"
    #: Bounds the historical general-transaction scan only. Current-state
    #: delegation calls have no time window -- they answer "now", not "when".
    analysis_start: dt.datetime | None = None
    analysis_cutoff: dt.datetime | None = None
    #: Caps how many current-state delegation counterparties get a per-pair
    #: detail lookup, and how many resource_delegation rows (of either
    #: temporal_status) are kept.
    provider_limit: int = 10
    #: Caps how many trx_funding rows are kept.
    funder_limit: int = 10
    max_requests: int | None = None
    known_token_transfer: KnownTokenTransfer | None = None
    run_id: str | None = None


@dataclass
class EvidenceRow:
    network: str
    candidate_address: str
    relationship_type: str
    counterparty_address: str
    asset_or_resource_type: str
    tx_or_operation_id: str
    amount_base_units: int | None
    block_number: int | None
    block_time: dt.datetime | None
    evidence_reference: str
    acquisition_mode: str
    coverage_start: dt.datetime | None
    coverage_end: dt.datetime | None
    coverage_complete: bool
    temporal_status: str
    interpretation_limitations: str
    #: One of OPERATION_DELEGATE / OPERATION_UNDELEGATE / OPERATION_CURRENT_INDEX
    #: / OPERATION_CURRENT_DETAIL for resource_delegation rows; None for
    #: token_transfer and trx_funding rows, whose relationship_type alone
    #: already says what happened.
    operation_type: str | None = None

    def dedup_key(self) -> tuple[str, str]:
        """Two rows are the same observation only if they name the same
        operation. A different tx/operation id for the same counterparty is
        a distinct fact and must never be merged into one (F: dedup without
        merging distinct transactions/operations)."""
        return (self.relationship_type, self.tx_or_operation_id)

    def to_csv_row(self) -> dict[str, str]:
        return {
            "network": self.network,
            "candidate_address": self.candidate_address,
            "relationship_type": self.relationship_type,
            "counterparty_address": self.counterparty_address,
            "asset_or_resource_type": self.asset_or_resource_type,
            "tx_or_operation_id": self.tx_or_operation_id,
            "amount_base_units": (
                "" if self.amount_base_units is None else str(self.amount_base_units)
            ),
            "block_number": "" if self.block_number is None else str(self.block_number),
            "block_time": self.block_time.isoformat() if self.block_time else "",
            "evidence_reference": self.evidence_reference,
            "acquisition_mode": self.acquisition_mode,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else "",
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else "",
            "coverage_complete": "true" if self.coverage_complete else "false",
            "temporal_status": self.temporal_status,
            "interpretation_limitations": self.interpretation_limitations,
            "operation_type": self.operation_type or "",
        }


@dataclass
class CollectionRun:
    run_id: str
    directory: Path
    candidate_address: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    rows: list[EvidenceRow] = field(default_factory=list)
    requests_used: int = 0
    #: Set when a phase failed for a reason other than the request budget --
    #: never converted into "this phase found nothing" (F6).
    delegation_index_error: str | None = None
    delegated_resource_errors: list[str] = field(default_factory=list)
    history_scan_error: str | None = None
    truncated_by_provider_limit: bool = False
    truncated_by_funder_limit: bool = False
    truncated_by_request_budget: bool = False
    written: bool = False

    def _delegation_history_count(self) -> int:
        return sum(
            1
            for r in self.rows
            if r.relationship_type == RELATIONSHIP_RESOURCE_DELEGATION
            and r.temporal_status == TEMPORAL_HISTORICAL
        )


def _require_known_candidate(registry: LabelRegistry, network_key: str, address: str) -> None:
    if not registry.lookup(network_key, address):
        raise ResourceEvidenceError(
            f"{address} on {network_key} is not a known candidate or anchor; "
            "resource evidence starts from an address already on record, not "
            "an arbitrary one"
        )


async def collect_resource_evidence(
    settings: Settings,
    request: ResourceEvidenceRequest,
    *,
    out_root: Path,
    data_dir: Path,
    write: bool = False,
) -> CollectionRun:
    """Gather resource-delegation and TRX-funding evidence for one candidate.

    ``write=False`` (the default) previews the rows and writes the raw
    evidence bundle, but leaves ``data/resource_evidence.csv`` untouched
    until a caller explicitly asks to write it.
    """
    started_at = dt.datetime.now(dt.UTC)
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    _require_known_candidate(registry, request.network_key, request.candidate_address)

    run_id = request.run_id or (
        dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
    )
    directory = out_root / run_id
    directory.mkdir(parents=True, exist_ok=True)
    recorder = BundleRecorder(directory / "raw")

    adapter = TronGridAdapter(
        settings.tron_api_base,
        api_key=settings.tron_api_key,
        max_requests=request.max_requests,
        recorder=recorder,
        enrich_events=False,
    )

    run = CollectionRun(
        run_id=run_id, directory=directory, candidate_address=request.candidate_address,
        started_at=started_at,
    )

    if request.known_token_transfer is not None:
        run.rows.append(_known_transfer_row(request))

    budget_exhausted = await _collect_delegation_evidence(adapter, request, run)
    if not budget_exhausted:
        budget_exhausted = await _collect_history_scan(adapter, request, run)
    run.truncated_by_request_budget = budget_exhausted

    run.rows = _dedup(run.rows)
    run.finished_at = dt.datetime.now(dt.UTC)
    run.requests_used = adapter.request_count

    _write_raw_bundle_summary(run, request)
    if write:
        _append_evidence_rows(data_dir, run.rows)
        run.written = True
    _write_manifest(run, settings, request)
    return run


def _known_transfer_row(request: ResourceEvidenceRequest) -> EvidenceRow:
    kt = request.known_token_transfer
    assert kt is not None  # narrowed by caller
    return EvidenceRow(
        network=request.network_key,
        candidate_address=request.candidate_address,
        relationship_type=RELATIONSHIP_TOKEN_TRANSFER,
        counterparty_address=kt.counterparty_address,
        asset_or_resource_type=kt.asset_symbol,
        tx_or_operation_id=kt.tx_hash,
        amount_base_units=kt.amount_base_units,
        block_number=None,
        block_time=kt.block_time,
        evidence_reference=kt.event_reference,
        acquisition_mode="known_prior_evidence",
        coverage_start=kt.block_time,
        coverage_end=kt.block_time,
        coverage_complete=True,
        temporal_status=TEMPORAL_HISTORICAL,
        interpretation_limitations=(
            "Already established and verified by collect_candidates and the "
            "anchor's own review; not re-acquired or re-verified here."
        ),
    )


async def _collect_delegation_evidence(
    adapter: TronGridAdapter, request: ResourceEvidenceRequest, run: CollectionRun
) -> bool:
    """Current-state delegation index, then per-pair detail. Returns True if
    the request budget was exhausted partway through."""
    acquired_at = dt.datetime.now(dt.UTC)
    try:
        index = await adapter.fetch_delegation_index(request.candidate_address)
    except ProviderError as exc:
        if exc.error_class is ProviderErrorClass.budget_exhausted:
            return True
        # A provider failure here means this phase's evidence is unknown,
        # not that no delegators exist (F6). The history scan below is
        # independent and still runs.
        run.delegation_index_error = f"{exc.error_class.value}: {exc}"
        return False

    providers = index.from_accounts[: request.provider_limit]
    run.truncated_by_provider_limit = len(index.from_accounts) > request.provider_limit

    for provider in providers:
        run.rows.append(
            EvidenceRow(
                network=request.network_key,
                candidate_address=request.candidate_address,
                relationship_type=RELATIONSHIP_RESOURCE_DELEGATION,
                counterparty_address=provider,
                asset_or_resource_type="unknown",
                tx_or_operation_id=f"delegation-index:{provider}->{request.candidate_address}",
                amount_base_units=None,
                block_number=None,
                block_time=None,
                evidence_reference="wallet/getdelegatedresourceaccountindexv2",
                acquisition_mode="delegation_index_current_state",
                coverage_start=acquired_at,
                coverage_end=acquired_at,
                coverage_complete=True,
                temporal_status=TEMPORAL_CURRENT_STATE_ONLY,
                interpretation_limitations=_CURRENT_STATE_LIMITATION,
                operation_type=OPERATION_CURRENT_INDEX,
            )
        )

        try:
            details = await adapter.fetch_delegated_resource(provider, request.candidate_address)
        except ProviderError as exc:
            if exc.error_class is ProviderErrorClass.budget_exhausted:
                return True
            run.delegated_resource_errors.append(f"{provider}: {exc.error_class.value}: {exc}")
            continue

        for detail in details:
            run.rows.append(
                EvidenceRow(
                    network=request.network_key,
                    candidate_address=request.candidate_address,
                    relationship_type=RELATIONSHIP_RESOURCE_DELEGATION,
                    counterparty_address=provider,
                    asset_or_resource_type=detail.resource or "unknown",
                    tx_or_operation_id=(
                        f"delegated-resource:{provider}->{request.candidate_address}:"
                        f"{detail.resource or 'unknown'}"
                    ),
                    amount_base_units=detail.balance_sun,
                    block_number=None,
                    block_time=None,
                    evidence_reference="wallet/getdelegatedresourcev2",
                    acquisition_mode="delegated_resource_detail_current_state",
                    coverage_start=acquired_at,
                    coverage_end=acquired_at,
                    coverage_complete=True,
                    temporal_status=TEMPORAL_CURRENT_STATE_ONLY,
                    interpretation_limitations=_CURRENT_STATE_LIMITATION
                    + _LOCK_EXPIRY_LIMITATION,
                    operation_type=OPERATION_CURRENT_DETAIL,
                )
            )
    return False


async def _collect_history_scan(
    adapter: TronGridAdapter, request: ResourceEvidenceRequest, run: CollectionRun
) -> bool:
    """Genuinely historical resource-delegation operations and TRX funding,
    from one bounded scan of the candidate's own transaction history. Returns
    True if the request budget was exhausted partway through."""
    if request.analysis_cutoff is None:
        run.history_scan_error = "no analysis_cutoff given; historical scan skipped"
        return False

    cursor: str | None = None
    funders_seen = 0
    try:
        while True:
            page = await adapter.fetch_account_transactions(
                address=request.candidate_address,
                analysis_cutoff=request.analysis_cutoff,
                analysis_start=request.analysis_start,
                direction=Direction.both,
            )
            for tx in page.transactions:
                if tx.contract_type in DELEGATE_CONTRACT_TYPES:
                    receiver = tx.contract_value.get("receiver_address")
                    if receiver != request.candidate_address:
                        continue
                    if run._delegation_history_count() >= request.provider_limit:
                        run.truncated_by_provider_limit = True
                        continue
                    run.rows.append(_delegation_history_row(request, tx))
                elif tx.contract_type == TRX_TRANSFER_CONTRACT_TYPE:
                    to_address = tx.contract_value.get("to_address")
                    if to_address != request.candidate_address:
                        continue
                    if funders_seen >= request.funder_limit:
                        run.truncated_by_funder_limit = True
                        continue
                    funders_seen += 1
                    run.rows.append(_trx_funding_row(request, tx))
            cursor = page.next_cursor
            if not cursor:
                break
    except ProviderError as exc:
        if exc.error_class is ProviderErrorClass.budget_exhausted:
            return True
        run.history_scan_error = f"{exc.error_class.value}: {exc}"
    return False


def _delegation_operation_type(contract_type: str) -> str | None:
    """Structural direction of a historical Delegate/UnDelegate operation,
    read from the contract type itself -- never from interpretation text."""
    if contract_type == "DelegateResourceContract":
        return OPERATION_DELEGATE
    if contract_type == "UnDelegateResourceContract":
        return OPERATION_UNDELEGATE
    return None


def _delegation_history_row(request: ResourceEvidenceRequest, tx: Any) -> EvidenceRow:
    value = tx.contract_value
    owner = value.get("owner_address", "unknown")
    return EvidenceRow(
        network=request.network_key,
        candidate_address=request.candidate_address,
        relationship_type=RELATIONSHIP_RESOURCE_DELEGATION,
        counterparty_address=owner,
        asset_or_resource_type=value.get("resource") or "unknown",
        tx_or_operation_id=tx.tx_id,
        amount_base_units=value.get("balance"),
        block_number=tx.block_number,
        block_time=tx.block_time,
        evidence_reference=f"v1/accounts/.../transactions:{tx.tx_id}",
        acquisition_mode="historical_operation_scan",
        coverage_start=tx.block_time,
        coverage_end=tx.block_time,
        coverage_complete=tx.execution_result == "SUCCESS",
        temporal_status=TEMPORAL_HISTORICAL,
        interpretation_limitations=(
            f"{tx.contract_type} operation with its own execution result "
            f"({tx.execution_result or 'unknown'}); a resource delegation is "
            "not a token payment and is not evidence of shared ownership."
        ),
        operation_type=_delegation_operation_type(tx.contract_type),
    )


def _trx_funding_row(request: ResourceEvidenceRequest, tx: Any) -> EvidenceRow:
    value = tx.contract_value
    sender = value.get("owner_address", "unknown")
    return EvidenceRow(
        network=request.network_key,
        candidate_address=request.candidate_address,
        relationship_type=RELATIONSHIP_TRX_FUNDING,
        counterparty_address=sender,
        asset_or_resource_type="TRX",
        tx_or_operation_id=tx.tx_id,
        amount_base_units=value.get("amount"),
        block_number=tx.block_number,
        block_time=tx.block_time,
        evidence_reference=f"v1/accounts/.../transactions:{tx.tx_id}",
        acquisition_mode="historical_operation_scan",
        coverage_start=tx.block_time,
        coverage_end=tx.block_time,
        coverage_complete=tx.execution_result == "SUCCESS",
        temporal_status=TEMPORAL_HISTORICAL,
        interpretation_limitations=(
            "A native TRX transfer to this candidate. Not evidence that the "
            "sender is the candidate's owner, controller, or an exchange -- "
            "gas/fee funding is routine and comes from many kinds of sources."
        ),
    )


def _dedup(rows: list[EvidenceRow]) -> list[EvidenceRow]:
    seen: set[tuple[str, str]] = set()
    kept: list[EvidenceRow] = []
    for row in rows:
        key = row.dedup_key()
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_raw_bundle_summary(run: CollectionRun, request: ResourceEvidenceRequest) -> None:
    (run.directory / "evidence.json").write_text(
        json.dumps(
            {
                "candidate_address": run.candidate_address,
                "analysis_start": (
                    request.analysis_start.isoformat() if request.analysis_start else None
                ),
                "analysis_cutoff": (
                    request.analysis_cutoff.isoformat() if request.analysis_cutoff else None
                ),
                "provider_limit": request.provider_limit,
                "funder_limit": request.funder_limit,
                "max_requests": request.max_requests,
                "requests_used": run.requests_used,
                "truncated_by_provider_limit": run.truncated_by_provider_limit,
                "truncated_by_funder_limit": run.truncated_by_funder_limit,
                "truncated_by_request_budget": run.truncated_by_request_budget,
                "delegation_index_error": run.delegation_index_error,
                "delegated_resource_errors": run.delegated_resource_errors,
                "history_scan_error": run.history_scan_error,
                "rows": [r.to_csv_row() for r in run.rows],
            },
            indent=2,
        )
    )


def _append_evidence_rows(data_dir: Path, rows: list[EvidenceRow]) -> None:
    """Append new rows to data/resource_evidence.csv, deduplicated against
    what is already there by (relationship_type, tx_or_operation_id) -- never
    touching verified_anchors.csv, deposit_candidates.csv's review fields, or
    review_log.csv."""
    path = data_dir / "resource_evidence.csv"
    existing_keys: set[tuple[str, str]] = set()
    file_exists = path.is_file()
    if file_exists:
        with path.open(newline="") as fh:
            for existing in csv.DictReader(fh):
                existing_keys.add(
                    (existing.get("relationship_type", ""), existing.get("tx_or_operation_id", ""))
                )

    new_rows = [r for r in rows if r.dedup_key() not in existing_keys]
    if not new_rows:
        return
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVIDENCE_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for row in new_rows:
            writer.writerow(row.to_csv_row())


def _derive_legacy_operation_type(row: dict[str, str]) -> str | None:
    """Only for rows persisted before operation_type existed. Named here once,
    from fields already recorded on the row -- acquisition_mode for the two
    current-state kinds, the leading contract-type name already present in
    interpretation_limitations for historical delegate/undelegate rows -- so
    the migration adds no new fact, it only gives an existing one its own
    column. New rows never go through this path; see _delegation_operation_type
    and the two current-state row builders above."""
    if row.get("relationship_type") != RELATIONSHIP_RESOURCE_DELEGATION:
        return None
    mode = row.get("acquisition_mode")
    if mode == "delegation_index_current_state":
        return OPERATION_CURRENT_INDEX
    if mode == "delegated_resource_detail_current_state":
        return OPERATION_CURRENT_DETAIL
    if mode == "historical_operation_scan":
        text = row.get("interpretation_limitations", "")
        if text.startswith("DelegateResourceContract"):
            return OPERATION_DELEGATE
        if text.startswith("UnDelegateResourceContract"):
            return OPERATION_UNDELEGATE
    return None


def backfill_operation_type(data_dir: Path) -> int:
    """Upgrade data/resource_evidence.csv rows written before operation_type
    existed. Offline, no network access, and never touches the immutable
    var/collect-resource-evidence/<run>/ bundle (its manifest.json hashes
    evidence.json byte-for-byte; this only enriches the separate, evolvable
    analysis table). Idempotent -- rows that already carry operation_type
    (including "" for token_transfer/trx_funding) are left untouched. Returns
    the number of rows given a value for the first time."""
    path = data_dir / "resource_evidence.csv"
    if not path.is_file():
        return 0
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    if "operation_type" in fieldnames:
        return 0

    upgraded = 0
    for row in rows:
        derived = _derive_legacy_operation_type(row)
        row["operation_type"] = derived or ""
        upgraded += 1

    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVIDENCE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in EVIDENCE_COLUMNS})
    return upgraded


def _write_manifest(
    run: CollectionRun, settings: Settings, request: ResourceEvidenceRequest
) -> None:
    files = {
        str(p.relative_to(run.directory)): _digest(p)
        for p in sorted(run.directory.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    manifest = {
        "run_id": run.run_id,
        "provenance": {
            "run_started_at": run.started_at.isoformat(),
            "run_finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "artifact_created_at": dt.datetime.now(dt.UTC).isoformat(),
            "backfilled": False,
        },
        "query": {
            "network": request.network_key,
            "candidate_address": request.candidate_address,
            "analysis_start": (
                request.analysis_start.isoformat() if request.analysis_start else None
            ),
            "analysis_cutoff": (
                request.analysis_cutoff.isoformat() if request.analysis_cutoff else None
            ),
            "provider_limit": request.provider_limit,
            "funder_limit": request.funder_limit,
            "max_requests": request.max_requests,
        },
        "configuration": {
            "tron_api_base": settings.tron_api_base,
            "tron_api_key_configured": bool(settings.tron_api_key),
            "data_mode": settings.data_mode.value,
        },
        "requests_used": run.requests_used,
        "rows_found": len(run.rows),
        "relationship_counts": {
            rel: sum(1 for r in run.rows if r.relationship_type == rel)
            for rel in (
                RELATIONSHIP_TOKEN_TRANSFER,
                RELATIONSHIP_RESOURCE_DELEGATION,
                RELATIONSHIP_TRX_FUNDING,
            )
        },
        "truncated_by_provider_limit": run.truncated_by_provider_limit,
        "truncated_by_funder_limit": run.truncated_by_funder_limit,
        "truncated_by_request_budget": run.truncated_by_request_budget,
        "delegation_index_error": run.delegation_index_error,
        "delegated_resource_errors": run.delegated_resource_errors,
        "history_scan_error": run.history_scan_error,
        "written": run.written,
        "files": files,
        "caveat": (
            "A hash establishes that these files have not changed since the run. "
            "It does not establish that a provider, funder, or counterparty "
            "shares ownership with the candidate."
        ),
    }
    (run.directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
