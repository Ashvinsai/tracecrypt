"""Stage 2 behavioral/sweep evidence: bounded TRC-20 history for one
candidate and one verified token contract, saved as its own normalized
evidence file.

Reuses the same TronGridAdapter.fetch_transfers used by the Stage 1 tracer --
the paginated TRC-20 history endpoint already gives per-event identity
(event_reference/event_index/ordering_ambiguous), exact base-unit amounts,
block time, and (via optional receipt verification) execution/confirmation
state. This module adds only the bounded incoming+outgoing walk, the
approval/failed-transfer exclusion, and the normalized CSV row.

This module never writes verified_anchors.csv, never touches
deposit_candidates.csv's review fields, and never touches review_log.csv --
a candidate is not promoted, and its role is not narrowed, by how it behaves
on-chain. Results land in their own file, data/behavioral_evidence.csv,
never merged into data/resource_evidence.csv (a different relationship
family entirely).

Design choice on execution verification: a TRC-20 ``Transfer`` log entry is
only ever emitted by a successfully executed transfer -- a reverted call
does not emit one -- so in practice the history endpoint alone very rarely
if ever contains a "failed transfer". Confirming that on-chain would cost
one extra receipt request per distinct transaction, which does not scale
against a small request budget. Verification is therefore opt-in
(``verify_execution=True``): when off, execution_status is left honestly
``unknown`` per NormalizedTransfer's own default, and the failed/approval
exclusion still runs so it is provably correct whenever the input ever does
carry a non-success status (see test_collect_behavioral_evidence.py).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from dataclasses import replace as dataclasses_replace
from pathlib import Path
from typing import Any, Literal

from app.adapters.base import (
    AssetRef,
    Direction,
    NormalizedTransfer,
    ProviderError,
    ProviderErrorClass,
)
from app.adapters.tron import TronGridAdapter
from app.core.settings import Settings
from app.models.enums import ConfirmationState, CoverageStatus, EventKind, ExecutionStatus
from app.services.evaluation_wallets import find_evaluation_wallet, load_evaluation_wallets
from app.services.evaluation_window import EvaluationWindow
from app.services.labels import LabelRegistry
from app.services.live_validation import BundleRecorder

#: "candidate_or_anchor" (the original, unchanged behavior): the subject
#: must already be on record in deposit_candidates.csv/verified_anchors.csv.
#: "evaluation_wallet": the subject must instead be an ACCEPTED record in
#: evaluation_wallets.csv -- a wallet independently explained by something
#: other than fraud (an exchange's own operational address, a payment
#: service, etc.). Evaluation-wallet capture never writes to
#: deposit_candidates.csv, verified_anchors.csv, review_log.csv, or
#: evaluation_review_log.csv, and never appends to
#: data/behavioral_evidence.csv -- it is bundle-only (see
#: collect_behavioral_evidence's write-guard below).
SubjectKind = Literal["candidate_or_anchor", "evaluation_wallet"]

BEHAVIORAL_EVIDENCE_COLUMNS = [
    "network",
    "candidate_address",
    "direction",
    "counterparty_address",
    "token_contract",
    "tx_hash",
    "event_index",
    "event_reference",
    "amount_base_units",
    "block_number",
    "block_time",
    "execution_status",
    "confirmation_state",
    "ordering_ambiguous",
    "evidence_reference",
    "acquisition_window_start",
    "acquisition_window_end",
    "coverage_status",
]

DIRECTION_INCOMING = "incoming"
DIRECTION_OUTGOING = "outgoing"


class BehavioralEvidenceError(RuntimeError):
    """The collection cannot proceed. Never a silent skip."""


#: The single canonical on-disk contract for evaluation-wallet evidence:
#:
#:     <evidence_root>/<network>/<address>/<run_id>/{manifest.json,evidence.json}
#:
#: ``<evidence_root>`` is the ``by-wallet`` directory. Each capture gets its
#: own ``<run_id>`` child, so distinct windows for the same wallet coexist and
#: no earlier capture is silently overwritten. The wallet directory
#: (``<network>/<address>``) and the capture run id are separate concepts --
#: the address is never used as the run id. Every reader (materialization,
#: readiness, console/status) discovers bundles through these helpers rather
#: than reconstructing the path.
BY_WALLET_DIRNAME = "by-wallet"


def _reject_unsafe_path_segment(value: str, field: str) -> None:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise BehavioralEvidenceError(
            f"refusing unsafe {field} for an evidence path: {value!r}"
        )


def evaluation_wallet_evidence_dir(
    evidence_root: Path, network: str, address: str
) -> Path:
    """The wallet's own bundle parent: ``<evidence_root>/<network>/<address>``."""
    _reject_unsafe_path_segment(network, "network")
    _reject_unsafe_path_segment(address, "address")
    return evidence_root / network / address


def evaluation_capture_dir(
    evidence_root: Path, network: str, address: str, run_id: str
) -> Path:
    """One capture bundle directory, under the wallet's bundle parent."""
    _reject_unsafe_path_segment(run_id, "run_id")
    return evaluation_wallet_evidence_dir(evidence_root, network, address) / run_id


