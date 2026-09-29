"""Bounded discovery runner and replay for VASP-neighborhood reports."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.adapters.base import (
    AssetRef,
    Direction,
    NormalizedTransfer,
    ProviderError,
    ProviderErrorClass,
)
from app.adapters.tron import TronGridAdapter
from app.core.settings import DataMode, Settings
from app.models.enums import AssertionType, ReviewState
from app.services.labels import LabelRegistry
from app.services.live_validation import BundleRecorder, load_recordings, replay_client
from app.services.vasp_neighborhood import (
    NeighborhoodCoverage,
    NeighborhoodObservation,
    NeighborhoodRequest,
    NeighborhoodResult,
    generate_neighborhood,
)


class NeighborhoodDiscoveryError(RuntimeError):
    """The bounded evidence acquisition or replay could not be completed."""


@dataclass(frozen=True)
class DiscoveryRun:
    run_id: str
    directory: Path
    result: NeighborhoodResult
    requests_used: int
    raw_exchange_count: int
    replayed: bool


def _anchor_from_registry(data_dir: Path, network: str, address: str):
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    anchors = [
        anchor
        for anchor in registry.lookup(network, address)
        if anchor.assertion_type is AssertionType.service_control
        and anchor.review_state is ReviewState.accepted
    ]
    if not anchors:
        raise NeighborhoodDiscoveryError("anchor is not an accepted service_control claim")
    return anchors[0]


def _observation(event: NormalizedTransfer, direction: Direction) -> NeighborhoodObservation:
    if event.from_address is None or event.to_address is None or event.block_time is None:
        raise NeighborhoodDiscoveryError("transfer lacks address or timestamp evidence")
    return NeighborhoodObservation(
        network=event.asset.network_key,
        token_contract=event.asset.token_contract or "",
        event_reference=event.event_reference,
        tx_hash=event.tx_hash,
        event_index=event.event_index,
        source_address=event.from_address,
        target_address=event.to_address,
        amount_base_units=event.amount_base_units,
        block_time=event.block_time,
        execution_status=event.execution_status.value,
        confirmation_state=event.confirmation_state.value,
        ordering_ambiguous=event.ordering_ambiguous,
        direction=direction.value,
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bundle(
    *,
    directory: Path,
    result: NeighborhoodResult,
    request: NeighborhoodRequest,
    settings: Settings,
    requests_used: int,
    raw_exchange_count: int,
    replayed: bool,
    started_at: dt.datetime,
) -> None:
    report_path = directory / "report.json"
    report_path.write_text(json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n")
    artifacts = {
        path.relative_to(directory).as_posix(): _digest(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = {
        "report_type": "vasp_candidate_neighborhood",
        "policy_version": result.policy_version,
        "run_id": directory.name,
        "status": "succeeded" if result.coverage.complete else "partial",
        "mode": "replay" if replayed else "live",
        "data_mode": settings.data_mode.value,
        "started_at": started_at.isoformat(),
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "query": {
            "network": request.network,
            "anchor_address": request.anchor_address,
            "token_contract": request.token_contract,
            "window_start": request.window_start.isoformat(),
            "window_end": request.window_end.isoformat(),
            "max_requests": request.max_requests,
            "page_limit": request.page_limit,
            "pages_per_address": request.pages_per_address,
            "event_limit": request.event_limit,
            "address_limit": request.address_limit,
            "verify_execution": request.verify_execution,
            "enrich_events": request.enrich_events,
        },
        "provider_requests": requests_used,
        "raw_exchange_count": raw_exchange_count,
        "candidate_count": len(result.candidates),
        "coverage_complete": result.coverage.complete,
        "configuration": {
            "tron_api_base": settings.tron_api_base,
            "tron_api_key_configured": bool(settings.tron_api_key),
            "data_mode": settings.data_mode.value,
        },
        "files": artifacts,
        "caveat": (
            "Candidate relationships are deterministic research leads only. They do not "
            "establish service ownership, customer-deposit role, common control, fraud, "
            "or unique fund ownership. SHA-256 hashes establish file consistency only."
        ),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


async def run_discovery(
    settings: Settings,
    request: NeighborhoodRequest,
    *,
    out_root: Path,
    data_dir: Path,
    replay_from: Path | None = None,
) -> DiscoveryRun:
    started_at = dt.datetime.now(dt.UTC)
    replayed = replay_from is not None
    if request.network != "tron":
        raise NeighborhoodDiscoveryError("only TRON is supported")
    if settings.data_mode is DataMode.SYNTHETIC:
        raise NeighborhoodDiscoveryError("synthetic mode cannot run public neighborhood discovery")
    if not replayed and settings.data_mode is not DataMode.LIVE:
        raise NeighborhoodDiscoveryError("live discovery requires CFA_DATA_MODE=LIVE")
    if not replayed and not settings.tron_api_key:
        raise NeighborhoodDiscoveryError("live discovery requires CFA_TRON_API_KEY")
    if replayed and settings.data_mode is not DataMode.RECORDED_PUBLIC:
        raise NeighborhoodDiscoveryError("replay requires CFA_DATA_MODE=RECORDED_PUBLIC")

    anchor = _anchor_from_registry(data_dir, request.network, request.anchor_address)
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
    directory = out_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    raw_dir = directory / "raw"
    recorder = None if replayed else BundleRecorder(raw_dir)
    if replay_from is not None:
        replay_source = replay_from / "raw"
        try:
            replay_record_count = len(load_recordings(replay_source))
            replay_client_instance = replay_client(replay_source)
        except (OSError, ValueError, RuntimeError) as exc:
            raise NeighborhoodDiscoveryError(
                f"cannot replay saved provider evidence: {exc}"
            ) from exc
    else:
        replay_record_count = 0
        replay_client_instance = None
    adapter = TronGridAdapter(
        settings.tron_api_base,
        api_key=settings.tron_api_key,
        client=replay_client_instance,
        recorder=recorder,
        max_requests=request.max_requests,
        enrich_events=False,
    )
    asset = AssetRef("tron", request.token_contract, 6, "USDT")
    observations: list[NeighborhoodObservation] = []
    pages_used = 0
    addresses_examined: set[str] = set()
    limits_hit: list[str] = []
    exhausted = False

    async def collect_direction(address: str, direction: Direction, page_cap: int) -> bool:
        nonlocal pages_used
        cursor: str | None = None
        kept = 0
        page_count = 0
        while page_count < page_cap and kept < request.event_limit:
            if adapter.request_count >= request.max_requests:
                raise ProviderError(
                    ProviderErrorClass.budget_exhausted,
                    "provider request budget exhausted before the next bounded history page",
                )
            page = await adapter.fetch_transfers(
                address=address,
                asset=asset,
                direction=direction,
                analysis_start=request.window_start,
                analysis_cutoff=request.window_end,
                cursor=cursor,
                limit=min(200, request.event_limit - kept),
                enrich=False,
            )
            pages_used += 1
            page_count += 1
            events = page.events
            if request.enrich_events:
                resolved = []
                for event in events:
                    with_index = await adapter.resolve_seed_event(event, asset)
                    resolved.append(with_index or event)
                events = resolved
            if request.verify_execution:
                events = (await adapter.verify_execution(events)).events
            observations.extend(_observation(event, direction) for event in events)
            kept += len(events)
            cursor = page.next_cursor
            if not cursor:
                return False
        if cursor:
            limits_hit.append(
                f"{direction.value} history for {address} hit its page/event budget"
            )
            return True
        return False

    try:
        exhausted = await collect_direction(
            request.anchor_address, Direction.incoming, request.page_limit
        )
        all_candidate_addresses = sorted(
            {
                observation.source_address
                for observation in observations
                if observation.target_address == request.anchor_address
                and anchor.covers(observation.block_time)
            }
        )
        candidate_addresses = all_candidate_addresses[: request.address_limit]
        if len(all_candidate_addresses) > request.address_limit:
            limits_hit.append("maximum distinct source-address limit reached")
            exhausted = True
        for address in candidate_addresses:
            addresses_examined.add(address)
            exhausted = (
                await collect_direction(address, Direction.incoming, request.pages_per_address)
                or exhausted
            )
            exhausted = (
                await collect_direction(address, Direction.outgoing, request.pages_per_address)
                or exhausted
            )
    except ProviderError as exc:
        if exc.error_class is ProviderErrorClass.budget_exhausted:
            limits_hit.append(
                "provider request budget exhausted; remaining history is unknown"
            )
        else:
            limits_hit.append(
                f"provider failure ({exc.error_class.value}); history is unknown: {exc}"
            )
        exhausted = True
    finally:
        if replay_client_instance is not None:
            await replay_client_instance.aclose()

    addresses = sorted(addresses_examined)

    coverage = NeighborhoodCoverage(
        complete=not exhausted,
        window_start=request.window_start,
        window_end=request.window_end,
        requests_used=0 if replayed else adapter.request_count,
        max_requests=request.max_requests,
        page_limit=request.page_limit,
        pages_used=pages_used,
        address_limit=request.address_limit,
        pages_per_address=request.pages_per_address,
        addresses_examined=min(len(addresses), request.address_limit),
        limitations=tuple(limits_hit),
    )
    result = generate_neighborhood(
        anchor=anchor,
        network=request.network,
        token_contract=request.token_contract,
        observations=observations,
        coverage=coverage,
    )
    _write_bundle(
        directory=directory,
        result=result,
        request=request,
        settings=settings,
        requests_used=0 if replayed else adapter.request_count,
        raw_exchange_count=recorder.count if recorder else replay_record_count,
        replayed=replayed,
        started_at=started_at,
    )
    return DiscoveryRun(
        run_id=run_id,
        directory=directory,
        result=result,
        requests_used=0 if replayed else adapter.request_count,
        raw_exchange_count=recorder.count if recorder else replay_record_count,
        replayed=replayed,
    )
