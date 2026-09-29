"""Stage 3A: a read-only, DISPLAY/DERIVED outcome layer over existing evidence.

This module is not a tracer, not a label registry, and not a new source of
truth. It takes already-computed, already-persisted facts about one traced
branch/claim -- the eight existing status axes this codebase already keeps
separate (``execution_status``, ``coverage_status``, ``attribution_status``,
``case_flow_linkage``, ``acquisition_completeness``, ``verification_quality``,
``event_identity_quality``, ``ordering_quality``) plus the label that a path's
terminal hop reaches, if any -- and classifies that ONE claim into exactly one
of four outcome categories:

  supported_destination   -- an accepted, in-date, right-network label names
                              the path's terminal receiving service, AND the
                              specific claimed path has sufficient execution/
                              ordering verification.
  strong_inference         -- see strong_inference_policy.py; this module
                              never assigns strong_inference itself.
  candidate_lead           -- a named service relationship with traceable
                              evidence but explicit, stated limitations.
  unknown_or_blocked       -- no accepted label reaches this claim, or a
                              blocking condition (conflict, expiry, wrong
                              network, insufficient verification) applies.

None of the eight input status fields are replaced, renamed, or collapsed --
they are copied through verbatim on the output record alongside the derived
category, so a reader can always see the raw facts a category was derived
from.

Scoping rule: outcomes are per claim/branch (``claim_id``). Resolving one
branch (e.g. a direct seed transfer that reaches an accepted label) never
implies anything about a sibling branch (e.g. a pooled withdrawal fan-out
from an intermediate hop). Naming H as "the path's terminal receiving
service" for a specific claim never asserts that an intermediate hop D is
owned or controlled by H -- D's ownership and address_role stay unknown
unless a *separate* claim/label establishes them.

This module never invents or guesses a service name. If there is no accepted
label reaching the claim, the category is unknown_or_blocked or
candidate_lead -- never a fabricated supported_destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

OutcomeCategory = Literal[
    "supported_destination",
    "strong_inference",
    "candidate_lead",
    "unknown_or_blocked",
]

CATEGORY_SUPPORTED_DESTINATION: OutcomeCategory = "supported_destination"
CATEGORY_STRONG_INFERENCE: OutcomeCategory = "strong_inference"
CATEGORY_CANDIDATE_LEAD: OutcomeCategory = "candidate_lead"
CATEGORY_UNKNOWN_OR_BLOCKED: OutcomeCategory = "unknown_or_blocked"

ReasonCode = Literal[
    "missing_evidence",
    "unresolved_conflict",
    "expired_label",
    "wrong_network",
    "insufficient_verification",
    "unreviewed_label",
    "no_accepted_label",
]

REASON_MISSING_EVIDENCE: ReasonCode = "missing_evidence"
REASON_UNRESOLVED_CONFLICT: ReasonCode = "unresolved_conflict"
REASON_EXPIRED_LABEL: ReasonCode = "expired_label"
REASON_WRONG_NETWORK: ReasonCode = "wrong_network"
REASON_INSUFFICIENT_VERIFICATION: ReasonCode = "insufficient_verification"
REASON_UNREVIEWED_LABEL: ReasonCode = "unreviewed_label"
REASON_NO_ACCEPTED_LABEL: ReasonCode = "no_accepted_label"

#: verification_quality values sufficient, on their own, to support a
#: supported_destination claim for the SPECIFIC path being evaluated.
_SUFFICIENT_VERIFICATION = frozenset({"receipt_verified"})


@dataclass(frozen=True)
class EvidenceReference:
    """One piece of evidence the outcome cites. ``evidence_id`` must resolve
    to a real, already-supplied evidence record -- callers are responsible
    for only citing evidence they were actually given (see
    test_service_outcome.py::test_evidence_references_resolve_to_real_input)."""

    kind: str
    evidence_id: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "evidence_id": self.evidence_id}


@dataclass(frozen=True)
class ServiceOutcome:
    """One claim/branch's derived outcome. Every field on this record is
    read-only output; nothing here is written back to any evidence file."""

    claim_id: str
    category: OutcomeCategory
    #: Populated only when justified for THIS claim; None otherwise. Never a
    #: guessed name.
    service_name: str | None
    evidence_references: tuple[EvidenceReference, ...]
    reason_codes: tuple[ReasonCode, ...]
    unresolved: tuple[str, ...]
    window_start: str | None
    window_end: str | None
    policy_version: str | None
    # -- the eight existing status axes, copied through verbatim ------------
    execution_status: str
    coverage_status: str
    attribution_status: str
    case_flow_linkage: str
    acquisition_completeness: str
    verification_quality: str
    event_identity_quality: str
    ordering_quality: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "category": self.category,
            "service_name": self.service_name,
            "evidence_references": [e.to_dict() for e in self.evidence_references],
            "reason_codes": list(self.reason_codes),
            "unresolved": list(self.unresolved),
            "window_start": self.window_start,
            "window_end": self.window_end,
            "policy_version": self.policy_version,
            "execution_status": self.execution_status,
            "coverage_status": self.coverage_status,
            "attribution_status": self.attribution_status,
            "case_flow_linkage": self.case_flow_linkage,
            "acquisition_completeness": self.acquisition_completeness,
            "verification_quality": self.verification_quality,
            "event_identity_quality": self.event_identity_quality,
            "ordering_quality": self.ordering_quality,
        }


def _sufficient_verification(verification_quality: str, ordering_ambiguous: bool) -> bool:
    return verification_quality in _SUFFICIENT_VERIFICATION and not ordering_ambiguous


def classify_service_outcome(
    *,
    claim_id: str,
    candidate_service_name: str | None,
    label_review_state: str | None,
    label_in_date: bool | None,
    label_network_matches: bool | None,
    execution_status: str,
    coverage_status: str,
    attribution_status: str,
    case_flow_linkage: str,
    acquisition_completeness: str,
    verification_quality: str,
    event_identity_quality: str,
    ordering_quality: str,
    ordering_ambiguous: bool,
    evidence_references: tuple[EvidenceReference, ...],
    unresolved: tuple[str, ...] = (),
    window_start: str | None = None,
    window_end: str | None = None,
    has_material_conflict: bool = False,
) -> ServiceOutcome:
    """Classify exactly one claim/branch. Pure function of its inputs -- no
    filesystem access, no network, no wall-clock read -- so calling it twice
    on the same inputs always returns an equal ServiceOutcome.

    ``candidate_service_name`` / ``label_review_state`` / ``label_in_date`` /
    ``label_network_matches`` describe the label reached by THIS claim's
    terminal hop only -- never a label reached by a different, unrelated
    branch. This is what keeps a resolved branch from implying anything
    about a sibling unresolved branch: callers must call this once per
    claim, with that claim's own terminal-hop facts.
    """

    def _outcome(
        category: OutcomeCategory,
        service_name: str | None,
        reason_codes: tuple[ReasonCode, ...],
        extra_unresolved: tuple[str, ...] = (),
    ) -> ServiceOutcome:
        return ServiceOutcome(
            claim_id=claim_id,
            category=category,
            service_name=service_name,
            evidence_references=evidence_references,
            reason_codes=reason_codes,
            unresolved=tuple(unresolved) + extra_unresolved,
            window_start=window_start,
            window_end=window_end,
            policy_version=None,
            execution_status=execution_status,
            coverage_status=coverage_status,
            attribution_status=attribution_status,
            case_flow_linkage=case_flow_linkage,
            acquisition_completeness=acquisition_completeness,
            verification_quality=verification_quality,
            event_identity_quality=event_identity_quality,
            ordering_quality=ordering_quality,
        )

    if has_material_conflict:
        return _outcome(
            CATEGORY_UNKNOWN_OR_BLOCKED,
            None,
            (REASON_UNRESOLVED_CONFLICT,),
            ("This claim has an unresolved material conflict in its evidence.",),
        )

    if not candidate_service_name:
        # Never invent a service name. No name -> not a supported destination,
        # and not a named "candidate_lead" relationship either.
        return _outcome(
            CATEGORY_UNKNOWN_OR_BLOCKED,
            None,
            (REASON_NO_ACCEPTED_LABEL,),
        )

    if label_review_state != "accepted":
        return _outcome(
            CATEGORY_UNKNOWN_OR_BLOCKED if not evidence_references else CATEGORY_CANDIDATE_LEAD,
            candidate_service_name if evidence_references else None,
            (REASON_UNREVIEWED_LABEL,),
            (f"Label review_state={label_review_state!r}; not an accepted label.",),
        )

    if label_in_date is False:
        return _outcome(
            CATEGORY_UNKNOWN_OR_BLOCKED,
            None,
            (REASON_EXPIRED_LABEL,),
            ("The named label's valid window does not cover this claim's evidence instant.",),
        )

    if label_network_matches is False:
        return _outcome(
            CATEGORY_UNKNOWN_OR_BLOCKED,
            None,
            (REASON_WRONG_NETWORK,),
            ("The named label applies to a different network than this claim's evidence.",),
        )

    # Label is accepted, in-date, and on the right network. Whether THIS
    # specific claimed path can be reported as verified now depends only on
    # this path's own verification/ordering facts -- acquisition_completeness
    # elsewhere is irrelevant to this claim (rule: a verified supported
    # destination can coexist with incomplete overall acquisition elsewhere).
    if _sufficient_verification(verification_quality, ordering_ambiguous):
        return _outcome(CATEGORY_SUPPORTED_DESTINATION, candidate_service_name, ())

    # Insufficient verification for THIS claim. Do not silently upgrade.
    if evidence_references:
        return _outcome(
            CATEGORY_CANDIDATE_LEAD,
            candidate_service_name,
            (REASON_INSUFFICIENT_VERIFICATION,),
            (
                f"verification_quality={verification_quality!r}, "
                f"ordering_ambiguous={ordering_ambiguous}: this specific path's execution/"
                "ordering is not sufficiently verified to report a supported destination.",
            ),
        )
    return _outcome(
        CATEGORY_UNKNOWN_OR_BLOCKED,
        None,
        (REASON_INSUFFICIENT_VERIFICATION,),
    )