def wallet_run_dirs(evidence_root: Path, network: str, address: str) -> list[Path]:
    """Every saved capture bundle for one (network, address), sorted by run id."""
    return run_dirs_in(evaluation_wallet_evidence_dir(evidence_root, network, address))


def run_dirs_in(wallet_dir: Path) -> list[Path]:
    """Every FINALIZED capture bundle directly under ``wallet_dir``, sorted by
    run id (deterministic).

    A staging directory (``.staging-*``), any hidden child, a failed/rejected
    run, or a directory missing its manifest/evidence file is NOT a finalized
    bundle and is ignored -- a half-written capture must never look
    materializable. Rejected runs live outside the wallet directory (see
    ``evaluation_rejected_root``)."""
    if not wallet_dir.is_dir():
        return []
    return sorted(
        path
        for path in wallet_dir.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and (path / "manifest.json").is_file()
        and (path / "evidence.json").is_file()
    )


#: Filesystem lifecycle of an evaluation-wallet capture. This is separate from
#: acquisition completeness: a bounded run that hit a configured limit is
#: ``partial`` on disk but still a valid, finalized bundle.
STAGING_PREFIX = ".staging-"

#: Discrete, declared bundle lifecycle states.
BUNDLE_STATE_STAGING = "staging"
BUNDLE_STATE_COMPLETE = "complete"
BUNDLE_STATE_PARTIAL = "partial"
BUNDLE_STATE_FAILED = "failed"

#: Bundle-level run outcome recorded in the manifest. ``partial`` means the
#: bounded run finished but a limit or a classified provider error truncated
#: it; it is never a failure. ``failed`` is only written under rejected-runs.
RUN_STATUS_COMPLETE = "complete"
RUN_STATUS_PARTIAL = "partial"
RUN_STATUS_FAILED = "failed"

REJECTED_RUNS_DIRNAME = "rejected-runs"


def evaluation_staging_dir(
    evidence_root: Path, network: str, address: str, run_id: str
) -> Path:
    """The non-final staging directory a capture writes into before an atomic
    rename into the canonical final path. Never materializable."""
    _reject_unsafe_path_segment(run_id, "run_id")
    return (
        evaluation_wallet_evidence_dir(evidence_root, network, address)
        / f"{STAGING_PREFIX}{run_id}"
    )


def evaluation_rejected_root(evidence_root: Path) -> Path:
    """Where failed/interrupted captures are preserved for forensics. This is
    a sibling of the by-wallet root, never inside a wallet directory, so no
    reader scanning wallet run directories can ever pick one up."""
    return evidence_root.parent / REJECTED_RUNS_DIRNAME


@dataclass(frozen=True)
class CaptureBundleValidation:
    """Structured result of checking one finalized-bundle candidate against
    the minimum contract derived from the actual readers
    (``load_preferred_behavioral_run`` reads manifest.json + evidence.json;
    replay reads raw/; materialization/readiness read the manifest query and
    window_selection). ``missing`` lists absent required artifacts; ``errors``
    lists present-but-invalid ones. ``ok`` is true only when both are empty."""

    path: Path
    ok: bool
    missing: tuple[str, ...]
    errors: tuple[str, ...]
    run_id: str | None
    subject_kind: str | None
    network: str | None
    address: str | None
    data_mode: str | None
    acquisition_completeness: str | None
    run_status: str | None


def validate_evaluation_capture_bundle(path: Path) -> CaptureBundleValidation:
    """Check a candidate capture bundle before it is allowed to finalize or be
    read as materializable. Pure filesystem/inspection: no network call."""
    missing: list[str] = []
    errors: list[str] = []
    manifest: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None

    if not path.is_dir():
        errors.append("not_a_directory")

    manifest_path = path / "manifest.json"
    evidence_path = path / "evidence.json"
    raw_dir = path / "raw"

    if not manifest_path.is_file():
        missing.append("manifest.json")
    else:
        try:
            loaded = json.loads(manifest_path.read_text())
            manifest = loaded if isinstance(loaded, dict) else None
            if manifest is None:
                errors.append("manifest.json:not_an_object")
        except (OSError, ValueError):
            errors.append("manifest.json:unreadable")
    if not evidence_path.is_file():
        missing.append("evidence.json")
    else:
        try:
            loaded = json.loads(evidence_path.read_text())
            evidence = loaded if isinstance(loaded, dict) else None
            if evidence is None:
                errors.append("evidence.json:not_an_object")
        except (OSError, ValueError):
            errors.append("evidence.json:unreadable")
    if not raw_dir.is_dir():
        missing.append("raw/")

    run_id = subject_kind = network = address = data_mode = acq = status = None
    if manifest is not None:
        query = manifest.get("query") or {}
        configuration = manifest.get("configuration") or {}
        window = manifest.get("window_selection") or {}
        run_id = manifest.get("run_id")
        subject_kind = manifest.get("subject_kind")
        network = query.get("network")
        address = query.get("candidate_address")
        data_mode = configuration.get("data_mode")
        acq = manifest.get("acquisition_completeness")
        status = manifest.get("run_status")

        if not run_id:
            errors.append("manifest:run_id_missing")
        if not subject_kind:
            errors.append("manifest:subject_kind_missing")
        if not network:
            errors.append("manifest:network_missing")
        if not address:
            errors.append("manifest:address_missing")
        if not window.get("requested_window_start") or not window.get("requested_window_cutoff"):
            errors.append("manifest:window_selection_missing")
        if subject_kind == "evaluation_wallet" and not manifest.get(
            "evaluation_wallet_registry_snapshot"
        ):
            errors.append("manifest:registry_snapshot_missing")
        if status not in (RUN_STATUS_COMPLETE, RUN_STATUS_PARTIAL):
            errors.append("manifest:run_status_not_final")
        if acq not in ("complete_within_scope", "truncated"):
            errors.append("manifest:acquisition_completeness_invalid")

    if evidence is not None and not evidence.get("candidate_address"):
        errors.append("evidence:candidate_address_missing")

    ok = not missing and not errors
    return CaptureBundleValidation(
        path=path,
        ok=ok,
        missing=tuple(missing),
        errors=tuple(errors),
        run_id=run_id,
        subject_kind=subject_kind,
        network=network,
        address=address,
        data_mode=data_mode,
        acquisition_completeness=acq,
        run_status=status,
    )


