"""Stage 2/3 prep: an offline dataset of independently sourced comparison
("control"/confounder) wallets, kept strictly separate from
verified_anchors.csv, deposit_candidates.csv, and review_log.csv.

This dataset never feeds the attribution pipeline (app.services.
evidence_comparison never imports this module). It exists for a later,
still-unbuilt evaluation step to compare a candidate's behavioral/resource
features against wallets whose activity pattern is independently explained
by something other than fraud -- a frequent exchange customer, a payment
service, an energy-rental recipient, a self-custody user, or another
operational confounder.

The absence of a record here is not a fact. A wallet with no entry has
simply not been independently evaluated; it must never be read as "not a
confounder" or promoted into a negative/benign label. Every record that
does exist must carry its own source_reference and evidence_type -- an
unsourced control category is refused, exactly like an unsourced service
label would be refused elsewhere in this project.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

EVALUATION_WALLET_COLUMNS = [
    "network",
    "address",
    "control_category",
    "source_reference",
    "evidence_type",
    "valid_from",
    "valid_to",
    "review_state",
    "notes",
    # Stage 3B additions -- optional/backward-compatible. An older CSV row
    # missing these columns loads with the defaults below, never an error.
    "upstream_source_id",
    "reviewer",
    "data_mode",
]

#: Columns added after the original Stage 2 schema. load_evaluation_wallets
#: fills these with a safe default when an older row's CSV doesn't have
#: them, so existing files never need a rewrite to stay loadable.
_OPTIONAL_COLUMN_DEFAULTS = {
    "upstream_source_id": "",
    "reviewer": "",
    "data_mode": "RECORDED_PUBLIC",
}

#: Independently established confounder categories. "other_operational_confounder"
#: covers a legitimate pattern this list does not yet name -- it still requires
#: its own source_reference and evidence_type, and its notes field must say what
#: the pattern actually is.
CONTROL_CATEGORIES = frozenset(
    {
        "self_custody",
        "frequent_exchange_customer",
        "payment_service",
        "energy_rental_recipient",
        "other_operational_confounder",
    }
)

#: Mirrors app.models.enums.ReviewState's vocabulary -- a control record is
#: reviewed the same way a service-control claim is, never accepted by default.
REVIEW_STATES = frozenset({"unreviewed", "accepted", "rejected", "quarantined"})


class EvaluationWalletError(RuntimeError):
    """A control record is missing what makes it usable as evidence. Never a
    silent default."""


@dataclass(frozen=True)
class EvaluationWallet:
    network: str
    address: str
    control_category: str
    source_reference: str
    evidence_type: str
    valid_from: str
    valid_to: str
    review_state: str
    notes: str
    #: Collapses two documents citing the same upstream origin (e.g. two
    #: news articles quoting one disclosure) into one source for
    #: evidence-counting purposes. Empty string means "not stated" -- never
    #: treated as automatically distinct from another empty-string row; a
    #: reader that needs to count sources treats blank ids as one-off,
    #: unmatched sources, not as silently equal to each other.
    upstream_source_id: str = ""
    #: Who reviewed/accepted this record -- mirrors candidate_review.py's
    #: reviewer field, never a free-text substitute for review_state.
    reviewer: str = ""
    #: LIVE / RECORDED_PUBLIC / SYNTHETIC. Defaults to RECORDED_PUBLIC for
    #: pre-existing rows that predate this field (this project has never
    #: written a LIVE or SYNTHETIC row to this file).
    data_mode: str = "RECORDED_PUBLIC"

    def to_csv_row(self) -> dict[str, str]:
        return {col: getattr(self, col) for col in EVALUATION_WALLET_COLUMNS}


def validate_evaluation_wallet(wallet: EvaluationWallet) -> None:
    """Every control record needs an explicit source/evidence basis (B).
    Raises rather than silently accepting an unsourced or miscategorized row."""
    if wallet.control_category not in CONTROL_CATEGORIES:
        raise EvaluationWalletError(
            f"unsupported control_category {wallet.control_category!r}; "
            f"expected one of {sorted(CONTROL_CATEGORIES)}"
        )
    if not wallet.source_reference.strip():
        raise EvaluationWalletError(
            "source_reference is required: a control wallet is only usable as "
            "evidence when its own basis is named, the same as a service label"
        )
    if not wallet.evidence_type.strip():
        raise EvaluationWalletError(
            "evidence_type is required: state what kind of evidence establishes "
            "this control category (e.g. 'authorized deposit record', "
            "'self-attested and independently corroborated wallet')"
        )
    if wallet.review_state not in REVIEW_STATES:
        raise EvaluationWalletError(
            f"unsupported review_state {wallet.review_state!r}; "
            f"expected one of {sorted(REVIEW_STATES)}"
        )


def load_evaluation_wallets(path: Path) -> list[EvaluationWallet]:
    """Read whatever control records exist. An empty or missing file is not
    an error -- it means no independently sourced control wallet has been
    supplied yet, not that none exist."""
    if not path.is_file():
        return []
    with path.open(newline="") as fh:
        wallets = []
        for row in csv.DictReader(fh):
            filled = dict(row)
            for col, default in _OPTIONAL_COLUMN_DEFAULTS.items():
                filled.setdefault(col, default)
                if filled[col] is None:
                    filled[col] = default
            wallets.append(EvaluationWallet(**filled))
        return wallets


def dedupe_by_upstream_source(wallets: list[EvaluationWallet]) -> int:
    """Count of INDEPENDENT sources across ``wallets``, collapsing any group
    that shares a non-blank upstream_source_id into one source. A blank
    upstream_source_id is never treated as matching another blank one --
    each such record counts as its own, unmatched source (see D:
    "two copies of one upstream source are not two sources", and the
    isolation this must NOT do -- collapse genuinely distinct, merely
    unlabeled, sources)."""
    named = {w.upstream_source_id for w in wallets if w.upstream_source_id.strip()}
    unnamed_count = sum(1 for w in wallets if not w.upstream_source_id.strip())
    return len(named) + unnamed_count


def _migrate_header_if_stale(path: Path) -> None:
    """Upgrade an on-disk header written before the Stage 3B optional
    columns existed (``upstream_source_id``/``reviewer``/``data_mode``) to
    the current, full column set -- in place, touching only the header
    line.

    Discovered as a real gap during Stage 3B.1 sourcing: appending a
    current-schema row (12 columns) under a stale 9-column header produces
    a CSV where ``csv.DictReader`` hands the extra trailing values back
    under key ``None`` on the very next load, which
    ``EvaluationWallet(**filled)`` then raises on -- silently corrupting
    the file's readability rather than refusing loudly at write time. This
    only rewrites the header line; every existing data row's bytes are
    left untouched, and rows written under the old, narrower header keep
    loading correctly afterward because ``load_evaluation_wallets`` already
    fills any column missing from a given data row with its documented
    default.
    """
    if not path.is_file():
        return
    text = path.read_text()
    if not text:
        return
    lines = text.splitlines(keepends=True)
    if not lines:
        return
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    header_cols = lines[0].rstrip("\r\n").split(",")
    if header_cols == EVALUATION_WALLET_COLUMNS:
        return  # already current
    if header_cols != EVALUATION_WALLET_COLUMNS[: len(header_cols)]:
        # Not a recognized old-format prefix of the current schema -- leave
        # it alone rather than guess; append will proceed as before and any
        # incompatibility here predates this fix and is out of its scope.
        return
    lines[0] = ",".join(EVALUATION_WALLET_COLUMNS) + newline
    path.write_text("".join(lines))


def append_evaluation_wallet(path: Path, wallet: EvaluationWallet) -> None:
    """Validate, then append. Never writes an unsourced or miscategorized
    row; never touches verified_anchors.csv, deposit_candidates.csv, or
    review_log.csv."""
    validate_evaluation_wallet(wallet)
    _migrate_header_if_stale(path)
    file_exists = path.is_file()
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVALUATION_WALLET_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(wallet.to_csv_row())


def find_evaluation_wallet(
    wallets: list[EvaluationWallet], network: str, address: str
) -> EvaluationWallet | None:
    """The accepted control record for one address, or None.

    None means "not independently evaluated". It is never read as, printed
    as, or converted into a negative/benign/"not a confounder" label -- the
    caller must keep that absence visibly unknown, exactly like an unknown
    address_role or an unreviewed candidate."""
    for wallet in wallets:
        if (
            wallet.network == network
            and wallet.address == address
            and wallet.review_state == "accepted"
        ):
            return wallet
    return None
