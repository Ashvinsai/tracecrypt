"""Stage 2C: candidate deposit-address leads, from one accepted anchor's own
incoming history.

A candidate D is a sender who transferred the verified token to an
already-accepted anchor H within a bounded window. That is a behavioural
observation, not a claim of exchange ownership or a customer relationship:
"Candidate D addresses are senders to H, not automatically exchange
deposits" (FIVE_STAGE_PLAN.md, Stage 2C). This module never writes
verified_anchors.csv. Every candidate row lands in deposit_candidates.csv
with ``assertion_type=deposit_candidate`` and ``address_role=unknown``, and
``anchor_import._route`` makes it structurally impossible for that
assertion type to reach the verified set -- promotion to a verified anchor
is a separate, human review decision (Stage 2's own boundary), never
automatic here.

Bounded by construction, the same way Stage 1's seed search is bounded:

- one already-accepted anchor (refused otherwise -- an unreviewed or
  rejected address is not a base to search from);
- one verified token contract;
- one time window (``analysis_start``/``analysis_cutoff``, the anchor's own
  documented ``min_timestamp``/``max_timestamp`` query parameters, not a
  client-side filter over a wider page);
- a maximum number of distinct candidate senders (``candidate_limit`` --
  "select a manageable sample before looking at outcomes");
- a request budget enforced at the adapter's own request boundary
  (``max_requests``, the same guard Stage 1 added).

Every raw acquisition response is saved (via the same ``BundleRecorder``
Stage 1's live-validation bundle uses) before any candidate row is written.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.adapters.base import AssetRef, Direction, ProviderError, ProviderErrorClass
from app.adapters.tron import TronGridAdapter
from app.core.settings import Settings
from app.models.enums import AddressRole, AssertionType, ReviewState
from app.services.anchor_import import (
    AnchorImportError,
    DisclosureKind,
    ImportReport,
    SourceDocument,
    import_anchors,
)
from app.services.labels import Anchor, LabelRegistry
from app.services.live_validation import BundleRecorder

CANDIDATE_COLUMNS = "network,address,entity_name,entity_type,assertion_type,address_role\n"
#: A candidate's own entity is never established by this module -- only that
#: it sent value to the anchor. Writing the anchor's entity here would read
#: as an ownership claim for the candidate; it is not one.
UNKNOWN_ENTITY_NAME = "unknown"
UNKNOWN_ENTITY_TYPE = "unknown"


class CandidateCollectionError(RuntimeError):
    """The collection cannot proceed, or did not finish cleanly. Never a silent skip."""


@dataclass(frozen=True)
class CollectionRequest:
    anchor_address: str
    token_contract: str
    network_key: str = "tron"
    asset_decimals: int = 6
    asset_symbol: str = "USDT"
    analysis_start: dt.datetime | None = None
    analysis_cutoff: dt.datetime | None = None
    #: "Select a manageable sample before looking at outcomes and record
    #: selection bias and truncation" -- Stage 2C.
    candidate_limit: int = 50
    max_requests: int | None = None
    run_id: str | None = None


@dataclass
class CollectionRun:
    run_id: str
    directory: Path
    anchor_address: str
    anchor_entity_name: str
    #: When the acquisition itself ran -- the real network activity window,
    #: never overwritten by a later manifest backfill (B).
    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    finished_at: dt.datetime | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    #: Transfers actually observed within the acquisition window whose sender
    #: was NOT made a candidate, because the accepted anchor claim did not
    #: cover that transfer's own timestamp. Recorded so the searched scope is
    #: honest even when it found nothing usable (requirement 5).
    ineligible_events: list[dict[str, Any]] = field(default_factory=list)
    requests_used: int = 0
    truncated_by_candidate_limit: bool = False
    truncated_by_request_budget: bool = False
    import_report: ImportReport | None = None
    written: bool = False


def _require_accepted_anchor(registry: LabelRegistry, network_key: str, address: str) -> Anchor:
    """A coarse gate only: there must be *an* accepted claim to search from at
    all. It does not establish that any particular transfer falls inside that
    claim's covered instant -- that is checked per event, below, the same way
    the tracer checks it (``LabelRegistry.terminating_anchor``), because an
    accepted claim can still be temporally inapplicable to a given transfer.
    """
    matches = [
        a for a in registry.lookup(network_key, address) if a.review_state == ReviewState.accepted
    ]
    if not matches:
        raise CandidateCollectionError(
            f"{address} on {network_key} has no accepted claim; collection "
            "starts from an accepted anchor only, not an unreviewed or "
            "rejected one"
        )
    return matches[0]


async def collect_candidates(
    settings: Settings,
    request: CollectionRequest,
    *,
    out_root: Path,
    data_dir: Path,
    write: bool = False,
) -> CollectionRun:
    """Find senders to an accepted anchor, save the raw evidence, prepare leads.

    ``write=False`` (the default, mirroring ``import_anchors``) previews the
    candidates and writes the raw evidence bundle, but leaves
    ``deposit_candidates.csv`` untouched until a caller explicitly asks to
    write it.
    """
    started_at = dt.datetime.now(dt.UTC)
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    anchor = _require_accepted_anchor(registry, request.network_key, request.anchor_address)

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
        # A lead needs identity, amount and time -- not a resolved event
        # index. Skipping enrichment keeps every request spent on this
        # search actually widening the candidate set (Stage 1's lesson).
        enrich_events=False,
    )
    asset = AssetRef(
        network_key=request.network_key,
        token_contract=request.token_contract,
        decimals=request.asset_decimals,
        display_symbol=request.asset_symbol,
    )
    cutoff = request.analysis_cutoff or settings.cutoff

    senders: dict[str, dict[str, Any]] = {}
    ineligible_events: list[dict[str, Any]] = []
    cursor: str | None = None
    truncated_by_budget = False
    try:
        while len(senders) < request.candidate_limit:
            page = await adapter.fetch_transfers(
                address=request.anchor_address,
                asset=asset,
                direction=Direction.incoming,
                analysis_cutoff=cutoff,
                analysis_start=request.analysis_start,
                cursor=cursor,
            )
            for event in page.events:
                if event.from_address is None:
                    continue
                # The same check the tracer makes before treating a label as
                # applicable (LabelRegistry.terminating_anchor): an accepted
                # claim is not blanket cover for every moment, only the one
                # it actually states. A transfer outside that instant is
                # observed, but not attribution-linked to this anchor.
                terminating = (
                    registry.terminating_anchor(
                        request.network_key, request.anchor_address, event.block_time
                    )
                    if event.block_time is not None
                    else None
                )
                if terminating is None:
                    ineligible_events.append(
                        {
                            "candidate_address": event.from_address,
                            "tx_hash": event.tx_hash,
                            "event_reference": event.event_reference,
                            "amount_base_units": event.amount_base_units,
                            "block_time": (
                                event.block_time.isoformat() if event.block_time else None
                            ),
                            "reason": (
                                "no block_time available for this event"
                                if event.block_time is None
                                else "the accepted anchor claim does not cover this "
                                "transfer's own timestamp"
                            ),
                        }
                    )
                    continue
                if event.from_address in senders:
                    continue
                senders[event.from_address] = {
                    "tx_hash": event.tx_hash,
                    "event_reference": event.event_reference,
                    "amount_base_units": event.amount_base_units,
                    "block_time": event.block_time.isoformat() if event.block_time else None,
                }
                if len(senders) >= request.candidate_limit:
                    break
            cursor = page.next_cursor
            if not cursor:
                break
    except ProviderError as exc:
        if exc.error_class is ProviderErrorClass.budget_exhausted:
            # Preserve what was found; report the truncation honestly rather
            # than discarding a partial, genuine sample (T3's spirit applied
            # to a budget boundary, not just a provider outage).
            truncated_by_budget = True
        else:
            raise CandidateCollectionError(
                f"collection for {request.anchor_address} failed: {exc}"
            ) from exc

    truncated_by_limit = len(senders) >= request.candidate_limit and cursor is not None

    run = CollectionRun(
        run_id=run_id,
        directory=directory,
        anchor_address=anchor.address,
        anchor_entity_name=anchor.entity_name,
        started_at=started_at,
        finished_at=dt.datetime.now(dt.UTC),
        candidates=[{"candidate_address": addr, **detail} for addr, detail in senders.items()],
        ineligible_events=ineligible_events,
        requests_used=adapter.request_count,
        truncated_by_candidate_limit=truncated_by_limit,
        truncated_by_request_budget=truncated_by_budget,
    )

    (directory / "candidates.json").write_text(
        json.dumps(
            {
                "anchor_address": anchor.address,
                "anchor_entity_name": anchor.entity_name,
                "anchor_valid_from": anchor.valid_from.isoformat() if anchor.valid_from else None,
                "anchor_valid_to": anchor.valid_to.isoformat() if anchor.valid_to else None,
                "token_contract": request.token_contract,
                "analysis_start": (
                    request.analysis_start.isoformat() if request.analysis_start else None
                ),
                "analysis_cutoff": cutoff.isoformat(),
                "candidate_limit": request.candidate_limit,
                "max_requests": request.max_requests,
                "requests_used": run.requests_used,
                "truncated_by_candidate_limit": run.truncated_by_candidate_limit,
                "truncated_by_request_budget": run.truncated_by_request_budget,
                "candidates": run.candidates,
                "ineligible_events": run.ineligible_events,
            },
            indent=2,
        )
    )

    if senders:
        selection_path = directory / "candidate-selection.csv"
        with selection_path.open("w", newline="") as fh:
            fh.write(CANDIDATE_COLUMNS)
            for addr in senders:
                # The candidate's own entity is not established -- "unknown",
                # never the anchor's entity. Which anchor this sender
                # transferred to is recorded separately, via
                # SourceDocument.anchor_address/anchor_entity_name below, so
                # a reader can never mistake "sent value to OKX's anchor" for
                # "is OKX".
                fh.write(
                    f"{request.network_key},{addr},{UNKNOWN_ENTITY_NAME},"
                    f"{UNKNOWN_ENTITY_TYPE},{AssertionType.deposit_candidate.value},"
                    f"{AddressRole.unknown.value}\n"
                )

        truncation_notes = []
        if run.truncated_by_candidate_limit:
            truncation_notes.append(
                "Truncated by the candidate limit before the window was fully searched."
            )
        if run.truncated_by_request_budget:
            truncation_notes.append(
                "Truncated by the request budget before the window was fully searched."
            )
        start_text = request.analysis_start.isoformat() if request.analysis_start else "unbounded"
        budget_text = (
            str(request.max_requests) if request.max_requests is not None else "an unbounded"
        )
        methodology = " ".join(
            [
                f"{len(senders)} distinct sender(s) of {request.token_contract} to the "
                f"accepted anchor {anchor.address} ({anchor.entity_name}), found by "
                "querying the anchor's own incoming history directly (not a per-sender "
                f"history search), within the acquisition window {start_text} to "
                f"{cutoff.isoformat()}, capped at {request.candidate_limit} candidates and "
                f"{budget_text} request(s) ({run.requests_used} actually used). The anchor "
                f"claim itself is applicable only "
                f"{anchor.valid_from.isoformat() if anchor.valid_from else '(open start)'} to "
                f"{anchor.valid_to.isoformat() if anchor.valid_to else '(open end)'}: "
                f"{len(ineligible_events)} transfer(s) inside the acquisition window were "
                "observed but fell outside that narrower claim and were not made "
                "candidates -- see ineligible_events in candidates.json.",
                *truncation_notes,
                "This establishes that each address sent value to the anchor while the "
                "anchor's own claim was applicable; it establishes nothing about who "
                "controls the sending address. Per-candidate transaction id, amount and "
                f"time are preserved in candidates.json alongside the raw provider "
                f"responses in {run_id}/raw/.",
            ]
        )

        document = SourceDocument(
            path=selection_path,
            url=f"tron:chain-observation:incoming-to:{anchor.address}",
            disclosure_kind=DisclosureKind.chain_observation,
            disclosure_date=dt.datetime.now(dt.UTC),
            retrieved_at=dt.datetime.now(dt.UTC),
            methodology=methodology,
            label_set_version=f"chain-observation-{run_id}",
            anchor_address=anchor.address,
            anchor_entity_name=anchor.entity_name,
        )
        try:
            run.import_report = import_anchors(
                document, network_key=request.network_key, out_dir=data_dir, write=write
            )
        except AnchorImportError as exc:
            raise CandidateCollectionError(str(exc)) from exc
        run.written = write and not run.import_report.rejections

    write_anchor_snapshot(directory, registry, anchor)
    write_manifest(run, settings, request)
    return run


@dataclass(frozen=True)
class Backfill:
    """Explicit provenance for evidence files written after the run they
    describe, from already-saved local data alone.

    A backfill can read everything the original run produced (it is already
    on disk), but nothing about what settings or network state the ORIGINAL
    process actually had -- that must be stated explicitly, never inferred
    from whatever happens to be ambient when the backfill runs. In
    particular, the backfill process itself makes zero network requests, so
    it must never be allowed to relabel a live run's own ``data_mode``
    (B: "data_mode=LIVE because it describes the original run, not the
    process that performed the local backfill").
    """

    original_data_mode: str
    note: str = (
        "Backfilled from already-saved local evidence only "
        "(raw provider responses, candidates.json, and the current label "
        "registry). Zero additional network requests were made to produce "
        "this file."
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_anchor_snapshot(
    directory: Path, registry: LabelRegistry, anchor: Anchor, *, backfill: Backfill | None = None
) -> None:
    """The accepted claim actually used, and the registry state it came from.

    Captured fresh (not backfilled) unless ``backfill`` says otherwise: the
    registry reflects ``data/`` as of whenever this file is actually written,
    which for a genuine backfill is after the original acquisition.
    """
    payload: dict[str, Any] = {
        "registry": registry.snapshot(),
        "anchor_used": anchor.to_evidence().to_json(),
        "artifact_created_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    if backfill is not None:
        payload["backfilled"] = True
        payload["backfill_note"] = backfill.note
    (directory / "accepted-anchor-snapshot.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )


def write_manifest(
    run: CollectionRun,
    settings: Settings,
    request: CollectionRequest,
    *,
    backfill: Backfill | None = None,
) -> None:
    """Every file this run produced, hashed, and the scope actually searched.

    No secret is written: headers are never recorded (BundleRecorder never
    captures them), and this states only whether a key was configured.

    ``run.started_at``/``run.finished_at`` are the real acquisition window
    and never change on a backfill; ``artifact_created_at`` below is when
    *this manifest file* was actually generated, which can be much later.
    """
    files = {
        str(p.relative_to(run.directory)): _digest(p)
        for p in sorted(run.directory.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    data_mode = backfill.original_data_mode if backfill is not None else settings.data_mode.value
    manifest = {
        "run_id": run.run_id,
        "provenance": {
            "run_started_at": run.started_at.isoformat(),
            "run_finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "artifact_created_at": dt.datetime.now(dt.UTC).isoformat(),
            "backfilled": backfill is not None,
            "backfill_note": backfill.note if backfill is not None else None,
        },
        "query": {
            "network": request.network_key,
            "anchor_address": request.anchor_address,
            "token_contract": request.token_contract,
            "analysis_start": (
                request.analysis_start.isoformat() if request.analysis_start else None
            ),
            "analysis_cutoff": (
                request.analysis_cutoff.isoformat() if request.analysis_cutoff else None
            ),
            "candidate_limit": request.candidate_limit,
            "max_requests": request.max_requests,
        },
        "configuration": {
            "tron_api_base": settings.tron_api_base,
            "tron_api_key_configured": bool(settings.tron_api_key),
            #: The mode the ORIGINAL acquisition ran under -- explicit on a
            #: backfill (B), read from live settings otherwise.
            "data_mode": data_mode,
        },
        "requests_used": run.requests_used,
        "candidates_found": len(run.candidates),
        "ineligible_events_found": len(run.ineligible_events),
        "truncated_by_candidate_limit": run.truncated_by_candidate_limit,
        "truncated_by_request_budget": run.truncated_by_request_budget,
        "written": run.written,
        "files": files,
        "caveat": (
            "A hash establishes that these files have not changed since the run. "
            "It does not establish that a candidate belongs to any entity."
        ),
    }
    (run.directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