@dataclass(frozen=True)
class BehavioralEvidenceRequest:
    candidate_address: str
    token_contract: str
    #: Both bounds are required (not optional): a behavioral scan without an
    #: explicit start and cutoff has no defined acquisition window to report
    #: truncation or completeness against.
    analysis_start: dt.datetime
    analysis_cutoff: dt.datetime
    network_key: str = "tron"
    token_decimals: int = 6
    token_symbol: str = "USDT"  # noqa: S105 -- a token symbol, not a secret
    #: Caps pages walked per direction. A page is one paginated request.
    page_limit: int = 10
    #: Caps rows kept per direction -- distinct from page_limit because one
    #: page can hold up to 200 events.
    event_limit: int = 500
    max_requests: int | None = None
    #: Opt-in: one extra receipt request per distinct transaction. See the
    #: module docstring for why this defaults to False.
    verify_execution: bool = False
    #: Opt-in: resolves real event_index via the events endpoint (one extra
    #: request per distinct transaction). Off by default for the same
    #: budget reason; without it, multi-transfer transactions still get
    #: distinct, correct event_reference values (content-derived,
    #: ordering_ambiguous=True) -- see TronGridAdapter._to_transfer.
    enrich_events: bool = False
    run_id: str | None = None
    #: See SubjectKind above. Defaults to the original candidate/anchor-only
    #: behavior -- existing callers are unaffected.
    subject_kind: SubjectKind = "candidate_or_anchor"
    #: Stage 3B.3: for subject_kind="evaluation_wallet" only. The canonical
    #: storage contract is
    #: <evidence_root>/<network>/<address>/<run_id>/, so a recapture normally
    #: gets its own unique run directory and coexists with earlier windows.
    #: This guard still refuses to overwrite a bundle if a caller passes an
    #: explicit run_id that already exists -- a saved run is never silently
    #: replaced. Defaults to False (refuse); an operator who deliberately
    #: wants to replace a saved run must pass True explicitly.
    allow_overwrite_existing_run: bool = False
    #: Stage 4 provenance only. These descriptive strings are recorded in the
    #: run manifest's ``window_selection`` block; they never affect which
    #: events are fetched and never make a window "representative". The bounds
    #: themselves are always caller-supplied -- this service never chooses a
    #: window.
    evaluation_window_rationale: str = ""
    evaluation_window_policy: str = ""


@dataclass
class BehavioralEventRow:
    network: str
    candidate_address: str
    direction: str
    counterparty_address: str | None
    token_contract: str | None
    tx_hash: str
    event_index: int | None
    event_reference: str
    amount_base_units: int
    block_number: int | None
    block_time: dt.datetime | None
    execution_status: str
    confirmation_state: str
    ordering_ambiguous: bool
    evidence_reference: str
    acquisition_window_start: dt.datetime | None
    acquisition_window_end: dt.datetime | None
    coverage_status: str

    def dedup_key(self) -> tuple[str, str]:
        return (self.direction, self.event_reference)

    def to_csv_row(self) -> dict[str, str]:
        return {
            "network": self.network,
            "candidate_address": self.candidate_address,
            "direction": self.direction,
            "counterparty_address": self.counterparty_address or "",
            "token_contract": self.token_contract or "",
            "tx_hash": self.tx_hash,
            "event_index": "" if self.event_index is None else str(self.event_index),
            "event_reference": self.event_reference,
            "amount_base_units": str(self.amount_base_units),
            "block_number": "" if self.block_number is None else str(self.block_number),
            "block_time": self.block_time.isoformat() if self.block_time else "",
            "execution_status": self.execution_status,
            "confirmation_state": self.confirmation_state,
            "ordering_ambiguous": "true" if self.ordering_ambiguous else "false",
            "evidence_reference": self.evidence_reference,
            "acquisition_window_start": (
                self.acquisition_window_start.isoformat() if self.acquisition_window_start else ""
            ),
            "acquisition_window_end": (
                self.acquisition_window_end.isoformat() if self.acquisition_window_end else ""
            ),
            "coverage_status": self.coverage_status,
        }


