"""Stage 3B.2: human review of evaluation_wallets.csv registry records.

This module is the *only* code path that may change a row's
``review_state`` in data/evaluation_wallets.csv, and it never decides which
action to apply -- it only validates a caller-supplied decision (accept /
reject / quarantine) and, if valid, applies it. There is no code path here
that derives an action from the record's own content (e.g. "a first-party
URL exists, so accept it"): every applied decision requires an explicit
external ``reviewer`` and ``rationale`` supplied by the caller. This is the
same reviewer-must-show-their-work shape as
``app.services.candidate_review``, adapted to the single-file
evaluation-wallet registry instead of the three-destination anchor/candidate
sets.

This module never fetches a URL. A review packet only displays what is
already on file in evaluation_wallets.csv (and, if present, a locally
preserved source snapshot under ``data/sources/``); it explicitly says so
when only a URL/reference exists, because a currently-reachable URL is not
immutable evidence.

Four distinct concepts, kept separate everywhere in this module's output:
  (A) the sourced registry record itself (network, address, category,
      source_reference, evidence_type, ...) -- exists once ingested.
  (B) the human-reviewed/accepted operational category -- exists only after
      a reviewer calls accept here; this module never sets it itself.
  (C) feature-domain eligibility for the current TRON/USDT-TRC20 evaluation
      experiment -- a separate question from (A)/(B), decided elsewhere.
  (D) presence of a saved, materializable wallet-window evidence bundle on
      disk -- checked directly against the filesystem convention used by
      app.services.evaluation_dataset, never inferred from category name.
An accepted record ((B)) is not automatically a usable ML row -- (C) and (D)
must also hold, and this module never claims otherwise.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.services.collect_behavioral_evidence import wallet_run_dirs
from app.services.evaluation_wallets import (
    EVALUATION_WALLET_COLUMNS,
    load_evaluation_wallets,
)

EVALUATION_REVIEW_LOG = "evaluation_review_log.csv"

EVALUATION_REVIEW_LOG_COLUMNS = [
    "decision_id",
    "decided_at",
    "network",
    "address",
    "control_category",
    "previous_review_state",
    "new_review_state",
    "reviewer",
    "reviewed_at",
    "rationale",
    "evidence_inspected",
    "source_reference",
    "upstream_source_id",
    "data_mode",
]

#: Explicit reason constant for concept (D): an accepted registry record
#: with no saved feature-evidence bundle on disk. Never silently dropped --
#: this string is what a caller reports instead.
ACCEPTED_BUT_NO_MATERIALIZABLE_WINDOW = "accepted_registry_record_but_no_materializable_window"


class ReviewAction(StrEnum):
    accept = "accept"
    reject = "reject"
    quarantine = "quarantine"


ACTION_TO_STATE: dict[ReviewAction, str] = {
    ReviewAction.accept: "accepted",
    ReviewAction.reject: "rejected",
    ReviewAction.quarantine: "quarantined",
}

#: review_state values that cannot be re-reviewed at all, except through the
#: one documented transition below (accepted -> quarantined, for a problem
#: discovered after acceptance). Any other transition out of a terminal
#: state is refused -- see test E.
TERMINAL_STATES = frozenset({"accepted", "rejected", "quarantined"})

#: The one allowed re-review transition. Anything else starting from a
#: terminal state is refused.
ALLOWED_TERMINAL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {("accepted", "quarantined")}
)

#: Reviewer identities the coding/automation path can never claim to be.
#: Matched case-insensitively as whole "words" inside the supplied name, so
#: "Claude", "the assistant", "AI reviewer", "coding agent" are all refused,
#: while a real name that merely contains a substring like "ai" inside a
#: longer word (e.g. "Aiyana") is not falsely flagged.
_INVALID_REVIEWER_WORDS = (
    "agent",
    "assistant",
    "claude",
    "ai",
    "bot",
    "llm",
    "gpt",
    "automation",
    "automated",
    "system",
    "model",
    "anthropic",
    "chatgpt",
    "copilot",
)
_INVALID_REVIEWER_PATTERN = re.compile(
    r"(?<![a-z0-9])(" + "|".join(_INVALID_REVIEWER_WORDS) + r")(?![a-z0-9])",
    re.IGNORECASE,
)


class EvaluationReviewError(RuntimeError):
    """Raised only for programming misuse (e.g. bad file state), never for
    an ordinary refused review decision -- those return a Refusal."""


@dataclass(frozen=True)
class Refusal:
    code: str
    message: str
    network: str
    address: str
    control_category: str


@dataclass(frozen=True)
class ReviewRequest:
    network: str
    address: str
    control_category: str
    action: ReviewAction | None
    reviewer: str | None = None
    rationale: str | None = None
    evidence_inspected: str | None = None
    decided_at: dt.datetime | None = None


@dataclass(frozen=True)
class AppliedDecision:
    network: str
    address: str
    control_category: str
    from_state: str
    to_state: str
    reviewer: str
    decided_at: dt.datetime


@dataclass
class ReviewOutcome:
    applied: AppliedDecision | None = None
    refusal: Refusal | None = None
    written: bool = False

    @property
    def ok(self) -> bool:
        return self.applied is not None


@dataclass(frozen=True)
class ReviewPacket:
    """Everything a human reviewer needs to see before deciding, and nothing
    this tool fetched itself. Concept (A) only -- (B)/(C)/(D) are reported
    separately by ``domain_eligibility_for_wallet``, never folded in here."""

    network: str
    address: str
    control_category: str
    source_reference: str
    evidence_type: str
    valid_from: str
    valid_to: str
    notes: str
    upstream_source_id: str
    current_review_state: str
    data_mode: str
    source_snapshot_status: str
    category_semantics_note: str

    def render(self) -> str:
        lines = [
            f"network:              {self.network}",
            f"address:              {self.address}",
            f"proposed category:    {self.control_category}",
            f"current review_state: {self.current_review_state}",
            f"data_mode:            {self.data_mode}",
            f"source_reference:     {self.source_reference}",
            f"evidence_type:        {self.evidence_type}",
            f"valid_from / valid_to:[{self.valid_from or 'unbounded'}, "
            f"{self.valid_to or 'unbounded'}]",
            f"upstream_source_id:   {self.upstream_source_id or '(none stated)'}",
            f"source snapshot:      {self.source_snapshot_status}",
            "notes/limitations:",
            f"  {self.notes}",
            "category semantics:",
            f"  {self.category_semantics_note}",
        ]
        return "\n".join(lines)


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _write_rows(path: Path, rows: Sequence[dict[str, str]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVALUATION_WALLET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _find_row(
    rows: list[dict[str, str]], network: str, address: str, control_category: str
) -> int | None:
    for index, row in enumerate(rows):
        if (
            row.get("network") == network
            and row.get("address") == address
            and row.get("control_category") == control_category
        ):
            return index
    return None


def is_invalid_reviewer(reviewer: str | None) -> bool:
    """True if ``reviewer`` is blank or looks like a non-human/automation
    identity (e.g. "agent", "claude", "AI", "assistant", "") -- the coding
    agent must never be able to pose as the human reviewer."""
    name = (reviewer or "").strip()
    if not name:
        return True
    return bool(_INVALID_REVIEWER_PATTERN.search(name))


def _names_source(evidence_inspected: str | None, row: dict[str, str]) -> bool:
    """evidence_inspected must identify the record's own source: it must
    match (case-sensitive substring, either direction) source_reference or
    upstream_source_id. Arbitrary unrelated text is refused."""
    text = (evidence_inspected or "").strip()
    if not text:
        return False
    candidates = [
        (row.get("source_reference") or "").strip(),
        (row.get("upstream_source_id") or "").strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in text or text in candidate:
            return True
    return False


_CATEGORY_SEMANTICS_NOTES: dict[str, str] = {
    "self_custody": (
        "self_custody is the currently proposed category. Check whether the source "
        "actually supports self-custody, or instead supports something narrower and "
        "different -- e.g. a source that names this as a company's own designated "
        "on-chain treasury wallet supports 'designated corporate treasury wallet', "
        "not literally 'self_custody'. This tool does not resolve that mismatch or "
        "rewrite the category; the reviewer must decide whether the existing "
        "self_custody category is appropriate, whether to reject, or whether to "
        "quarantine pending a taxonomy decision."
    ),
    "other_operational_confounder": (
        "other_operational_confounder is the currently proposed category. Check that "
        "the source supports only an operational/service address associated with the "
        "named entity's business (e.g. an energy/resource marketplace's own address). "
        "This tool does not infer the specific on-chain transaction role (sender vs. "
        "receiver, or both) beyond what the source itself states -- if the source is "
        "silent on that, the packet's notes field should say so, and the reviewer "
        "should not read a specific role into an accepted category."
    ),
}
_DEFAULT_CATEGORY_SEMANTICS_NOTE = (
    "Read the source_reference, evidence_type, and notes fields above and confirm "
    "the proposed control_category is the most specific, accurate description the "
    "source actually supports -- do not accept a broader or narrower category than "
    "the source states."
)


def _source_snapshot_status(data_dir: Path, source_reference: str) -> str:
    """Whether a locally preserved snapshot exists for this source. This
    function never fetches the URL itself -- if no local snapshot exists it
    says so, and explicitly notes that a currently-reachable URL is not by
    itself immutable evidence."""
    sources_dir = data_dir / "sources"
    if sources_dir.is_dir():
        for candidate in sources_dir.iterdir():
            if candidate.is_file() and source_reference.startswith(("http://", "https://")):
                # No naming convention links evaluation_wallets.csv rows to a
                # sources/ snapshot file today (unlike anchor_import's
                # source_file column) -- report that explicitly rather than
                # guessing a match.
                continue
    return (
        "no locally preserved source snapshot/hash is recorded on this "
        "evaluation_wallets.csv row (there is no source_file/source_hash column "
        "for this registry, unlike verified_anchors.csv). Only the "
        "source_reference text is on file. A currently-reachable URL is NOT "
        "immutable evidence -- content can change or disappear after this row "
        "was written. Verification is limited to what the notes field records "
        "about when/how the source was inspected."
    )


def build_review_packet(
    data_dir: Path, network: str, address: str, control_category: str
) -> ReviewPacket | None:
    """The read-only packet a human reviewer inspects before deciding.
    Returns None if no such registry row exists."""
    rows = _read_rows(data_dir / "evaluation_wallets.csv")
    index = _find_row(rows, network, address, control_category)
    if index is None:
        return None
    row = rows[index]
    return ReviewPacket(
        network=row.get("network", ""),
        address=row.get("address", ""),
        control_category=row.get("control_category", ""),
        source_reference=row.get("source_reference", ""),
        evidence_type=row.get("evidence_type", ""),
        valid_from=row.get("valid_from", ""),
        valid_to=row.get("valid_to", ""),
        notes=row.get("notes", ""),
        upstream_source_id=row.get("upstream_source_id", ""),
        current_review_state=row.get("review_state", ""),
        data_mode=row.get("data_mode", "RECORDED_PUBLIC"),
        source_snapshot_status=_source_snapshot_status(
            data_dir, row.get("source_reference", "")
        ),
        category_semantics_note=_CATEGORY_SEMANTICS_NOTES.get(
            control_category, _DEFAULT_CATEGORY_SEMANTICS_NOTE
        ),
    )


def _decision_id(network: str, address: str, control_category: str, decided_at: dt.datetime) -> str:
    return f"{network}:{address}:{control_category}:{decided_at.isoformat()}"


def review_evaluation_wallet(
    data_dir: Path, request: ReviewRequest, *, write: bool = False
) -> ReviewOutcome:
    """Apply (or dry-run) one review decision against
    data/evaluation_wallets.csv, and, if written, append exactly one record
    to data/evaluation_review_log.csv.

    ``request.action`` may be None -- that is the valid "just show me the
    packet" mode; this function does nothing and returns an empty outcome
    in that case regardless of ``write``. This function never picks an
    action on its own; it only validates and applies the one supplied.
    """
    registry_path = data_dir / "evaluation_wallets.csv"
    rows = _read_rows(registry_path)
    index = _find_row(rows, request.network, request.address, request.control_category)
    if index is None:
        return ReviewOutcome(
            refusal=Refusal(
                "no_such_record",
                f"no evaluation_wallets.csv record for {request.network}/{request.address} "
                f"with control_category={request.control_category!r}",
                request.network,
                request.address,
                request.control_category,
            )
        )
    row = rows[index]
    from_state = row.get("review_state", "")

    if request.action is None:
        # Dry-run "show packet, decide nothing" mode -- always valid.
        return ReviewOutcome()

    if is_invalid_reviewer(request.reviewer):
        return ReviewOutcome(
            refusal=Refusal(
                "reviewer_required",
                "a review decision needs a named human reviewer identity; blank or "
                "automation-like identities (e.g. 'agent', 'assistant', 'claude', 'AI', "
                "'system') are refused",
                request.network,
                request.address,
                request.control_category,
            )
        )
    if not (request.rationale or "").strip():
        return ReviewOutcome(
            refusal=Refusal(
                "rationale_required",
                "a review decision needs a non-blank rationale",
                request.network,
                request.address,
                request.control_category,
            )
        )
    if not _names_source(request.evidence_inspected, row):
        return ReviewOutcome(
            refusal=Refusal(
                "evidence_not_identified",
                "evidence_inspected must identify this record's own source_reference or "
                "upstream_source_id; arbitrary unrelated text is refused "
                f"(source_reference={row.get('source_reference')!r}, "
                f"upstream_source_id={row.get('upstream_source_id')!r})",
                request.network,
                request.address,
                request.control_category,
            )
        )

    to_state = ACTION_TO_STATE[request.action]
    if from_state in TERMINAL_STATES and (from_state, to_state) not in ALLOWED_TERMINAL_TRANSITIONS:
        return ReviewOutcome(
            refusal=Refusal(
                "already_terminal",
                f"this record is already {from_state!r}; the only allowed re-review "
                f"transition is accepted -> quarantined, not {from_state!r} -> {to_state!r}",
                request.network,
                request.address,
                request.control_category,
            )
        )

    decided_at = request.decided_at or dt.datetime.now(dt.UTC)
    updated = dict(row)
    updated["review_state"] = to_state
    updated["reviewer"] = request.reviewer.strip() if request.reviewer else ""

    log_row = {
        "decision_id": _decision_id(
            request.network, request.address, request.control_category, decided_at
        ),
        "decided_at": decided_at.isoformat(),
        "network": request.network,
        "address": request.address,
        "control_category": request.control_category,
        "previous_review_state": from_state,
        "new_review_state": to_state,
        "reviewer": request.reviewer.strip() if request.reviewer else "",
        "reviewed_at": decided_at.isoformat(),
        "rationale": (request.rationale or "").strip(),
        "evidence_inspected": (request.evidence_inspected or "").strip(),
        "source_reference": row.get("source_reference", ""),
        "upstream_source_id": row.get("upstream_source_id", ""),
        "data_mode": row.get("data_mode", ""),
    }

    if write:
        rows[index] = updated
        _write_rows(registry_path, rows)
        _append_log(data_dir / EVALUATION_REVIEW_LOG, [log_row])

    applied = AppliedDecision(
        network=request.network,
        address=request.address,
        control_category=request.control_category,
        from_state=from_state,
        to_state=to_state,
        reviewer=request.reviewer.strip() if request.reviewer else "",
        decided_at=decided_at,
    )
    return ReviewOutcome(applied=applied, written=write)


def _append_log(path: Path, log_rows: Sequence[dict[str, str]]) -> None:
    exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVALUATION_REVIEW_LOG_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerows(log_rows)


def domain_eligibility_for_wallet(
    data_dir: Path,
    behavioral_evidence_root: Path,
    network: str,
    address: str,
) -> str:
    """Concept (D): does a saved, materializable feature-evidence bundle
    exist on disk for this (network, address) under the canonical
    <evidence_root>/<network>/<address>/<run_id>/{manifest.json,evidence.json}
    contract (see app.services.collect_behavioral_evidence.wallet_run_dirs)?

    This is a direct filesystem check -- never inferred from
    control_category, and never from whether the record is accepted.
    Returns a short, explicit status string.
    """
    if wallet_run_dirs(behavioral_evidence_root, network, address):
        return "materializable_window_present"

    wallets = load_evaluation_wallets(data_dir / "evaluation_wallets.csv")
    is_accepted = any(
        w.network == network and w.address == address and w.review_state == "accepted"
        for w in wallets
    )
    if is_accepted:
        return ACCEPTED_BUT_NO_MATERIALIZABLE_WINDOW
    return "not_accepted_and_no_materializable_window"
