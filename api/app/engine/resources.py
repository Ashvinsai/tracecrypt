"""TRON resource delegation as evidence, and the limits of that evidence.

Two provider shapes, read from the current TRON documentation on 2026-09-20
rather than assumed:

``POST /wallet/getdelegatedresourceaccountindexv2``
    returns ``account``, ``fromAccounts``, ``toAccounts`` — address lists. No
    timestamp, no amount, not even which resource was delegated.

``POST /walletsolidity/getdelegatedresourcev2``
    returns ``from``, ``to``, ``frozen_balance_for_bandwidth``,
    ``frozen_balance_for_energy``, ``expire_time_for_bandwidth``,
    ``expire_time_for_energy``. The ``expire_time`` fields are when the lock
    ends, not when the delegation began.

Neither says when a relationship started, and neither reports one that has
already ended. So a state query supports "this exists now" and never "this
existed then" (day-one test 12), and an empty response is silence, not absence.

A sponsor is also not an owner. Energy rental is a market: JustLend and similar
services delegate to thousands of unrelated strangers, and an exchange's own
wallet delegating energy to an address says nothing about who controls that
address. A shared sponsor therefore produces a lead about one receiver, never a
cluster and never an inherited entity name (day-one test 10).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.engine.result import LabelEvidence, Limitation
from app.models.enums import (
    AttributionStatus,
    CoverageStatus,
    DelegationBasis,
    ResourceType,
)
from app.services.labels import LabelRegistry

#: Above this many distinct receivers, a sponsor looks like a rental service or
#: another shared provider rather than a related party. It is a review
#: threshold, not a measurement: nothing here has been calibrated against
#: known sponsors, and a sponsor below it is not thereby related to anyone.
DEFAULT_SHARED_SERVICE_FANOUT = 20

#: Evidence kinds that are independent of resource delegation. Anything derived
#: from the same overlap — a shared sponsor, a shared funder, a repeated sweep
#: pattern — is not corroboration of itself.
INDEPENDENT_EVIDENCE_KINDS = frozenset(
    {
        "sourced_disclosure",
        "signed_ownership",
        "authorized_observation",
    }
)


def _require_aware(value: dt.datetime | None, name: str) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware; naive input is not assumed to be UTC")
    return value.astimezone(dt.UTC)


@dataclass(frozen=True)
class DelegationObservation:
    """One delegation relationship as some provider reported it.

    ``sponsor_address`` delegates (``from``); ``receiver_address`` receives
    (``to``). ``resource`` is ``None`` when the endpoint did not say which.
    """

    network_key: str
    sponsor_address: str
    receiver_address: str
    resource: ResourceType | None
    basis: DelegationBasis
    observed_at: dt.datetime
    source_reference: str
    frozen_balance_base_units: int | None = None
    lock_expires_at: dt.datetime | None = None
    operation_tx_hash: str | None = None
    operation_time: dt.datetime | None = None
    operation_kind: str | None = None
    acquisition_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _require_aware(self.observed_at, "observed_at"))
        object.__setattr__(
            self, "lock_expires_at", _require_aware(self.lock_expires_at, "lock_expires_at")
        )
        object.__setattr__(
            self, "operation_time", _require_aware(self.operation_time, "operation_time")
        )
        if self.basis is DelegationBasis.current_state and (
            self.operation_time is not None
            or self.operation_tx_hash is not None
            or self.operation_kind is not None
        ):
            raise ValueError(
                "a current state response carries no operation; refusing to record one"
            )
        if self.basis is DelegationBasis.historical_operation and (
            self.operation_time is None or self.operation_tx_hash is None
        ):
            raise ValueError(
                "a historical delegation claim needs both a transaction and its block time"
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "network": self.network_key,
            "sponsor_address": self.sponsor_address,
            "receiver_address": self.receiver_address,
            "resource": self.resource.value if self.resource else None,
            "basis": self.basis.value,
            "observed_at": self.observed_at.isoformat(),
            "source_reference": self.source_reference,
            "frozen_balance_base_units": (
                str(self.frozen_balance_base_units)
                if self.frozen_balance_base_units is not None
                else None
            ),
            "lock_expires_at": self.lock_expires_at.isoformat() if self.lock_expires_at else None,
            "operation_tx_hash": self.operation_tx_hash,
            "operation_time": self.operation_time.isoformat() if self.operation_time else None,
            "operation_kind": self.operation_kind,
            "acquisition_id": self.acquisition_id,
        }


@dataclass(frozen=True)
class DelegationTiming:
    """When a delegation is known to have been established, if it is known."""

    established_at: dt.datetime | None
    basis: DelegationBasis
    status: str  # "dated" | "unknown"
    reason: str
    evidence_reference: str | None = None


def delegation_timing(observation: DelegationObservation) -> DelegationTiming:
    if observation.basis is DelegationBasis.historical_operation:
        return DelegationTiming(
            established_at=observation.operation_time,
            basis=observation.basis,
            status="dated",
            reason="a successful delegation operation with a block time",
            evidence_reference=observation.operation_tx_hash,
        )
    return DelegationTiming(
        established_at=None,
        basis=observation.basis,
        status="unknown",
        reason=(
            "current delegation state carries no start time; the expiry field is "
            "when the lock ends, not when the delegation began"
        ),
        evidence_reference=observation.source_reference,
    )


def active_at(observation: DelegationObservation, moment: dt.datetime) -> bool | None:
    """Was this delegation in place at ``moment``? ``None`` means unknown.

    A state query answers only for the instant it was read. Asking about any
    earlier moment returns unknown rather than projecting the present backwards.
    """
    aware = _require_aware(moment, "moment")
    if aware is None:  # pragma: no cover - moment is never None here
        return None
    if observation.basis is DelegationBasis.current_state:
        return True if aware >= observation.observed_at else None
    if observation.operation_time is None:  # pragma: no cover - constructor forbids it
        return None
    return aware >= observation.operation_time


@dataclass(frozen=True)
class DelegationCoverage:
    """What a delegation query did and did not establish."""

    queried_at: dt.datetime
    endpoint: str
    observations_found: int
    has_historical_source: bool

    @property
    def status(self) -> CoverageStatus:
        """Never ``complete_within_scope`` from state alone, empty or not."""
        if not self.has_historical_source:
            return CoverageStatus.unknown
        return CoverageStatus.complete_within_scope

    @property
    def establishes_absence(self) -> bool:
        """An empty current-state response is silence, not proof of absence."""
        return self.observations_found == 0 and self.has_historical_source

    def limitations(self) -> list[Limitation]:
        out: list[Limitation] = []
        if not self.has_historical_source:
            out.append(
                Limitation(
                    code="delegation_history_not_queried",
                    message=(
                        f"{self.endpoint} reports current state only. It cannot date a "
                        "delegation, and an empty response does not establish that no "
                        "delegation existed earlier."
                    ),
                )
            )
        return out


@dataclass(frozen=True)
class SponsorLead:
    """One receiver, one sponsor, and what that pairing is worth: a lead.

    ``entity_name`` is always ``None``. The sponsor's own label, when it has
    one, is carried in ``sponsor_label`` so a reviewer can see it — being
    delegated energy by an exchange does not make an address the exchange's.
    """

    receiver_address: str
    sponsor_address: str
    resource: ResourceType | None
    basis: DelegationBasis
    sponsor_fanout: int
    sponsor_looks_like_shared_service: bool
    reasons: tuple[str, ...]
    supporting_observations: tuple[DelegationObservation, ...]
    sponsor_label: LabelEvidence | None = None
    attribution_status: AttributionStatus = field(default=AttributionStatus.candidate)
    entity_name: None = None

    def addresses_mentioned(self) -> set[str]:
        """Every address this lead rests on. Co-receivers are not among them."""
        addresses = {self.receiver_address, self.sponsor_address}
        for observation in self.supporting_observations:
            addresses.add(observation.sponsor_address)
            addresses.add(observation.receiver_address)
        return addresses

    def to_json(self) -> dict[str, Any]:
        return {
            "receiver_address": self.receiver_address,
            "sponsor_address": self.sponsor_address,
            "resource": self.resource.value if self.resource else None,
            "basis": self.basis.value,
            "attribution_status": self.attribution_status.value,
            "entity_name": None,
            "sponsor_fanout": self.sponsor_fanout,
            "sponsor_looks_like_shared_service": self.sponsor_looks_like_shared_service,
            "reasons": list(self.reasons),
            "sponsor_label": self.sponsor_label.to_json() if self.sponsor_label else None,
            "supporting_observations": [o.to_json() for o in self.supporting_observations],
        }


def sponsor_leads(
    observations: Iterable[DelegationObservation],
    *,
    registry: LabelRegistry | None = None,
    moment: dt.datetime | None = None,
    shared_service_fanout_threshold: int = DEFAULT_SHARED_SERVICE_FANOUT,
) -> list[SponsorLead]:
    """One lead per (receiver, sponsor) pair. Never a cluster.

    Addresses sharing a sponsor are not collected into a group here, because
    there is no supported sense in which they are one.
    """
    observations = list(observations)
    fanout: dict[tuple[str, str], set[str]] = {}
    for observation in observations:
        sponsor_key = (observation.network_key, observation.sponsor_address)
        fanout.setdefault(sponsor_key, set()).add(observation.receiver_address)

    grouped: dict[tuple[str, str, str], list[DelegationObservation]] = {}
    for observation in observations:
        pair_key = (
            observation.network_key,
            observation.receiver_address,
            observation.sponsor_address,
        )
        grouped.setdefault(pair_key, []).append(observation)

    leads: list[SponsorLead] = []
    for (network_key, receiver, sponsor), group in grouped.items():
        count = len(fanout[(network_key, sponsor)])
        shared_service = count >= shared_service_fanout_threshold
        reasons = [
            f"{sponsor} delegates resources to {receiver}",
            "resource delegation is not a token payment and not shared ownership",
        ]
        if shared_service:
            reasons.append(
                f"this sponsor delegates to {count} distinct receivers in the observed "
                "window, which is what an energy-rental service looks like"
            )
        if any(o.basis is DelegationBasis.current_state for o in group):
            reasons.append("current state only; the delegation is undated")

        sponsor_label = None
        if registry is not None and moment is not None:
            anchors = registry.lookup(network_key, sponsor)
            for anchor in anchors:
                if anchor.covers(moment):
                    sponsor_label = anchor.to_evidence()
                    break

        leads.append(
            SponsorLead(
                receiver_address=receiver,
                sponsor_address=sponsor,
                resource=group[0].resource,
                basis=group[0].basis,
                sponsor_fanout=count,
                sponsor_looks_like_shared_service=shared_service,
                reasons=tuple(reasons),
                supporting_observations=tuple(group),
                sponsor_label=sponsor_label,
            )
        )
    return leads


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    reason: str
    resulting_status: AttributionStatus | None = None


def may_promote(lead: SponsorLead, *, corroboration: Collection[str] = ()) -> PromotionDecision:
    """May this lead become more than a lead?

    Only on evidence independent of the delegation itself, and only as far as
    inference. Nothing here can produce ``supported``: that needs a source
    naming the address, which a delegation record is not.
    """
    independent = sorted(set(corroboration) & INDEPENDENT_EVIDENCE_KINDS)
    dependent = sorted(set(corroboration) - INDEPENDENT_EVIDENCE_KINDS)

    if lead.sponsor_looks_like_shared_service:
        return PromotionDecision(
            allowed=False,
            reason=(
                f"{lead.sponsor_address} delegates to {lead.sponsor_fanout} receivers and "
                "behaves like a shared service; its customers are not related to each other"
            ),
        )
    if not independent:
        listed = ", ".join(dependent) if dependent else "nothing"
        return PromotionDecision(
            allowed=False,
            reason=(
                f"a shared sponsor plus {listed} is one overlap described twice; "
                f"promotion needs one of {sorted(INDEPENDENT_EVIDENCE_KINDS)}"
            ),
        )
    return PromotionDecision(
        allowed=True,
        reason=f"independent evidence: {', '.join(independent)}. Records as inference, not fact.",
        resulting_status=AttributionStatus.inferred,
    )


def parse_account_index(
    payload: dict[str, Any], *, network_key: str, observed_at: dt.datetime
) -> list[DelegationObservation]:
    """Parse ``/wallet/getdelegatedresourceaccountindexv2``.

    The documented fields are ``account``, ``fromAccounts`` and ``toAccounts``.
    There is no resource, no amount and no time in the response, so none is
    filled in here.
    """
    account = (payload.get("account") or "").strip()
    if not account:
        return []
    source = "POST /wallet/getdelegatedresourceaccountindexv2"

    def build(sponsor: str, receiver: str) -> DelegationObservation:
        return DelegationObservation(
            network_key=network_key,
            sponsor_address=sponsor,
            receiver_address=receiver,
            resource=None,
            basis=DelegationBasis.current_state,
            observed_at=observed_at,
            source_reference=source,
        )

    out = [build(str(s), account) for s in payload.get("fromAccounts") or []]
    out += [build(account, str(r)) for r in payload.get("toAccounts") or []]
    return out


def _expiry(raw: Any) -> dt.datetime | None:
    """``expire_time_*`` is milliseconds; 0 or absent means no lock, not 1970."""
    if not raw:
        return None
    return dt.datetime.fromtimestamp(int(raw) / 1000, tz=dt.UTC)


def parse_delegated_resource_v2(
    payload: dict[str, Any], *, network_key: str, observed_at: dt.datetime
) -> list[DelegationObservation]:
    """Parse ``/walletsolidity/getdelegatedresourcev2``.

    One row can carry both resources, and they are separate relationships with
    separate amounts and separate locks, so they stay separate observations. A
    zero frozen balance is not a delegation.
    """
    source = "POST /walletsolidity/getdelegatedresourcev2"
    rows: Sequence[dict[str, Any]] = payload.get("delegatedResource") or []
    out: list[DelegationObservation] = []
    for row in rows:
        sponsor = str(row.get("from") or "").strip()
        receiver = str(row.get("to") or "").strip()
        if not sponsor or not receiver:
            continue
        for resource, balance_field, expiry_field in (
            (ResourceType.energy, "frozen_balance_for_energy", "expire_time_for_energy"),
            (
                ResourceType.bandwidth,
                "frozen_balance_for_bandwidth",
                "expire_time_for_bandwidth",
            ),
        ):
            balance = int(row.get(balance_field) or 0)
            if balance <= 0:
                continue
            out.append(
                DelegationObservation(
                    network_key=network_key,
                    sponsor_address=sponsor,
                    receiver_address=receiver,
                    resource=resource,
                    basis=DelegationBasis.current_state,
                    observed_at=observed_at,
                    source_reference=source,
                    frozen_balance_base_units=balance,
                    lock_expires_at=_expiry(row.get(expiry_field)),
                )
            )
    return out