@dataclass
class CollectionRun:
    run_id: str
    directory: Path
    candidate_address: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    rows: list[BehavioralEventRow] = field(default_factory=list)
    requests_used: int = 0
    truncated_by_page_limit: dict[str, bool] = field(
        default_factory=lambda: {DIRECTION_INCOMING: False, DIRECTION_OUTGOING: False}
    )
    truncated_by_event_limit: dict[str, bool] = field(
        default_factory=lambda: {DIRECTION_INCOMING: False, DIRECTION_OUTGOING: False}
    )
    truncated_by_request_budget: bool = False
    direction_errors: dict[str, str] = field(default_factory=dict)
    excluded_non_transfer_count: int = 0
    excluded_failed_or_reverted_count: int = 0
    execution_verification_unverified: list[dict[str, Any]] = field(default_factory=list)
    written: bool = False
    subject_kind: SubjectKind = "candidate_or_anchor"
    #: Populated only for subject_kind="evaluation_wallet": a snapshot of the
    #: admitting evaluation_wallets.csv row, for audit -- never written back
    #: to any registry/review CSV, and never fed into behavioral features.
    evaluation_wallet_snapshot: dict[str, str] | None = None

    def direction_truncated(self, direction: str) -> bool:
        return (
            self.truncated_by_page_limit.get(direction, False)
            or self.truncated_by_event_limit.get(direction, False)
            or self.truncated_by_request_budget
        )

    @property
    def acquisition_completeness(self) -> str:
        """Acquisition completeness ONLY, matching the definition
        ``load_preferred_behavioral_run`` uses: ``complete_within_scope`` when
        no page/event/request-budget limit truncated the bounded walk, else
        ``truncated``. This says nothing about whether the process finished
        (see ``run_status``); a bounded, truncated run is still a successful
        capture."""
        if (
            any(self.truncated_by_page_limit.values())
            or any(self.truncated_by_event_limit.values())
            or self.truncated_by_request_budget
        ):
            return "truncated"
        return "complete_within_scope"

    @property
    def run_status(self) -> str:
        """Bundle-level run outcome, distinct from acquisition completeness.
        ``partial`` means the bounded run finished but a limit or a classified
        provider error left the evidence incomplete; it is still a valid,
        finalized bundle. Unhandled failures never reach this and are written
        under rejected-runs as ``failed``."""
        if self.acquisition_completeness == "truncated" or self.direction_errors:
            return RUN_STATUS_PARTIAL
        return RUN_STATUS_COMPLETE


def _require_known_candidate(registry: LabelRegistry, network_key: str, address: str) -> None:
    if not registry.lookup(network_key, address):
        raise BehavioralEvidenceError(
            f"{address} on {network_key} is not a known candidate or anchor; "
            "behavioral evidence starts from an address already on record, not "
            "an arbitrary one"
        )


def _require_accepted_evaluation_wallet(
    data_dir: Path, network_key: str, address: str
) -> dict[str, str]:
    """Validate an evaluation-wallet subject and return an audit snapshot of
    its registry row.

    This never writes to deposit_candidates.csv, verified_anchors.csv,
    review_log.csv, or evaluation_review_log.csv, and never treats the
    address as a candidate or anchor -- an evaluation wallet is an
    independently-explained comparison wallet (e.g. an exchange's own
    operational address), not a fraud-tracing subject."""
    wallets = load_evaluation_wallets(data_dir / "evaluation_wallets.csv")
    wallet = find_evaluation_wallet(wallets, network_key, address)
    if wallet is None:
        raise BehavioralEvidenceError(
            f"{address} on {network_key} is not an accepted evaluation-wallet record in "
            "evaluation_wallets.csv; evaluation-wallet capture requires an existing "
            "review_state=accepted row (unreviewed/rejected/quarantined/missing/"
            "wrong-network records are refused, never silently promoted)"
        )
    return {
        "network": wallet.network,
        "address": wallet.address,
        "control_category": wallet.control_category,
        "source_reference": wallet.source_reference,
        "evidence_type": wallet.evidence_type,
        "review_state": wallet.review_state,
        "upstream_source_id": wallet.upstream_source_id,
        "reviewer": wallet.reviewer,
        "data_mode": wallet.data_mode,
    }


def _is_fund_flow_event(event: NormalizedTransfer) -> bool:
    """Approvals and non-executed events are evidence of nothing moving.

    Mirrors app.engine.tracer.ChronologicalTracer._is_spendable's day-one
    test 6 rule, applied here to bound what becomes a behavioral evidence
    row rather than what continues a trace path.
    """
    if event.event_kind is not EventKind.transfer:
        return False
    if event.execution_status in (ExecutionStatus.failed, ExecutionStatus.reverted):
        return False
    return event.confirmation_state is not ConfirmationState.removed


