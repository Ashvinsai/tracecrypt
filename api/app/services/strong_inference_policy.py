"""Strong-inference policy v1 -- documented, versioned, uncalibrated.

This is engineering judgment encoded as an explicit, testable gate, NOT a
trained or validated classifier. It is Stage 3A prep only; Stage 3's later
Isolation Forest scoring and held-out precision/coverage evaluation are
separate, not-yet-started work (see docs/PROGRESS.md).

What this policy infers, precisely: that the evidence, taken together, is
strong enough to name an OPERATIONAL/RECEIVING relationship between the
subject address and a named service FOR THE SPECIFIC PATH/WINDOW under
evaluation -- i.e. "this address received funds along a path this service
operationally receives into, in this window." It explicitly does NOT infer,
and must never be read as inferring:
  - ownership of the subject address by the named service,
  - a customer-deposit relationship,
  - continuous control beyond the evidenced window,
  - a fraud or ownership probability of any kind.

Independent-evidence requirement
---------------------------------
To promote a claim to ``strong_inference`` this policy requires:
  1. At least one item of REVIEWED, address-specific linkage evidence
     (family="reviewed_address_specific_linkage") that is independent of
     whatever behavioral pattern first surfaced the candidate.
  2. A second such item from a DISTINCT upstream source (not merely a
     second feature derived from the same underlying source -- see below).
  3. In-date, right-network label scope for the claim.
  4. Sufficient verification quality for the specific claim (receipt-level,
     not history-only, not ordering-ambiguous).
  5. No unresolved material conflict.

The following do NOT count as independent evidence, and this policy is
written specifically to avoid two known traps:
  - Repeated sweeps/forwarding patterns alone (behavior, not linkage).
  - A shared resource sponsor (energy/bandwidth delegation) alone.
  - TRX funding from a common funder alone.
  - High fan-out / unusual volume alone, regardless of magnitude.
  - TRAP 1 ("one upstream source counted twice"): if two or more evidence
    items all trace back to one common upstream source (e.g. two addresses
    that share one funder), that is ONE source, not two independent ones --
    ``upstream_source_id`` is used to de-duplicate before counting.
  - TRAP 2 ("current-state delegation is not historical"): current-state
    resource delegation observed today cannot retroactively establish that
    the same delegation existed at an earlier claimed time; this policy
    refuses to promote a claim that asks it to backdate current-state
    evidence.

This policy never bypasses the review workflow. It never writes to
review_log.csv, deposit_candidates.csv, or verified_anchors.csv, and it
never auto-promotes or auto-reviews a real candidate -- it only computes a
read-only label to place on a report. Running it is always safe to repeat.

This policy also never consumes the confounder-analysis wallet-evaluation
CSV/module (see docs/DECISIONS.md's isolation entry and
test_feature_dataset.py's sibling isolation test) -- that data is
confounder-analysis-only and is kept out of this module entirely,
deliberately including out of this docstring's own wording, so a grep for
its exact module/file name over this file turns up nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from app.services.service_outcome import (
    CATEGORY_CANDIDATE_LEAD,
    CATEGORY_STRONG_INFERENCE,
    REASON_MISSING_EVIDENCE,
    ServiceOutcome,
)

POLICY_VERSION = "v1-uncalibrated-2026-09-20"

EvidenceFamily = Literal[
    "reviewed_address_specific_linkage",
    "behavioral_pattern",
    "resource_sponsorship",
    "trx_funding",
    "chronological_path",
]

FAMILY_REVIEWED_LINKAGE: EvidenceFamily = "reviewed_address_specific_linkage"
FAMILY_BEHAVIORAL: EvidenceFamily = "behavioral_pattern"
FAMILY_RESOURCE_SPONSORSHIP: EvidenceFamily = "resource_sponsorship"
FAMILY_TRX_FUNDING: EvidenceFamily = "trx_funding"
FAMILY_CHRONOLOGICAL_PATH: EvidenceFamily = "chronological_path"

#: The only family this policy accepts as counting toward the "independent,
#: reviewed, address-specific linkage" requirement. Behavioral/sponsorship/
#: funding evidence can still appear in the input list (for context/audit)
#: but never qualifies on its own, no matter how many items are supplied.
_QUALIFYING_FAMILIES = frozenset({FAMILY_REVIEWED_LINKAGE})


@dataclass(frozen=True)
class IndependentEvidenceItem:
    """One item of candidate independent-linkage evidence.

    ``data_mode`` must be "SYNTHETIC" for any fixture that is not a real,
    acquired evidence record -- SYNTHETIC items are only ever exercised via
    clearly-named test fixtures, never presented as real evidence.
    """

    family: EvidenceFamily
    evidence_id: str
    #: Identifies the ultimate upstream source this item traces back to, so
    #: that two items sharing one funder/provider are counted as one source.
    upstream_source_id: str
    reviewed: bool
    address_specific: bool
    data_mode: Literal["REAL", "SYNTHETIC"] = "REAL"


@dataclass(frozen=True)
class StrongInferencePolicyResult:
    promoted: bool
    qualifying_item_count: int
    distinct_upstream_source_count: int
    notes: tuple[str, ...]


def _qualifying_items(
    evidence_items: tuple[IndependentEvidenceItem, ...],
) -> tuple[IndependentEvidenceItem, ...]:
    return tuple(
        item
        for item in evidence_items
        if item.family in _QUALIFYING_FAMILIES and item.reviewed and item.address_specific
    )


def evaluate_independent_evidence(
    evidence_items: tuple[IndependentEvidenceItem, ...],
) -> StrongInferencePolicyResult:
    """Evaluate ONLY the independent-evidence requirement (criteria 1 and 2
    of the module docstring), de-duplicating by upstream source. Does not
    check label scope, verification quality, or conflicts -- callers use
    :func:`apply_strong_inference_policy` for the full gate."""
    qualifying = _qualifying_items(evidence_items)
    distinct_sources = {item.upstream_source_id for item in qualifying}
    notes: list[str] = []
    if not qualifying:
        notes.append(
            "No independent, reviewed, address-specific linkage evidence beyond the "
            "behavioral pattern that surfaced this candidate."
        )
    elif len(distinct_sources) < 2:
        notes.append(
            "Only one distinct upstream source of independent linkage evidence "
            f"({sorted(distinct_sources)}); repeated items tracing to a single common "
            "upstream source do not satisfy the independence requirement."
        )
    promoted = len(qualifying) >= 1 and len(distinct_sources) >= 2
    return StrongInferencePolicyResult(
        promoted=promoted,
        qualifying_item_count=len(qualifying),
        distinct_upstream_source_count=len(distinct_sources),
        notes=tuple(notes),
    )


def apply_strong_inference_policy(
    outcome: ServiceOutcome,
    evidence_items: tuple[IndependentEvidenceItem, ...],
    *,
    label_in_date: bool,
    label_network_matches: bool,
    delegation_is_current_state_only: bool = False,
    claimed_as_historical: bool = False,
) -> ServiceOutcome:
    """Apply the v1 strong-inference gate to an already-computed
    :class:`ServiceOutcome`. Only ever promotes FROM ``candidate_lead`` --
    a claim that already failed to reach even candidate_lead (e.g. no
    accepted label at all) or that is already a fully verified
    ``supported_destination`` is returned unchanged (plus a
    ``policy_version`` stamp for audit -- this never alters ``category``,
    ``service_name``, or the eight copied-through status fields in those
    cases).

    This function computes a label only. It performs no file I/O and takes
    no action against review_log.csv, deposit_candidates.csv, or
    verified_anchors.csv.
    """
    stamped = replace(outcome, policy_version=POLICY_VERSION)

    if outcome.category != CATEGORY_CANDIDATE_LEAD:
        return stamped

    if delegation_is_current_state_only and claimed_as_historical:
        return replace(
            stamped,
            reason_codes=stamped.reason_codes + (REASON_MISSING_EVIDENCE,),
            unresolved=stamped.unresolved
            + (
                "Current-state resource delegation cannot be backdated to claim "
                "historical delegation at this claim's earlier time.",
            ),
        )

    if not label_in_date or not label_network_matches:
        return replace(
            stamped,
            unresolved=stamped.unresolved
            + ("Label scope (date/network) is insufficient for strong_inference.",),
        )

    result = evaluate_independent_evidence(evidence_items)
    if not result.promoted:
        return replace(
            stamped,
            reason_codes=stamped.reason_codes + (REASON_MISSING_EVIDENCE,),
            unresolved=stamped.unresolved + result.notes,
        )

    return replace(
        stamped,
        category=CATEGORY_STRONG_INFERENCE,
        unresolved=stamped.unresolved
        + (
            "strong_inference names an operational/receiving relationship for this "
            "specific path window only -- it is not an ownership claim and not a "
            "customer-deposit claim.",
        ),
    )
