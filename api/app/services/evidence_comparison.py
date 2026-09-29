"""Stage 2 gate: a four-level evidence-comparison report, offline only.

Reads already-saved rows -- verified_anchors.csv, deposit_candidates.csv,
data/resource_evidence.csv -- and the resource-evidence collection run's own
truncation flags. It makes no blockchain request and writes nothing back to
any of those files.

The four levels match docs/FIVE_STAGE_PLAN.md's Stage 2 gate ("anchor-only,
chronological tracing, sweep rules, and sweep plus resource evidence"):

1. anchor_only -- what the accepted anchor disclosure alone establishes,
   with no reference to the candidate at all.
2. chronological_tracing -- the one token transfer that puts the candidate
   and the anchor in the same place at a moment the anchor's own claim
   covers. Still just a lead.
3. tracing_plus_behavioral_rules -- what a sweep/forwarding-behavior layer
   would add. This repository has not yet collected any outgoing-history
   scan of the candidate beyond the single known transfer, so this level's
   honest content is "not collected", plus the anti-merging/anti-promotion
   rules that would govern such data if it existed.
4. tracing_plus_behavioral_rules_plus_resource_evidence -- adds the
   collected resource-delegation and TRX-funding evidence, keeping
   current-state and historical facts separate and never inferring
   ownership from a shared sponsor.

No level computes a fraud or ownership probability. No level calls this
candidate an OKX address or a customer-deposit address -- see CAVEATS.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.services.behavioral_features import (
    ACQUISITION_VS_VERIFICATION_NOTE,
    compute_behavioral_features_from_run,
)
from app.services.collect_behavioral_evidence import PreferredBehavioralRun
from app.services.collect_resource_evidence import (
    RELATIONSHIP_RESOURCE_DELEGATION,
    RELATIONSHIP_TOKEN_TRANSFER,
    RELATIONSHIP_TRX_FUNDING,
    TEMPORAL_CURRENT_STATE_ONLY,
    TEMPORAL_HISTORICAL,
)
from app.services.features import extract_features
from app.services.resource_evidence_report import summarize

LEVEL_ANCHOR_ONLY = "anchor_only"
LEVEL_CHRONOLOGICAL_TRACING = "chronological_tracing"
LEVEL_TRACING_PLUS_BEHAVIORAL_RULES = "tracing_plus_behavioral_rules"
LEVEL_TRACING_PLUS_BEHAVIORAL_RULES_PLUS_RESOURCE_EVIDENCE = (
    "tracing_plus_behavioral_rules_plus_resource_evidence"
)

CAVEATS: tuple[str, ...] = (
    "This candidate is a lead only -- an unreviewed deposit_candidate. It has "
    "not been promoted or accepted as a verified anchor at any level below.",
    "No level below claims this candidate belongs to OKX or any other named entity.",
    "No level below calls this candidate a customer deposit address.",
    "No level below calculates a fraud probability or an ownership probability.",
    "A shared resource sponsor, a repeated delegation pattern, or a repeated "
    "sweep alone never merges two candidates into one and never promotes a "
    "candidate to a verified or trusted status.",
)

ANTI_MERGE_RULE = (
    "Anti-merging rule: a resource provider (or any other counterparty) shared "
    "by two or more candidates is never, by itself, evidence that those "
    "candidates share an owner or controller. Each candidate's evidence is "
    "evaluated independently."
)
NO_LABEL_FROM_RESOURCE_EVIDENCE_RULE = (
    "Resource-delegation and TRX-funding evidence, however extensive, cannot "
    "by themselves create or support a service label for the candidate; a "
    "service label requires its own sourced, reviewed disclosure."
)
BEHAVIORAL_RULE = (
    "Repeated forwarding or high outgoing concentration is behavioral evidence "
    "only. It must not be read as OKX ownership, customer-deposit status, "
    "service ownership, fraud, common control, or a strong inference of any kind."
)


@dataclass(frozen=True)
class LevelResult:
    level: str
    observed_evidence: tuple[str, ...]
    supported_conclusion: str
    unresolved: tuple[str, ...]
    source_evidence_ids: tuple[str, ...]
    temporal_scope_start: str | None
    temporal_scope_end: str | None
    #: "complete" | "truncated" | "not_collected" | "not_applicable"
    completeness_status: str
    completeness_notes: tuple[str, ...]
    additional_signals: tuple[str, ...]


@dataclass(frozen=True)
class ComparisonReport:
    candidate_address: str
    candidate_status: str
    caveats: tuple[str, ...]
    levels: tuple[LevelResult, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _anchor_row(
    anchor_rows: list[dict[str, str]], network: str, address: str
) -> dict[str, str] | None:
    for row in anchor_rows:
        if row.get("network") == network and row.get("address") == address:
            return row
    return None


def _level_anchor_only(
    deposit_candidate_row: dict[str, str] | None, anchor_rows: list[dict[str, str]]
) -> LevelResult:
    anchor_address = (deposit_candidate_row or {}).get("anchor_address") or ""
    network = (deposit_candidate_row or {}).get("network", "tron")
    anchor = _anchor_row(anchor_rows, network, anchor_address) if anchor_address else None

    if anchor is None:
        return LevelResult(
            level=LEVEL_ANCHOR_ONLY,
            observed_evidence=(),
            supported_conclusion=(
                "No accepted anchor disclosure is on record for this candidate's chain of evidence."
            ),
            unresolved=("The candidate's relationship, if any, to a service anchor is unknown.",),
            source_evidence_ids=(),
            temporal_scope_start=None,
            temporal_scope_end=None,
            completeness_status="not_applicable",
            completeness_notes=(),
            additional_signals=(),
        )

    entity = anchor.get("entity_name", "unknown")
    role = anchor.get("address_role") or "unknown"
    observed = (
        f"{entity} filed a {anchor.get('assertion_type', 'unknown')} disclosure for "
        f"{anchor.get('address')} ({anchor.get('review_state', 'unknown')}), source "
        f"{anchor.get('source_reference', 'unknown')}.",
    )
    valid_from = anchor.get("valid_from") or "an unknown instant"
    conclusion = (
        f"{entity} controlled {anchor.get('address')} at {valid_from} "
        f"(a dated snapshot claim); the address role is {role}. This says nothing about any "
        "other address, including the candidate below."
    )
    return LevelResult(
        level=LEVEL_ANCHOR_ONLY,
        observed_evidence=observed,
        supported_conclusion=conclusion,
        unresolved=(
            "Whether this candidate has any relationship to the anchor is not "
            "established at this level.",
            f"The anchor's address role remains {role}.",
        ),
        source_evidence_ids=(
            f"verified_anchors:{network}:{anchor.get('address')}:{anchor.get('source_hash', '')}",
        ),
        temporal_scope_start=anchor.get("valid_from") or None,
        temporal_scope_end=anchor.get("valid_to") or None,
        completeness_status="complete",
        completeness_notes=(
            "Scope is limited to the disclosed snapshot instant; this is not a "
            "continuous-control claim beyond it.",
        ),
        additional_signals=(
            "primary-source proof-of-reserves disclosure",
            "signature verification of the disclosed address",
        ),
    )


def _level_chronological_tracing(
    candidate_address: str,
    deposit_candidate_row: dict[str, str] | None,
    token_rows: list[dict[str, str]],
) -> LevelResult:
    if not token_rows:
        return LevelResult(
            level=LEVEL_CHRONOLOGICAL_TRACING,
            observed_evidence=(),
            supported_conclusion=(
                "No token transfer linking this candidate to an anchor is on record."
            ),
            unresolved=(
                "Whether this candidate ever transferred value to a known anchor is unknown.",
            ),
            source_evidence_ids=(),
            temporal_scope_start=None,
            temporal_scope_end=None,
            completeness_status="not_applicable",
            completeness_notes=(),
            additional_signals=(),
        )

    observed = tuple(
        f"{candidate_address} sent {r.get('amount_base_units')} base units of "
        f"{r.get('asset_or_resource_type')} to {r.get('counterparty_address')} at "
        f"{r.get('block_time')} (tx {r.get('tx_or_operation_id')})."
        for r in token_rows
    )
    times = sorted(r.get("block_time", "") for r in token_rows if r.get("block_time"))
    review_state = (deposit_candidate_row or {}).get("review_state", "unreviewed")
    conclusion = (
        f"This candidate is a chronologically confirmed sender of value to an address with a "
        "dated service-control claim, at a moment that claim covered. It remains a "
        f"{review_state} deposit_candidate lead: not a verified OKX address, and not a "
        "customer-deposit address."
    )
    completeness_notes = [
        "Only the single already-verified transfer is on record for this candidate."
    ]
    methodology = (deposit_candidate_row or {}).get("methodology")
    if methodology:
        completeness_notes.append(
            "Candidate discovery methodology (see deposit_candidates.csv) describes its own "
            "selection caps and acquisition window; reproduced there, not restated here."
        )
    return LevelResult(
        level=LEVEL_CHRONOLOGICAL_TRACING,
        observed_evidence=observed,
        supported_conclusion=conclusion,
        unresolved=(
            "The candidate's own identity, ownership, and role are unknown.",
            "Whether this transfer is a direct customer deposit, an intermediary hop, or "
            "something else is unresolved.",
            "No backward trace beyond this one transfer has been performed.",
        ),
        source_evidence_ids=tuple(
            sorted(
                r.get("evidence_reference") or r.get("tx_or_operation_id", "") for r in token_rows
            )
        ),
        temporal_scope_start=times[0] if times else None,
        temporal_scope_end=times[-1] if times else None,
        completeness_status="complete",
        completeness_notes=tuple(completeness_notes),
        additional_signals=(
            "chronological consistency between the transfer instant and the anchor's "
            "own valid window",
        ),
    )


def _level_behavioral_rules_not_collected() -> LevelResult:
    return LevelResult(
        level=LEVEL_TRACING_PLUS_BEHAVIORAL_RULES,
        observed_evidence=(
            "No outgoing-history scan of this candidate beyond the single known transfer has "
            "been collected; sweep/forwarding behavior is not observed.",
        ),
        supported_conclusion=(
            "No new supported conclusion is added at this level. The candidate's status is "
            "unchanged from chronological_tracing."
        ),
        unresolved=(
            "observed_token_forwarding_concentration: not collected",
            "repeated_forwarding_count: not collected",
            "receipt_to_outflow_timing: not collected",
            "post_outflow_residue: not collected",
        ),
        source_evidence_ids=(),
        temporal_scope_start=None,
        temporal_scope_end=None,
        completeness_status="not_collected",
        completeness_notes=(
            "Forwarding/sweep evidence requires a separate outgoing-history scan of the "
            "candidate; none has been run and saved in this repository yet.",
        ),
        additional_signals=(ANTI_MERGE_RULE,),
    )


def _level_behavioral_rules_from_evidence(
    behavioral_run: PreferredBehavioralRun,
    anchor_address: str | None,
    receipt_verified_tx_hashes: frozenset[str] = frozenset(),
) -> LevelResult:
    features = compute_behavioral_features_from_run(
        behavioral_run,
        anchor_address=anchor_address,
        receipt_verified_tx_hashes=receipt_verified_tx_hashes,
    )
    by_name = {f.name: f for f in features if f.name != "receipt_to_outflow_timing_seconds"}

    incoming_count = by_name["observed_incoming_transfer_count"].value
    outgoing_count = by_name["observed_outgoing_transfer_count"].value
    concentration = by_name["outgoing_concentration_toward_accepted_anchor"]
    max_by_count = by_name["outgoing_concentration_max_by_count"]
    max_by_amount = by_name["outgoing_concentration_max_by_amount"]
    repeated = by_name["repeated_forwarding_count"]
    repeated_counterparties = by_name["outgoing_counterparties_with_repeat_count"]
    timing_count = by_name["receipt_to_outflow_observation_count"].value
    ambiguous_count = by_name["receipt_to_outflow_ambiguous_count"].value
    min_gap = by_name["receipt_to_outflow_min_gap_seconds"]
    residue = by_name["post_outflow_residue_base_units"]
    execution_status = by_name["execution_verification_status"]
    acquisition_completeness = by_name["acquisition_completeness"]
    verification_quality = by_name["verification_quality"]
    event_identity_quality = by_name["event_identity_quality"]
    ordering_quality = by_name["ordering_quality"]
    receipt_verified_count = by_name["receipt_verified_observation_count"]

    # (A) The one sentence this level must say plainly: acquisition
    # completeness and verification quality are separate facts.
    acquisition_clause = (
        "Acquisition complete within the bounded window"
        if acquisition_completeness.value == "complete_within_scope"
        else "Acquisition truncated within the bounded window"
    )
    verification_clause = {
        "receipt_verified": "execution and event ordering are receipt-verified",
        "history_only": "execution and fine event ordering not verified",
        "mixed": "execution and fine event ordering verified for some, not all, observations",
        "unknown": "execution and event ordering verification status is unknown",
    }[verification_quality.value]
    observed = [
        f"{acquisition_clause}; {verification_clause}.",
        f"{incoming_count} incoming and {outgoing_count} outgoing TRC-20 transfer(s) observed "
        "for this candidate within the collected window.",
        f"Repeated forwarding: at most {repeated.value} outgoing transfer(s) observed to a "
        f"single counterparty; {repeated_counterparties.value} distinct counterpart(y/ies) "
        "received more than one observed outgoing transfer.",
        f"Maximum outgoing concentration to a single counterparty: "
        f"{_fmt_ratio(max_by_count.value)} by transfer count, "
        f"{_fmt_ratio(max_by_amount.value)} by amount.",
    ]
    if receipt_verified_count.value:
        other_count = len(behavioral_run.rows) - receipt_verified_count.value
        observed.append(
            f"{receipt_verified_count.value} of these observation(s) additionally has "
            "separate, independently verified execution evidence (a Stage 1 seed "
            f"transfer); that verification is not generalized to the other "
            f"{other_count} observation(s)."
        )
    if concentration.value is not None:
        observed.append(
            f"Outgoing concentration toward the accepted anchor: {concentration.value:.6f} "
            "of observed outgoing amount."
        )
    else:
        observed.append(
            "Outgoing concentration toward the accepted anchor is unknown "
            f"({concentration.interpretation_note})"
        )
    observed.append(
        f"{timing_count} receipt-to-outflow timing pairing(s) established (against the single "
        "nearest preceding incoming event, never an arbitrary one); "
        f"{ambiguous_count} outgoing event(s) could not be paired with a preceding receipt."
    )
    if min_gap.value is not None:
        observed.append(f"Minimum observed incoming-to-later-outgoing gap: {min_gap.value:.0f}s.")
    if residue.value is not None:
        observed.append(
            f"Post-outflow residue (observed incoming - observed outgoing): {residue.value}."
        )
    else:
        observed.append(f"Post-outflow residue is unknown ({residue.interpretation_note})")
    observed.append(
        f"execution_status is {execution_status.value} for these observations "
        "(--verify-execution was not run for this collection)."
    )

    unresolved = [
        "This behavioral pattern does not establish OKX ownership, customer-deposit status, "
        "service ownership, fraud, or common control.",
        "A later outgoing transfer is never claimed to move the same fungible token units as "
        "an earlier incoming one -- timing pairings are temporal observations only.",
    ]
    if verification_quality.value != "receipt_verified":
        unresolved.append(
            f"verification_quality={verification_quality.value}: execution is not receipt-"
            "verified for these observations; do not describe them as confirmed successful "
            "transfers."
        )
    if event_identity_quality.value != "receipt_event_index":
        unresolved.append(
            f"event_identity_quality={event_identity_quality.value}: event identity rests on "
            "a content-derived reference, not a chain-confirmed event index, for at least one "
            "observation."
        )
    if ordering_quality.value != "precise":
        unresolved.append(
            f"ordering_quality={ordering_quality.value}: fine intra-transaction ordering is "
            "not established for at least one observation."
        )
    if ambiguous_count:
        unresolved.append(
            f"{ambiguous_count} outgoing event(s) have no determinable preceding receipt in "
            "the collected evidence."
        )
    if residue.value is None:
        unresolved.append("Post-outflow residue is unknown for the reason given above.")

    source_ids = tuple(sorted(r.get("event_reference", "") for r in behavioral_run.rows))
    times = sorted(r.get("block_time", "") for r in behavioral_run.rows if r.get("block_time"))

    return LevelResult(
        level=LEVEL_TRACING_PLUS_BEHAVIORAL_RULES,
        observed_evidence=tuple(observed),
        supported_conclusion=(
            "Behavioral/sweep evidence adds observed transfer counts, concentration, and "
            "timing patterns for this candidate. " + BEHAVIORAL_RULE
        ),
        unresolved=tuple(unresolved),
        source_evidence_ids=source_ids,
        temporal_scope_start=times[0] if times else None,
        temporal_scope_end=times[-1] if times else None,
        completeness_status=(
            "complete" if acquisition_completeness.value == "complete_within_scope" else "truncated"
        ),
        completeness_notes=(
            f"preferred_behavioral_run_id={behavioral_run.run_id}",
            f"acquisition_completeness={acquisition_completeness.value}",
            f"verification_quality={verification_quality.value}",
            f"event_identity_quality={event_identity_quality.value}",
            f"ordering_quality={ordering_quality.value}",
            f"incoming_complete={behavioral_run.incoming_complete}",
            f"outgoing_complete={behavioral_run.outgoing_complete}",
            f"request_budget_truncated={behavioral_run.request_budget_truncated}",
        ),
        additional_signals=(ANTI_MERGE_RULE, BEHAVIORAL_RULE, ACQUISITION_VS_VERIFICATION_NOTE),
    )


def _fmt_ratio(value: float | None) -> str:
    return f"{value:.6f}" if value is not None else "unknown"


def _level_resource_evidence(
    candidate_address: str,
    resource_rows: list[dict[str, str]],
    *,
    request_budget_truncated: bool,
    provider_limit_truncated: bool,
    funder_limit_truncated: bool,
) -> LevelResult:
    non_token_rows = [
        r for r in resource_rows if r.get("relationship_type") != RELATIONSHIP_TOKEN_TRANSFER
    ]
    counts = summarize(resource_rows)
    features = extract_features(
        resource_rows,
        candidate_address,
        request_budget_truncated=request_budget_truncated,
        provider_limit_truncated=provider_limit_truncated,
        funder_limit_truncated=funder_limit_truncated,
    )
    by_name = {f.name: f for f in features}

    hist_rows = [
        r
        for r in resource_rows
        if r.get("relationship_type") == RELATIONSHIP_RESOURCE_DELEGATION
        and r.get("temporal_status") == TEMPORAL_HISTORICAL
    ]
    current_rows = [
        r
        for r in resource_rows
        if r.get("relationship_type") == RELATIONSHIP_RESOURCE_DELEGATION
        and r.get("temporal_status") == TEMPORAL_CURRENT_STATE_ONLY
    ]
    funding_rows = [
        r for r in resource_rows if r.get("relationship_type") == RELATIONSHIP_TRX_FUNDING
    ]

    observed: list[str] = []
    if hist_rows:
        hist_start = by_name["first_historical_resource_time"].value
        hist_end = by_name["last_historical_resource_time"].value
        hist_providers = sorted({r.get("counterparty_address", "") for r in hist_rows})
        observed.append(
            f"{counts.historical_delegation_operations} historical DelegateResourceContract/"
            f"UnDelegateResourceContract operation(s) ({counts.historical_delegate_operations} "
            f"delegate, {counts.historical_undelegate_operations} undelegate) between the "
            f"candidate and {', '.join(hist_providers)}, from {hist_start.isoformat()} to "
            f"{hist_end.isoformat()}."
        )
    if current_rows:
        current_providers = sorted({r.get("counterparty_address", "") for r in current_rows})
        current_at = by_name["current_state_observed_at"].value
        observed.append(
            f"Current-state resource delegation observed from {len(current_providers)} "
            f"counterpart(y/ies) ({', '.join(current_providers)}) as of "
            f"{current_at.isoformat() if current_at else 'an unknown instant'}. "
            "This is a snapshot fact only; it is not evidence the relationship existed at "
            "any earlier moment."
        )
    funding_note = f"{counts.incoming_trx_funding} incoming TRX-funding transaction(s) observed."
    funding_truncated = funder_limit_truncated or request_budget_truncated
    if funding_truncated and counts.incoming_trx_funding == 0:
        funding_note += (
            " The scan was truncated before completing, so this is not confirmed "
            "absence of TRX funding."
        )
    elif funding_truncated:
        funding_note += (
            " The scan was truncated before completing; this count is a lower bound, "
            "not a confirmed total."
        )
    observed.append(funding_note)

    unresolved = [
        "The identity and role of any resource provider (energy-rental market "
        "participant, operator, or otherwise) is unknown.",
        "Whether a resource provider also serves other addresses is out of scope here, "
        "and would not, by itself, merge this candidate with any other.",
    ]
    if funder_limit_truncated or request_budget_truncated:
        unresolved.append(
            "Incoming TRX-funding is unknown, not confirmed zero, due to truncated collection."
        )

    source_ids = tuple(sorted(r.get("tx_or_operation_id", "") for r in non_token_rows))
    times = sorted(
        t
        for t in (
            [r.get("block_time") for r in hist_rows]
            + [r.get("coverage_start") for r in current_rows]
        )
        if t
    )

    completeness_status = (
        "truncated"
        if (request_budget_truncated or provider_limit_truncated or funder_limit_truncated)
        else "complete"
    )
    completeness_notes = [
        f"request_budget_truncated={request_budget_truncated}",
        f"provider_limit_truncated={provider_limit_truncated}",
        f"funder_limit_truncated={funder_limit_truncated}",
    ]
    if not hist_rows and not current_rows and not funding_rows:
        completeness_notes.append("No resource-delegation or TRX-funding evidence is on record.")

    return LevelResult(
        level=LEVEL_TRACING_PLUS_BEHAVIORAL_RULES_PLUS_RESOURCE_EVIDENCE,
        observed_evidence=tuple(observed),
        supported_conclusion=(
            "Resource-delegation and TRX-funding evidence add corroborating facts about "
            "counterparties who sponsored this candidate's TRON resources. They do not "
            "establish common ownership between the candidate and any resource provider, "
            "and they introduce no new supported service-label or customer-deposit conclusion. "
            + NO_LABEL_FROM_RESOURCE_EVIDENCE_RULE
        ),
        unresolved=tuple(unresolved),
        source_evidence_ids=source_ids,
        temporal_scope_start=times[0] if times else None,
        temporal_scope_end=times[-1] if times else None,
        completeness_status=completeness_status,
        completeness_notes=tuple(completeness_notes),
        additional_signals=(
            "resource-sponsor identity and operation counts",
            "TRX-funding corroboration (incomplete unless flags above are all false)",
            "current-state and historical resource evidence kept separate",
            ANTI_MERGE_RULE,
        ),
    )


def build_comparison(
    candidate_address: str,
    *,
    deposit_candidate_row: dict[str, str] | None,
    anchor_rows: list[dict[str, str]],
    resource_rows: list[dict[str, str]],
    request_budget_truncated: bool,
    provider_limit_truncated: bool,
    funder_limit_truncated: bool,
    behavioral_run: PreferredBehavioralRun | None = None,
) -> ComparisonReport:
    """Pure function of its inputs -- no filesystem access, no network, no
    wall-clock read -- so calling it twice on the same inputs always returns
    an equal ComparisonReport (see test_evidence_comparison.py::
    test_comparison_output_is_deterministic).

    ``behavioral_run`` is optional and separate from ``resource_rows``: when
    it is None, level 3 keeps its current not_collected behavior; when a
    caller names one specific, already-loaded PreferredBehavioralRun (see
    collect_behavioral_evidence.load_preferred_behavioral_run), level 3 is
    populated from exactly that run's rows and that run's own completeness
    flags -- never from whatever happens to be sitting in
    data/behavioral_evidence.csv, whose per-row coverage_status can still
    carry an earlier, superseded run's partial status. Resource evidence
    stays level 4 regardless."""
    candidate_rows = [r for r in resource_rows if r.get("candidate_address") == candidate_address]
    token_rows = [
        r for r in candidate_rows if r.get("relationship_type") == RELATIONSHIP_TOKEN_TRANSFER
    ]
    anchor_address = (deposit_candidate_row or {}).get("anchor_address") or None

    review_state = (deposit_candidate_row or {}).get("review_state", "unreviewed")
    candidate_status = f"deposit_candidate (review_state={review_state})"

    level1 = _level_anchor_only(deposit_candidate_row, anchor_rows)
    level2 = _level_chronological_tracing(candidate_address, deposit_candidate_row, token_rows)
    if behavioral_run is not None and behavioral_run.rows:
        # The known seed transfer's tx hash, if any -- cross-referenced by
        # tx_hash only, never by re-deriving or re-verifying it here (A).
        receipt_verified_tx_hashes = frozenset(
            r.get("tx_or_operation_id", "") for r in token_rows if r.get("tx_or_operation_id")
        )
        level3 = _level_behavioral_rules_from_evidence(
            behavioral_run, anchor_address, receipt_verified_tx_hashes
        )
    else:
        level3 = _level_behavioral_rules_not_collected()
    level4 = _level_resource_evidence(
        candidate_address,
        candidate_rows,
        request_budget_truncated=request_budget_truncated,
        provider_limit_truncated=provider_limit_truncated,
        funder_limit_truncated=funder_limit_truncated,
    )

    return ComparisonReport(
        candidate_address=candidate_address,
        candidate_status=candidate_status,
        caveats=CAVEATS,
        levels=(level1, level2, level3, level4),
    )