def _row_from_event(
    request: BehavioralEvidenceRequest,
    direction: str,
    event: NormalizedTransfer,
    coverage_status: CoverageStatus,
) -> BehavioralEventRow:
    counterparty = event.to_address if direction == DIRECTION_OUTGOING else event.from_address
    return BehavioralEventRow(
        network=request.network_key,
        candidate_address=request.candidate_address,
        direction=direction,
        counterparty_address=counterparty,
        token_contract=event.asset.token_contract,
        tx_hash=event.tx_hash,
        event_index=event.event_index,
        event_reference=event.event_reference,
        amount_base_units=event.amount_base_units,
        block_number=event.block_height,
        block_time=event.block_time,
        execution_status=event.execution_status.value,
        confirmation_state=event.confirmation_state.value,
        ordering_ambiguous=event.ordering_ambiguous,
        evidence_reference=f"v1/accounts/.../transactions/trc20:{event.event_reference}",
        acquisition_window_start=request.analysis_start,
        acquisition_window_end=request.analysis_cutoff,
        coverage_status=coverage_status.value,
    )


async def _collect_direction(
    adapter: TronGridAdapter,
    request: BehavioralEvidenceRequest,
    asset: AssetRef,
    direction: Direction,
    run: CollectionRun,
) -> tuple[list[NormalizedTransfer], dict[str, CoverageStatus], bool]:
    """Walk one direction's paginated history. Every filter (address, asset,
    direction, analysis_start/cutoff) is passed unchanged on every call
    except the cursor, so pagination cannot silently widen or narrow scope
    mid-walk.

    Returns the kept transfer-kind events, a map of event_reference ->
    the page's coverage_status they came from, and whether the request
    budget was exhausted partway through.
    """
    direction_key = DIRECTION_INCOMING if direction is Direction.incoming else DIRECTION_OUTGOING
    kept: list[NormalizedTransfer] = []
    coverage_by_ref: dict[str, CoverageStatus] = {}
    cursor: str | None = None
    pages = 0

    while True:
        try:
            page = await adapter.fetch_transfers(
                address=request.candidate_address,
                asset=asset,
                direction=direction,
                analysis_cutoff=request.analysis_cutoff,
                analysis_start=request.analysis_start,
                cursor=cursor,
                enrich=request.enrich_events,
            )
        except ProviderError as exc:
            if exc.error_class is ProviderErrorClass.budget_exhausted:
                return kept, coverage_by_ref, True
            run.direction_errors[direction_key] = f"{exc.error_class.value}: {exc}"
            return kept, coverage_by_ref, False
        pages += 1

        coverage_status = (
            page.acquisition.coverage_status if page.acquisition else CoverageStatus.unknown
        )
        for event in page.events:
            if event.event_kind is not EventKind.transfer:
                run.excluded_non_transfer_count += 1
                continue
            if len(kept) >= request.event_limit:
                run.truncated_by_event_limit[direction_key] = True
                break
            kept.append(event)
            coverage_by_ref[event.event_reference] = coverage_status

        cursor = page.next_cursor
        if len(kept) >= request.event_limit:
            if cursor:
                # This page's own continuation cursor says more history
                # exists; stopping here to respect event_limit is still a
                # truncation, even though no leftover event in *this* page
                # tripped the check above (F: a page landing exactly on the
                # cap must not silently read as complete).
                run.truncated_by_event_limit[direction_key] = True
            break
        if not cursor:
            break
        if pages >= request.page_limit:
            run.truncated_by_page_limit[direction_key] = True
            break

    return kept, coverage_by_ref, False


