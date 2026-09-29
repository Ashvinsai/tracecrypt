"""One live trace, saved whole, and replayable offline afterwards.

This is the Stage 1 gate's evidence: real observations from TronGrid, followed
to an accepted anchor from the reviewed label sets, with everything the run saw
written to disk so a second person can check it.

The bundle under ``var/live-validation/<run-id>/``:

``manifest.json``      what ran, when, against what, and the hash of every file
``raw/``               every provider exchange, exactly as it arrived
``normalized-transfers.json``  what the parser made of them
``receipts.json``      execution and finality per transaction, and what failed
``accepted-label-snapshot.json``  the label claims as they stood at run time
``token-verification.json``  EVM only: read-only contract checks (code, decimals,
                       symbol, name), recorded in ``raw/`` and replayed like any
                       other exchange
``trace.json``         the result
``report.html``        the printable evidence view

Three refusals, all deliberate:

- A live run without ``CFA_DATA_MODE=LIVE`` and a configured key **fails**. It
  does not skip, and it does not quietly produce a fixture run: an explicitly
  requested live validation that reports success without touching the chain is
  the worst possible outcome here.
- A provider failure fails the validation. Partial evidence is recorded and the
  run is marked failed rather than presented as a clean result.
- Replay reads the recorded bundle through the same parser, tracer and report.
  A request the recording does not contain is a provider error, never empty
  data — a replay that invents silence is not a replay.

No secret is written: headers are never recorded, and the manifest states only
whether a key was configured.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx

from app.adapters.base import AssetRef, ProviderError
from app.adapters.evm import BLOCK_RESOLUTION_CURRENT, EVM_NETWORKS, EvmRpcAdapter
from app.adapters.execution import ReceiptVerifiable
from app.adapters.tron import TronGridAdapter
from app.core.settings import DataMode, Settings
from app.engine.result import Limitation, TraceResult
from app.models.enums import BoundaryReason, CaseFlowLinkage, ExecutionStatus
from app.reports.evidence import render_evidence_html
from app.services.trace_service import TraceUnavailable, load_labels, run_trace

BUNDLE_VERSION = "1"


class LiveValidationError(RuntimeError):
    """The run cannot proceed, or did not complete. Never a silent skip."""


@dataclass(frozen=True)
class ValidationRequest:
    address: str
    token_contract: str
    seed_event_reference: str | None = None
    network_key: str = "tron"
    asset_decimals: int = 6
    asset_symbol: str = "USDT"
    analysis_cutoff: dt.datetime | None = None
    #: Lower bound for the seed-event search only, alongside the existing
    #: cutoff -- narrows the acquisition itself rather than filtering a wider
    #: page after the fact (A). ``None`` searches from account genesis, as
    #: before.
    analysis_start: dt.datetime | None = None
    #: Caps genuine network requests across the whole run: seed lookup, event
    #: enrichment, receipts, pagination, the tracer's own acquisition (C).
    #: ``None`` leaves the adapter unbounded, as before.
    max_requests: int | None = None
    run_id: str | None = None
    #: EVM only: read the token contract's code and ``decimals()``/``symbol()``/
    #: ``name()`` first, through the same recorded adapter, and refuse the run
    #: when there is no code or the on-chain decimals differ from
    #: ``asset_decimals``. A replay sets this from its source bundle: a bundle
    #: recorded before this check existed holds no such exchanges to replay.
    verify_token: bool = True
    #: EVM only: how the window start resolves to a block (see
    #: ``app.adapters.evm``). Recorded in the manifest; a replay passes the
    #: policy its bundle was recorded with.
    block_resolution_policy: str = BLOCK_RESOLUTION_CURRENT


@dataclass
class ValidationRun:
    run_id: str
    directory: Path
    status: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    trace: dict[str, Any] | None = None
    exchanges: int = 0
    receipts: dict[str, Any] = field(default_factory=dict)
    failure: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exchange_key(method: str, path: str, params: dict[str, Any], payload: dict[str, Any]) -> str:
    """Identifies one provider exchange, for replay lookup.

    The key covers the query and the body, so a paginated sequence replays in
    the order the live run made it rather than collapsing into one page.
    """
    canonical = json.dumps(
        {
            "method": method.upper(),
            "path": path,
            # httpx gives back strings on replay and the caller passes ints on
            # the way out; the exchange is the same exchange either way.
            "params": {str(k): str(v) for k, v in params.items()},
            "payload": {str(k): str(v) for k, v in payload.items()},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _slug(path: str) -> str:
    return path.strip("/").replace("/", "-")[:60] or "root"


class BundleRecorder:
    """Writes every provider exchange into ``raw/`` as it happens."""

    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.count = 0

    def __call__(self, exchange: dict[str, Any]) -> None:
        self.count += 1
        record = dict(exchange)
        record["key"] = exchange_key(
            exchange["method"], exchange["path"], exchange["params"], exchange["payload"]
        )
        record["sequence"] = self.count
        name = f"{self.count:04d}-{exchange['method'].lower()}-{_slug(exchange['path'])}.json"
        (self.raw_dir / name).write_text(json.dumps(record, indent=2, sort_keys=True))


def replay_client(raw_dir: Path) -> httpx.AsyncClient:
    """An httpx client serving a recorded bundle, and nothing else.

    A request the recording does not hold returns a body the adapter classifies
    as a provider error. It never returns an empty result, because "we have no
    recording of this" and "the chain had nothing" are different facts.
    """
    recordings = load_recordings(raw_dir)
    pending: dict[str, list[dict[str, Any]]] = {}
    for record in recordings:
        pending.setdefault(record["key"], []).append(record)

    def handler(request: httpx.Request) -> httpx.Response:
        payload: dict[str, Any] = {}
        if request.content:
            try:
                payload = json.loads(request.content)
            except ValueError:
                payload = {}
        params = {k: v for k, v in request.url.params.items()}
        key = exchange_key(request.method, request.url.path, params, payload)
        queue = pending.get(key)
        if not queue:
            return httpx.Response(
                200,
                json={
                    "Error": (
                        f"replay miss: the bundle holds no {request.method} "
                        f"{request.url.path} with these parameters"
                    )
                },
            )
        record = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(record.get("status", 200), json=record["body"])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def load_recordings(raw_dir: Path) -> list[dict[str, Any]]:
    if not raw_dir.is_dir():
        raise LiveValidationError(f"no recorded exchanges at {raw_dir}")
    records = [json.loads(p.read_text()) for p in sorted(raw_dir.glob("*.json"))]
    if not records:
        raise LiveValidationError(f"no recorded exchanges at {raw_dir}")
    return records


def preflight(settings: Settings, network_key: str) -> None:
    """Refuse a live run that would not be live, or that has nothing to run on. Loudly."""
    if settings.data_mode is not DataMode.LIVE:
        raise LiveValidationError(
            f"live validation needs CFA_DATA_MODE=LIVE; it is {settings.data_mode.value}. "
            "Refusing to report a fixture run as a live one"
        )
    if network_key == "tron":
        if not settings.tron_api_key:
            raise LiveValidationError(
                "live validation needs CFA_TRON_API_KEY; without it TronGrid answers "
                "unauthenticated and a quota error is indistinguishable from an empty history"
            )
    elif network_key in EVM_NETWORKS:
        if not settings.evm_rpc_url(network_key):
            raise LiveValidationError(
                f"live validation needs {EVM_NETWORKS[network_key].rpc_env_var} for network "
                f"{network_key!r}; not silently choosing a public RPC endpoint, or another "
                "network's, to make this run happen"
            )
    else:
        raise LiveValidationError(f"no live adapter is configured for network {network_key!r}")


def _build_adapter(
    settings: Settings,
    network_key: str,
    *,
    client: httpx.AsyncClient | None,
    recorder: BundleRecorder | None,
    max_requests: int | None,
    block_resolution_policy: str = BLOCK_RESOLUTION_CURRENT,
) -> TronGridAdapter | EvmRpcAdapter:
    """The one place a live-validation run picks its adapter, by network (D009)."""
    if network_key == "tron":
        return TronGridAdapter(
            settings.tron_api_base,
            api_key=settings.tron_api_key,
            client=client,
            recorder=recorder,
            max_requests=max_requests,
        )
    if network_key in EVM_NETWORKS:
        # A replay (``client`` provided) always gets the placeholder, even if
        # the network's RPC URL also happens to be configured (the same
        # settings commonly serve both LIVE and RECORDED_PUBLIC runs). The
        # adapter's own request recording normalizes every exchange's URL path
        # to ``"/"`` so replay matching never depends on the real endpoint's
        # path; using the real URL here would defeat that by giving the
        # replayed request a different, real path. The placeholder is
        # syntactically valid but resolves nowhere -- httpx needs an absolute
        # URL to build a request even when a mock transport intercepts it and
        # no DNS lookup or connection is ever attempted. ``preflight`` already
        # refused an unset URL for a genuine live run.
        rpc_url = (
            "https://replay.invalid" if client is not None else settings.evm_rpc_url(network_key)
        )
        return EvmRpcAdapter(
            rpc_url or "https://replay.invalid",
            network_key=network_key,
            client=client,
            recorder=recorder,
            max_requests=max_requests,
            block_resolution_policy=block_resolution_policy,
        )
    raise LiveValidationError(f"no live adapter is configured for network {network_key!r}")


async def run_validation(
    settings: Settings,
    request: ValidationRequest,
    *,
    out_root: Path,
    replay_from: Path | None = None,
) -> ValidationRun:
    """Run the validation and write the bundle. Raises rather than half-reporting."""
    replaying = replay_from is not None
    if not replaying:
        preflight(settings, request.network_key)
    elif settings.data_mode is DataMode.LIVE:
        raise LiveValidationError("a replay is not a live run; set CFA_DATA_MODE=RECORDED_PUBLIC")

    run_id = request.run_id or (
        dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
    )
    directory = out_root / run_id
    directory.mkdir(parents=True, exist_ok=True)
    started_at = dt.datetime.now(dt.UTC)
    run = ValidationRun(run_id=run_id, directory=directory, status="running", started_at=started_at)

    recorder = BundleRecorder(directory / "raw") if not replaying else None
    client = replay_client(replay_from) if replay_from is not None else None
    adapter = _build_adapter(
        settings,
        request.network_key,
        client=client,
        recorder=recorder,
        max_requests=request.max_requests,
        block_resolution_policy=request.block_resolution_policy,
    )
    asset = AssetRef(
        network_key=request.network_key,
        token_contract=request.token_contract,
        decimals=request.asset_decimals,
        display_symbol=request.asset_symbol,
    )
    cutoff = request.analysis_cutoff or settings.cutoff

    try:
        if isinstance(adapter, EvmRpcAdapter) and request.verify_token:
            await _verify_token(adapter, request, directory, replaying=replaying)
        labels = load_labels(settings)
        result = await run_trace(
            settings,
            seed_address=request.address,
            asset=asset,
            seed_event_reference=request.seed_event_reference,
            analysis_cutoff=cutoff,
            analysis_start=request.analysis_start,
            adapter=adapter,
            case_flow_linkage=(
                CaseFlowLinkage.established
                if request.seed_event_reference
                else CaseFlowLinkage.not_established
            ),
        )
        result.limitations.extend(
            _report_limitations(result, analysis_start=request.analysis_start)
        )
        verification = await _verify(adapter, result)
        _apply_receipt_statuses(result, verification)
        _reject_incomplete(result)
    except (ProviderError, TraceUnavailable, LiveValidationError) as exc:
        run.status = "failed"
        detail = f"{exc.error_class.value}: " if isinstance(exc, ProviderError) else ""
        run.failure = f"{type(exc).__name__}: {detail}{exc}"
        run.finished_at = dt.datetime.now(dt.UTC)
        run.exchanges = recorder.count if recorder else 0
        _write_manifest(run, settings, request, adapter=adapter, replaying=replaying)
        raise LiveValidationError(
            f"validation {run_id} failed and was not completed: {run.failure}. "
            f"Partial evidence is in {directory}"
        ) from exc

    payload = result.to_json()
    run.trace = payload
    run.receipts = verification
    run.exchanges = (
        recorder.count if recorder else len(load_recordings(replay_from or directory / "raw"))
    )

    _write(directory / "trace.json", payload)
    _write(directory / "normalized-transfers.json", payload["observed_transfers"])
    _write(directory / "receipts.json", verification)
    _write(directory / "accepted-label-snapshot.json", _label_snapshot(labels, payload))
    (directory / "report.html").write_text(render_evidence_html(payload, request_id=run_id))

    run.status = "succeeded"
    run.finished_at = dt.datetime.now(dt.UTC)
    _write_manifest(run, settings, request, adapter=adapter, replaying=replaying)
    return run


def _report_limitations(
    result: TraceResult, *, analysis_start: dt.datetime | None
) -> list[Limitation]:
    """Honest bounds on what a clean, complete run still does not claim.

    Distinct from a tracer-recorded ``Limitation`` (a walk-time failure): these
    describe what this run's own accepted labels and scope actually mean, so a
    reader does not read ``coverage: complete_within_scope`` as ``coverage:
    complete``. Every fact here already exists somewhere in ``result``; this
    only makes it visible in the section meant to hold it.
    """
    found: list[Limitation] = []
    seen: set[tuple[str, str | None]] = set()

    def add(code: str, message: str, *, address: str | None = None) -> None:
        key = (code, address)
        if key in seen:
            return
        seen.add(key)
        found.append(Limitation(code=code, message=message, address=address))

    has_observed_amount = False
    for ending in result.branch_endings:
        if ending.observed_amount_base_units is not None:
            has_observed_amount = True
        label = ending.label
        if label is None:
            continue
        if label.valid_from and label.valid_to and label.valid_from == label.valid_to:
            add(
                "snapshot_only_label",
                f"{label.entity_name}'s claim over {ending.address} is scoped to a "
                f"single instant ({label.valid_from}), not a period of continuing "
                "control.",
                address=ending.address,
            )
        if label.address_role == "unknown":
            add(
                "address_role_unknown",
                f"{ending.address}'s role under {label.entity_name} is not "
                "established beyond service control -- not confirmed as a customer "
                "deposit address, hot wallet, or cold reserve.",
                address=ending.address,
            )

    if has_observed_amount:
        add(
            "allocation_unknown",
            "The observed amount is the transfer's own value, not an allocation to "
            "any specific case or claimant. An observed path is a sequence of "
            "transfers, not ownership of fungible units.",
        )

    window = (
        f"{analysis_start.isoformat()} to {result.analysis_cutoff.isoformat()}"
        if analysis_start is not None
        else f"up to {result.analysis_cutoff.isoformat()}"
    )
    add(
        "bounded_analysis_window",
        f"Analysed {window} only -- not the account's full history before or after it.",
    )
    network = EVM_NETWORKS.get(result.network_key)
    add(
        "single_validation_case",
        "One public-chain validation case, chosen to demonstrate the pipeline end "
        "to end. Not a general coverage claim about this address, this entity, or "
        f"{network.display_name if network else 'TRON'} activity broadly.",
    )
    return found


async def _verify_token(
    adapter: EvmRpcAdapter, request: ValidationRequest, directory: Path, *, replaying: bool
) -> None:
    """Read-only token contract checks, saved whether or not they pass.

    They run through the same recording adapter as the trace, so a replay
    re-derives them from ``raw/`` rather than copying the LIVE file. They are
    technical facts only; issuer provenance is a separate, documented claim.
    """
    facts = await adapter.verify_token_contract(request.token_contract)
    facts["requested_decimals"] = request.asset_decimals
    facts["requested_display_symbol"] = request.asset_symbol
    facts["replayed_from_recorded_exchanges"] = replaying
    _write(directory / "token-verification.json", facts)
    if not facts["code_present"]:
        raise LiveValidationError(
            f"no contract code at {facts['contract']} on {adapter.network_key}; "
            "refusing to trace a token that is not deployed on this network"
        )
    if facts["decimals"] != request.asset_decimals:
        raise LiveValidationError(
            f"on-chain decimals() is {facts['decimals']!r} but the run was configured "
            f"with decimals={request.asset_decimals}; refusing to format amounts wrongly"
        )


def _reject_incomplete(result: TraceResult) -> None:
    """A validation that could not read part of the chain did not validate it.

    The tracer is right to record a provider failure as a boundary and carry on
    — a partial trace is still evidence. A validation run is a different claim,
    so it fails here rather than presenting an incomplete walk as a clean one.
    """
    failed = [
        ending
        for ending in result.branch_endings
        if ending.boundary_reason is BoundaryReason.provider_failure
    ]
    if failed:
        addresses = ", ".join(sorted({ending.address for ending in failed}))
        raise LiveValidationError(
            f"the trace could not read onward activity for {addresses}; "
            "recording an incomplete walk rather than reporting it as complete"
        )


async def _verify(adapter: ReceiptVerifiable, result: TraceResult) -> dict[str, Any]:
    """Establish execution and finality for the transactions this trace used.

    One receipt per transaction, not per event. A transfer whose receipt could
    not be read is listed rather than assumed to have succeeded.
    """
    #: The seed event is an input to the trace rather than something the walk
    #: discovered, so it is not in ``observed_transfers`` — and for a direct
    #: A → anchor case it is the only transfer there is. Verify it too.
    seed_tx = (
        adapter.tx_hash_from_reference(result.seed_event_reference)
        if result.seed_event_reference
        else None
    )
    tx_hashes = [t.tx_hash for t in result.observed_transfers]
    if seed_tx:
        tx_hashes.insert(0, seed_tx)
    if not tx_hashes:
        return {"receipts": {}, "unverified": [], "note": "no transfer was observed to verify"}

    receipts, failures = await adapter.fetch_receipts(tx_hashes)
    unverified = []
    for transfer in result.observed_transfers:
        receipt = receipts.get(transfer.tx_hash)
        if receipt is None:
            reason = failures.get(transfer.tx_hash, "no receipt was fetched")
        elif receipt.execution_status is ExecutionStatus.unknown:
            reason = receipt.note
        else:
            continue
        unverified.append(
            {
                "event_reference": transfer.event_reference,
                "tx_hash": transfer.tx_hash,
                "reason": reason,
            }
        )
    if seed_tx and seed_tx not in receipts:
        unverified.append(
            {
                "event_reference": result.seed_event_reference or seed_tx,
                "tx_hash": seed_tx,
                "reason": failures.get(seed_tx, "no receipt was fetched for the seed event"),
            }
        )
    return {
        "receipts": {tx: receipt.to_json() for tx, receipt in receipts.items()},
        "seed_transaction": seed_tx,
        "failures": failures,
        "unverified": unverified,
        "note": (
            "Execution status comes from the receipt endpoints, not from the history "
            "endpoint, which documents none. Confirmation is separate: only a "
            "solidified receipt reports confirmed."
        ),
    }


def _apply_receipt_statuses(result: TraceResult, verification: dict[str, Any]) -> None:
    """Reflect receipt-backed status in the trace consumed by investigators.

    History/event endpoints do not establish execution or finality, so the
    tracer initially records those axes as unknown. The receipt bundle is the
    source of truth; copy its values into both the seed transfer and onward
    transfers before serialising ``trace.json`` and the report.
    """
    receipts = verification.get("receipts", {})

    def verified(transfer: Any) -> Any:
        receipt = receipts.get(transfer.tx_hash)
        if receipt is None:
            return transfer
        return replace(
            transfer,
            execution_status=receipt["execution_status"],
            confirmation_state=receipt["confirmation_state"],
        )

    if result.seed_transfer is not None:
        result.seed_transfer = verified(result.seed_transfer)
    result.observed_transfers = [verified(transfer) for transfer in result.observed_transfers]


def _label_snapshot(labels: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """The claims this run had available, and the ones it actually used."""
    used = [
        {"address": b["address"], "label": b["label"]}
        for b in payload["branch_endings"]
        if b.get("label")
    ]
    return {"registry": labels.snapshot(), "claims_used": used}


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _network_configuration(
    settings: Settings, request: ValidationRequest, adapter: TronGridAdapter | EvmRpcAdapter
) -> dict[str, Any]:
    """Network-specific configuration facts. Never a secret: a TRON key is
    reported only as configured/not, and an EVM RPC URL (which may embed a
    provider API key) is never included at all -- only the chain id it
    reported (constraint 3), which carries no secret."""
    if isinstance(adapter, TronGridAdapter):
        return {
            "tron_api_base": settings.tron_api_base,
            # Never the key itself, and never a prefix of it.
            "tron_api_key_configured": bool(settings.tron_api_key),
        }
    config = EVM_NETWORKS[adapter.network_key]
    return {
        "network": adapter.network_key,
        "caip2": config.caip2,
        f"{adapter.network_key}_rpc_configured": bool(settings.evm_rpc_url(adapter.network_key)),
        "expected_chain_id": adapter.chain_id,
        "observed_chain_id": adapter.observed_chain_id,
        "finality_note": config.finality_note,
        "evm_block_resolution_policy": adapter.block_resolution_policy,
    }


def _acquisition_stats(adapter: TronGridAdapter | EvmRpcAdapter) -> dict[str, Any]:
    """What the run actually sent, beyond the exchanges it could record.

    ``provider_exchanges`` counts recorded responses only; a request that
    failed at the HTTP level (for example an ``eth_getLogs`` span over the
    provider's limit) is never recorded. A replay reissues the same request
    sequence -- an unrecorded request misses the same way it failed live -- so
    these figures reproduce under replay.
    """
    stats: dict[str, Any] = {"provider_requests_issued": adapter.request_count}
    if isinstance(adapter, EvmRpcAdapter):
        stats["log_range_splits"] = adapter.log_range_splits
        stats["incomplete_log_ranges"] = [list(r) for r in adapter.incomplete_ranges]
    return stats


def _write_manifest(
    run: ValidationRun,
    settings: Settings,
    request: ValidationRequest,
    *,
    adapter: TronGridAdapter | EvmRpcAdapter,
    replaying: bool,
) -> None:
    files = {
        str(p.relative_to(run.directory)): _digest(p)
        for p in sorted(run.directory.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "run_id": run.run_id,
        "status": run.status,
        "failure": run.failure,
        "mode": "replay" if replaying else "live",
        "data_mode": settings.data_mode.value,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "query": {
            "network": request.network_key,
            "address": request.address,
            "token_contract": request.token_contract,
            "seed_event_reference": request.seed_event_reference,
            "analysis_start": (
                request.analysis_start.isoformat() if request.analysis_start else None
            ),
            "analysis_cutoff": (
                request.analysis_cutoff.isoformat() if request.analysis_cutoff else None
            ),
        },
        "versions": {
            "engine": settings.engine_version,
            "parser": settings.parser_version,
            "label_set": settings.label_set_version,
        },
        "configuration": {
            **_network_configuration(settings, request, adapter),
            "label_source": settings.effective_label_source.value,
            "label_dir": str(settings.label_directory),
            "budgets": {
                "max_hops": settings.budget_max_hops,
                "max_events": settings.budget_max_events,
                "max_provider_requests": settings.budget_max_provider_requests,
            },
            #: The narrower, per-run acquisition cap this instruction added
            #: (C) -- separate from the tracer's own hop-loop budget above,
            #: and enforced at the adapter's request boundary, not here.
            "acquisition_max_requests": request.max_requests,
        },
        "provider_exchanges": run.exchanges,
        "acquisition_stats": _acquisition_stats(adapter),
        "files": files,
        "caveat": (
            "A hash establishes that these files have not changed since the run. "
            "It does not establish that the attribution is correct."
        ),
    }
    (run.directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
