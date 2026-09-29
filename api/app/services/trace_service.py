"""Assemble a tracer for the current data mode and run it.

This is the only place that decides which adapter serves a request. The decision
is made from settings, not from a caller-supplied flag, so a demo cannot ask for
live data and a live deployment cannot be handed a fixture (D009).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from app.adapters.base import AssetRef, ChainAdapter, Direction, NormalizedTransfer
from app.adapters.evm import EVM_NETWORKS, EvmRpcAdapter
from app.adapters.fixture import FixtureAdapter
from app.adapters.tron import TronGridAdapter
from app.core.settings import DataMode, LabelSource, Settings
from app.engine.result import TraceResult
from app.engine.tracer import ChronologicalTracer
from app.models.enums import CaseFlowLinkage, CoverageStatus
from app.engine.result import Limitation
from app.adapters.receipt_gate import ReceiptGateAdapter
from app.services.labels import LabelRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
ANCHORS_CSV = REPO_ROOT / "data" / "anchors.csv"
DEFAULT_FIXTURE = REPO_ROOT / "fixtures" / "tron_synthetic_case_alpha.json"


class TraceUnavailable(RuntimeError):
    """The configured mode cannot be served, and we will not substitute another."""


def build_adapter(
    settings: Settings, *, network_key: str = "tron", fixture_path: Path | None = None
) -> ChainAdapter:
    """The one place that decides which adapter serves ``network_key`` (D009).

    The default is TRON, unchanged from before this network parameter existed,
    so every existing caller that does not pass one keeps its current behavior.
    """
    if settings.data_mode is DataMode.LIVE:
        if network_key == "tron":
            if not settings.tron_api_key:
                # Better to refuse than to run unauthenticated and read a quota
                # error as an empty history.
                raise TraceUnavailable(
                    "CFA_DATA_MODE=LIVE but no CFA_TRON_API_KEY is configured; "
                    "live tracing is disabled rather than run unauthenticated"
                )
            return TronGridAdapter(settings.tron_api_base, api_key=settings.tron_api_key,
                                   max_requests=settings.budget_max_provider_requests)
        if network_key in EVM_NETWORKS:
            rpc_url = settings.evm_rpc_url(network_key)
            if not rpc_url:
                raise TraceUnavailable(
                    f"CFA_DATA_MODE=LIVE but no {EVM_NETWORKS[network_key].rpc_env_var} is "
                    f"configured for network {network_key!r}; not silently choosing a public "
                    "endpoint, and never another network's"
                )
            return EvmRpcAdapter(rpc_url, network_key=network_key,
                                 max_requests=settings.budget_max_provider_requests)
        raise TraceUnavailable(f"no live adapter is configured for network {network_key!r}")
    if network_key != "tron" and fixture_path is None:
        raise TraceUnavailable(
            f"no default fixture is defined for network {network_key!r}; pass fixture_path"
        )
    return FixtureAdapter(fixture_path or DEFAULT_FIXTURE, network_key=network_key)


def load_labels(settings: Settings, *, labels_path: Path | None = None) -> LabelRegistry:
    """The one place a label set is chosen, for the API and the CLI alike.

    A live trace reads the reviewed sets or it does not run. Falling back to
    ``anchors.csv`` would put fictional entity names on real chain observations,
    and a fallback that happens silently is worse than a refusal (D019).
    """
    if labels_path is not None:
        return LabelRegistry.from_csv(labels_path, source="explicit_path")

    if settings.effective_label_source is LabelSource.synthetic_fixture:
        if settings.data_mode is DataMode.LIVE:
            raise TraceUnavailable(
                "live tracing refuses the synthetic label set; import and review a "
                "sourced anchor first"
            )
        return LabelRegistry.from_csv(ANCHORS_CSV, source="synthetic_fixture")

    registry = LabelRegistry.from_reviewed_sets(settings.label_directory)
    if settings.data_mode is DataMode.LIVE and registry.accepted_service_claim_count == 0:
        raise TraceUnavailable(
            f"no accepted service claim in {settings.label_directory}; run "
            "scripts/import_anchors.py then scripts/review_candidates.py. "
            "Refusing to fall back to the synthetic label set"
        )
    return registry


async def run_trace(
    settings: Settings,
    *,
    seed_address: str,
    asset: AssetRef,
    seed_event_reference: str | None = None,
    analysis_cutoff: dt.datetime | None = None,
    analysis_start: dt.datetime | None = None,
    fixture_path: Path | None = None,
    labels_path: Path | None = None,
    #: Supplied by the live-validation harness, which needs the same adapter for
    #: the trace and the receipt pass so one recording covers both.
    adapter: ChainAdapter | None = None,
    case_flow_linkage: CaseFlowLinkage = CaseFlowLinkage.established,
) -> TraceResult:
    adapter = adapter or build_adapter(
        settings, network_key=asset.network_key, fixture_path=fixture_path
    )
    if isinstance(adapter, (TronGridAdapter, EvmRpcAdapter)):
        adapter = ReceiptGateAdapter(adapter)
    labels = load_labels(settings, labels_path=labels_path)
    cutoff = analysis_cutoff or settings.cutoff
    tracer = ChronologicalTracer(adapter, labels, settings)

    seed_event: NormalizedTransfer | None = None
    if seed_event_reference:
        seed_event = await _find_seed_event(
            adapter, seed_address, asset, cutoff, seed_event_reference, start=analysis_start
        )
        if seed_event is None:
            window = f"from {analysis_start.isoformat()} " if analysis_start is not None else ""
            raise TraceUnavailable(
                f"seed event {seed_event_reference!r} was not found in the outgoing "
                f"history of {seed_address}, searched {window}up to {cutoff.isoformat()}. "
                "Not restarting from account genesis or widening the window silently."
            )

    result = await tracer.trace(
        seed_address=seed_address,
        asset=asset,
        analysis_cutoff=cutoff,
        analysis_start=analysis_start,
        seed_event=seed_event,
        case_flow_linkage=case_flow_linkage,
    )
    if isinstance(adapter, ReceiptGateAdapter):
        def serializable(value):
            return value.isoformat() if isinstance(value, dt.datetime) else str(value)
        result.acquisitions.extend(json.loads(json.dumps(adapter.acquisitions, default=serializable)))
        # Store the receipt evidence alongside its acquisition provenance;
        # no signed transaction or provider credential is ever stored here.
        if adapter.receipts or adapter.unverified:
            result.acquisitions.append({"kind": "execution_verification",
                "receipts": adapter.receipts, "unverified": adapter.unverified})
        for message in sorted(set(adapter.coverage_gaps)):
            result.limitations.append(Limitation(code="provider_incomplete_coverage", message=message))
            if result.coverage_status is CoverageStatus.complete_within_scope:
                result.coverage_status = CoverageStatus.partial
    return result


async def _find_seed_event(
    adapter: ChainAdapter,
    address: str,
    asset: AssetRef,
    cutoff: dt.datetime,
    event_reference: str,
    *,
    start: dt.datetime | None = None,
) -> NormalizedTransfer | None:
    """Locate the specific transfer the complaint names.

    A transaction can hold several transfers, so the caller names an event, not a
    transaction hash (D005).

    When the adapter can read a transaction id back out of ``event_reference``
    (``tx_hash_from_reference``), pages are fetched without per-transaction
    enrichment and matched by that id first -- cheap, and on its own not
    trustworthy -- then reconciled against decoded event detail through
    ``resolve_seed_event``, which is the only per-transaction enrichment this
    search pays for. An adapter that cannot read a transaction id back out of
    its own reference format falls back to the original full-enrichment scan,
    so this stays correct for any ``ChainAdapter``, not just TRON.
    """
    target_tx = adapter.tx_hash_from_reference(event_reference)
    cursor: str | None = None
    while True:
        page = await adapter.fetch_transfers(
            address=address,
            asset=asset,
            direction=Direction.outgoing,
            analysis_cutoff=cutoff,
            analysis_start=start,
            cursor=cursor,
            enrich=False if target_tx is not None else None,
        )
        for event in page.events:
            if target_tx is None:
                if event.event_reference == event_reference:
                    return event
                continue
            if event.tx_hash != target_tx:
                continue
            resolved = await adapter.resolve_seed_event(event, asset)
            if resolved is not None and resolved.event_reference == event_reference:
                return resolved
            # Matched the transaction id but not (yet) this specific event --
            # another row in this same page may be the one actually named
            # (distinct events within one transaction stay distinct, D005).
        cursor = page.next_cursor
        if not cursor:
            return None