async def collect_behavioral_evidence(
    settings: Settings,
    request: BehavioralEvidenceRequest,
    *,
    out_root: Path,
    data_dir: Path,
    write: bool = False,
) -> CollectionRun:
    """Gather bounded TRC-20 behavioral evidence for one candidate.

    ``write=False`` (the default) previews the rows and writes the raw
    evidence bundle, but leaves data/behavioral_evidence.csv untouched until
    a caller explicitly asks to write it.

    ``request.subject_kind="evaluation_wallet"`` validates the subject
    against evaluation_wallets.csv (an accepted record required) instead of
    the candidate/anchor registries, and is always bundle-only: ``write=True``
    is refused for this subject kind, because an evaluation wallet is never
    the source of a data/behavioral_evidence.csv row.
    """
    started_at = dt.datetime.now(dt.UTC)
    evaluation_wallet_snapshot: dict[str, str] | None = None
    if request.subject_kind == "evaluation_wallet":
        if write:
            raise BehavioralEvidenceError(
                "evaluation-wallet capture is bundle-only; write=True is refused because "
                "an evaluation wallet is never a source of a behavioral_evidence.csv row"
            )
        evaluation_wallet_snapshot = _require_accepted_evaluation_wallet(
            data_dir, request.network_key, request.candidate_address
        )
    else:
        registry = LabelRegistry.from_reviewed_sets(data_dir)
        _require_known_candidate(registry, request.network_key, request.candidate_address)

    run_id = request.run_id or (
        dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
    )
    is_evaluation = request.subject_kind == "evaluation_wallet"
    final_dir: Path | None = None
    if is_evaluation:
        # out_root is the by-wallet evidence root for this subject kind.
        final_dir = evaluation_capture_dir(
            out_root, request.network_key, request.candidate_address, run_id
        )
        staging_dir = evaluation_staging_dir(
            out_root, request.network_key, request.candidate_address, run_id
        )
        if (final_dir / "manifest.json").is_file() and not request.allow_overwrite_existing_run:
            raise BehavioralEvidenceError(
                f"refused: {final_dir / 'manifest.json'} already exists. The by-wallet "
                "storage convention writes each evaluation-wallet capture to "
                "<evidence_root>/<network>/<address>/<run_id>, and a saved run must "
                "never be silently overwritten by a later capture. Pass "
                "allow_overwrite_existing_run=True (an explicit operator decision) to "
                "replace it, or use a different --run-id."
            )
        if staging_dir.exists():
            raise BehavioralEvidenceError(
                f"refused: a staging directory already exists at {staging_dir}; a "
                "previous capture with this run id was interrupted. Inspect/remove it "
                "before retrying -- an interrupted capture is never finalized silently."
            )
        work_dir = staging_dir
    else:
        work_dir = out_root / run_id
    work_dir.mkdir(parents=True, exist_ok=True)
    recorder = BundleRecorder(work_dir / "raw")

    adapter = TronGridAdapter(
        settings.tron_api_base,
        api_key=settings.tron_api_key,
        max_requests=request.max_requests,
        recorder=recorder,
        enrich_events=request.enrich_events,
    )

    asset = AssetRef(
        network_key=request.network_key,
        token_contract=request.token_contract,
        decimals=request.token_decimals,
        display_symbol=request.token_symbol,
    )

    run = CollectionRun(
        run_id=run_id,
        directory=work_dir,
        candidate_address=request.candidate_address,
        started_at=started_at,
        subject_kind=request.subject_kind,
        evaluation_wallet_snapshot=evaluation_wallet_snapshot,
    )

    try:
        all_events: dict[str, NormalizedTransfer] = {}
        event_direction: dict[str, str] = {}
        coverage_by_ref: dict[str, CoverageStatus] = {}
        budget_exhausted = False

        for direction, direction_key in (
            (Direction.incoming, DIRECTION_INCOMING),
            (Direction.outgoing, DIRECTION_OUTGOING),
        ):
            if budget_exhausted:
                break
            events, coverage, exhausted = await _collect_direction(
                adapter, request, asset, direction, run
            )
            for event in events:
                all_events[event.event_reference] = event
                event_direction[event.event_reference] = direction_key
            coverage_by_ref.update(coverage)
            budget_exhausted = exhausted

        run.truncated_by_request_budget = budget_exhausted

        events_list = list(all_events.values())
        if request.verify_execution and events_list and not budget_exhausted:
            verification = await adapter.verify_execution(events_list)
            for event in verification.events:
                all_events[event.event_reference] = event
            run.execution_verification_unverified = [
                u.to_json() for u in verification.unverified
            ]
            if any("budget_exhausted" in u.reason for u in verification.unverified):
                run.truncated_by_request_budget = True

        for reference, event in all_events.items():
            if not _is_fund_flow_event(event):
                run.excluded_failed_or_reverted_count += 1
                continue
            run.rows.append(
                _row_from_event(
                    request,
                    event_direction[reference],
                    event,
                    coverage_by_ref.get(reference, CoverageStatus.unknown),
                )
            )

        run.rows.sort(
            key=lambda r: (
                r.block_time or dt.datetime.min.replace(tzinfo=dt.UTC),
                r.event_reference,
            )
        )
        run.finished_at = dt.datetime.now(dt.UTC)
        run.requests_used = adapter.request_count

        _write_raw_bundle_summary(run, request)
        if write:
            _append_evidence_rows(data_dir, run.rows)
            run.written = True
        _write_manifest(run, settings, request)

        if is_evaluation:
            validation = validate_evaluation_capture_bundle(work_dir)
            if not validation.ok:
                raise BehavioralEvidenceError(
                    "capture bundle failed its finalize validation: "
                    f"missing={list(validation.missing)} errors={list(validation.errors)}"
                )
            assert final_dir is not None
            if final_dir.exists() and request.allow_overwrite_existing_run:
                shutil.rmtree(final_dir)
            # Atomic rename within the same wallet directory: file-by-file copy
            # into the final location is never used.
            work_dir.rename(final_dir)
            run.directory = final_dir
        return run
    except Exception as exc:
        if not is_evaluation:
            raise
        failure_dir = _preserve_failed_capture(
            settings=settings,
            evidence_root=out_root,
            request=request,
            run=run,
            started_at=started_at,
            failure=exc,
            requests_used=adapter.request_count,
        )
        if isinstance(exc, BehavioralEvidenceError):
            raise
        raise BehavioralEvidenceError(
            f"evaluation-wallet capture failed ({type(exc).__name__}); forensic "
            f"evidence preserved at {failure_dir}"
        ) from exc


async def collect_behavioral_evidence_for_evaluation_wallet(
    settings: Settings,
    request: BehavioralEvidenceRequest,
    *,
    out_root: Path,
    data_dir: Path,
) -> CollectionRun:
    """Thin, explicit wrapper: forces ``subject_kind="evaluation_wallet"`` and
    ``write=False``. Prefer this over hand-setting subject_kind on a
    long-lived request so a caller cannot accidentally construct a
    candidate/anchor request and reuse it here (or vice versa)."""
    if request.subject_kind != "evaluation_wallet":
        request = dataclasses_replace(request, subject_kind="evaluation_wallet")
    return await collect_behavioral_evidence(
        settings, request, out_root=out_root, data_dir=data_dir, write=False
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_raw_bundle_summary(run: CollectionRun, request: BehavioralEvidenceRequest) -> None:
    (run.directory / "evidence.json").write_text(
        json.dumps(
            {
                "candidate_address": run.candidate_address,
                "token_contract": request.token_contract,
                "analysis_start": request.analysis_start.isoformat(),
                "analysis_cutoff": request.analysis_cutoff.isoformat(),
                "page_limit": request.page_limit,
                "event_limit": request.event_limit,
                "max_requests": request.max_requests,
                "verify_execution": request.verify_execution,
                "enrich_events": request.enrich_events,
                "requests_used": run.requests_used,
                "truncated_by_page_limit": run.truncated_by_page_limit,
                "truncated_by_event_limit": run.truncated_by_event_limit,
                "truncated_by_request_budget": run.truncated_by_request_budget,
                "direction_errors": run.direction_errors,
                "excluded_non_transfer_count": run.excluded_non_transfer_count,
                "excluded_failed_or_reverted_count": run.excluded_failed_or_reverted_count,
                "execution_verification_unverified": run.execution_verification_unverified,
                "rows": [r.to_csv_row() for r in run.rows],
            },
            indent=2,
        )
    )


def _append_evidence_rows(data_dir: Path, rows: list[BehavioralEventRow]) -> None:
    """Append new rows to data/behavioral_evidence.csv, deduplicated by
    (direction, event_reference) -- a separate file from
    data/resource_evidence.csv, never touching verified_anchors.csv,
    deposit_candidates.csv's review fields, or review_log.csv."""
    path = data_dir / "behavioral_evidence.csv"
    existing_keys: set[tuple[str, str]] = set()
    file_exists = path.is_file()
    if file_exists:
        with path.open(newline="") as fh:
            for existing in csv.DictReader(fh):
                existing_keys.add(
                    (existing.get("direction", ""), existing.get("event_reference", ""))
                )

    new_rows = [r for r in rows if r.dedup_key() not in existing_keys]
    if not new_rows:
        return
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=BEHAVIORAL_EVIDENCE_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for row in new_rows:
            writer.writerow(row.to_csv_row())


def _write_manifest(
    run: CollectionRun, settings: Settings, request: BehavioralEvidenceRequest
) -> None:
    files = {
        str(p.relative_to(run.directory)): _digest(p)
        for p in sorted(run.directory.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    window = EvaluationWindow(
        network=request.network_key,
        address=request.candidate_address,
        start=request.analysis_start,
        cutoff=request.analysis_cutoff,
        rationale=request.evaluation_window_rationale,
        policy=request.evaluation_window_policy,
    )
    manifest = {
        "run_id": run.run_id,
        "run_status": run.run_status,
        "subject_kind": run.subject_kind,
        "acquisition_completeness": run.acquisition_completeness,
        "capture_started_at": run.started_at.isoformat(),
        "capture_completed_at": run.finished_at.isoformat() if run.finished_at else None,
        "evaluation_wallet_registry_snapshot": run.evaluation_wallet_snapshot,
        "window_selection": window.manifest_fields(run_id=run.run_id),
        "provenance": {
            "run_started_at": run.started_at.isoformat(),
            "run_finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "artifact_created_at": dt.datetime.now(dt.UTC).isoformat(),
            "backfilled": False,
        },
        "budgets": {
            "page_limit": request.page_limit,
            "event_limit": request.event_limit,
            "max_requests": request.max_requests,
            "requests_used": run.requests_used,
        },
        "query": {
            "network": request.network_key,
            "candidate_address": request.candidate_address,
            "token_contract": request.token_contract,
            "analysis_start": request.analysis_start.isoformat(),
            "analysis_cutoff": request.analysis_cutoff.isoformat(),
            "page_limit": request.page_limit,
            "event_limit": request.event_limit,
            "max_requests": request.max_requests,
            "verify_execution": request.verify_execution,
            "enrich_events": request.enrich_events,
        },
        "configuration": {
            "tron_api_base": settings.tron_api_base,
            "tron_api_key_configured": bool(settings.tron_api_key),
            "data_mode": settings.data_mode.value,
        },
        "requests_used": run.requests_used,
        "rows_found": len(run.rows),
        "direction_counts": {
            direction: sum(1 for r in run.rows if r.direction == direction)
            for direction in (DIRECTION_INCOMING, DIRECTION_OUTGOING)
        },
        "truncated_by_page_limit": run.truncated_by_page_limit,
        "truncated_by_event_limit": run.truncated_by_event_limit,
        "truncated_by_request_budget": run.truncated_by_request_budget,
        "direction_errors": run.direction_errors,
        "excluded_non_transfer_count": run.excluded_non_transfer_count,
        "excluded_failed_or_reverted_count": run.excluded_failed_or_reverted_count,
        "written": run.written,
        "files": files,
        "caveat": (
            "Repeated forwarding or high outgoing concentration recorded from this "
            "bundle is behavioral evidence only. It does not establish OKX ownership, "
            "customer-deposit status, service ownership, fraud, common control, or a "
            "strong inference of any kind."
        ),
    }
    (run.directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _preserve_failed_capture(
    *,
    settings: Settings,
    evidence_root: Path,
    request: BehavioralEvidenceRequest,
    run: CollectionRun,
    started_at: dt.datetime,
    failure: Exception,
    requests_used: int,
) -> Path:
    """Move a failed/interrupted evaluation-wallet capture out of staging into
    ``rejected-runs/`` and record a secret-free failure manifest. Never
    deletes evidence; never writes a provider credential (BundleRecorder
    records method/path/params/body only, never headers)."""
    rejected_root = evaluation_rejected_root(evidence_root)
    rejected_root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = rejected_root / (
        f"{request.network_key}-{request.candidate_address}-{run.run_id}-"
        f"{settings.data_mode.value}-{stamp}-invalid"
    )
    raw_files = (
        sorted(p.name for p in (run.directory / "raw").rglob("*") if p.is_file())
        if (run.directory / "raw").is_dir()
        else []
    )
    classification = (
        failure.error_class.value
        if isinstance(failure, ProviderError)
        else type(failure).__name__
    )
    record = {
        "run_status": RUN_STATUS_FAILED,
        "run_id": run.run_id,
        "subject_kind": request.subject_kind,
        "network": request.network_key,
        "address": request.candidate_address,
        "data_mode": settings.data_mode.value,
        "requested_window_start": request.analysis_start.isoformat(),
        "requested_window_cutoff": request.analysis_cutoff.isoformat(),
        "capture_started_at": started_at.isoformat(),
        "failure_time": dt.datetime.now(dt.UTC).isoformat(),
        "failure_type": type(failure).__name__,
        "error_classification": classification,
        "requests_completed": requests_used,
        "raw_response_files": raw_files,
        "raw_responses_present": bool(raw_files),
        "note": (
            "failed or interrupted capture preserved for forensics; never a "
            "materializable bundle"
        ),
    }
    if run.directory.exists():
        run.directory.rename(dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    (dest / "FAILED.json").write_text(json.dumps(record, indent=2, sort_keys=True))
    return dest


@dataclass(frozen=True)
class PreferredBehavioralRun:
    """One collect_behavioral_evidence run bundle, chosen by a caller as the
    authoritative behavioral-acquisition source for a candidate -- e.g. a
    later, non-truncated run superseding an earlier truncated one for the
    same window. Completeness here comes from this run's own manifest, never
    from data/behavioral_evidence.csv's per-row coverage_status, which can
    still carry an earlier run's now-superseded partial status for rows a
    later complete run re-observed identically (F1)."""

    run_id: str
    candidate_address: str
    rows: tuple[dict[str, str], ...]
    behavioral_window_start: dt.datetime
    behavioral_window_end: dt.datetime
    incoming_complete: bool
    outgoing_complete: bool
    request_budget_truncated: bool
    page_limit_truncated: bool
    event_limit_truncated: bool
    acquisition_mode: str = "collect_behavioral_evidence"

    @property
    def acquisition_completeness(self) -> str:
        """ "complete_within_scope" | "truncated" -- acquisition status only.

        This says nothing about whether any row's execution or event
        ordering was verified; see behavioral_features.py's
        verification_quality/event_identity_quality/ordering_quality for
        that separate question. Never read one status as implying both (A)."""
        return (
            "complete_within_scope"
            if (self.incoming_complete and self.outgoing_complete)
            else "truncated"
        )


def load_preferred_behavioral_run(run_dir: Path) -> PreferredBehavioralRun:
    """Read one run bundle's manifest.json and evidence.json directly from
    disk. Offline, no network access: this only opens files this repository
    already saved."""
    manifest = json.loads((run_dir / "manifest.json").read_text())
    evidence = json.loads((run_dir / "evidence.json").read_text())
    query = manifest["query"]
    page_limit_by_direction = manifest["truncated_by_page_limit"]
    event_limit_by_direction = manifest["truncated_by_event_limit"]
    budget_truncated = bool(manifest["truncated_by_request_budget"])

    def _direction_complete(direction: str) -> bool:
        return not (
            page_limit_by_direction.get(direction, False)
            or event_limit_by_direction.get(direction, False)
            or budget_truncated
        )

    return PreferredBehavioralRun(
        run_id=manifest["run_id"],
        candidate_address=query["candidate_address"],
        rows=tuple(evidence["rows"]),
        behavioral_window_start=dt.datetime.fromisoformat(query["analysis_start"]),
        behavioral_window_end=dt.datetime.fromisoformat(query["analysis_cutoff"]),
        incoming_complete=_direction_complete(DIRECTION_INCOMING),
        outgoing_complete=_direction_complete(DIRECTION_OUTGOING),
        request_budget_truncated=budget_truncated,
        page_limit_truncated=any(page_limit_by_direction.values()),
        event_limit_truncated=any(event_limit_by_direction.values()),
    )
