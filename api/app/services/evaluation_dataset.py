"""Stage 3B: converts APPROVED evaluation-wallet registry entries plus
SAVED evidence run bundles into wallet-window feature rows, offline and
deterministically.

This module never fetches evidence live. If an accepted evaluation-wallet
record has no saved behavioral-evidence run bundle on disk, that record is
skipped with an explicit ``missing_evidence`` reason -- it is never silently
dropped and never triggers a network call.

Isolation (must hold, and is grep-tested): this module never imports
app.services.service_outcome or app.services.strong_inference_policy, and
never treats their output as a feature or as evaluation truth. A category
here always comes from app.services.evaluation_wallets, never from
behavioral/resource features themselves.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.services.behavioral_features import compute_behavioral_features_from_run
from app.services.collect_behavioral_evidence import (
    BehavioralEvidenceError,
    load_preferred_behavioral_run,
    wallet_run_dirs,
)
from app.services.evaluation_wallets import (
    find_evaluation_wallet,
    load_evaluation_wallets,
)
from app.services.feature_dataset import (
    FEATURE_DEFINITION_VERSION,
    WalletWindowRow,
    build_wallet_window_row,
    dedupe_rows,
)


@dataclass(frozen=True)
class SkippedWallet:
    network: str
    address: str
    reason: str


@dataclass(frozen=True)
class MaterializationResult:
    rows: list[WalletWindowRow]
    skipped: list[SkippedWallet]
    snapshot_hash: str
    feature_definition_version: str
    registry_path: str


def materialize_evaluation_dataset(
    *,
    registry_path: Path,
    behavioral_evidence_root: Path,
    feature_definition_version: str = FEATURE_DEFINITION_VERSION,
) -> MaterializationResult:
    """Build wallet-window rows for every ACCEPTED evaluation-wallet record
    that has a saved behavioral-evidence run bundle on disk.

    Deterministic and offline: same registry file + same saved run bundles
    always produce the same rows and the same snapshot_hash. Bundles are
    discovered under the canonical
    ``<evidence_root>/<network>/<address>/<run_id>/`` contract, so every
    saved capture is visible; two windows for the same wallet yield two
    distinct rows (see feature_dataset's per-window row semantics). A wallet
    with no readable bundle is skipped with reason "missing_evidence" -- this
    function never fetches live evidence to fill that gap.
    """
    wallets = load_evaluation_wallets(registry_path)
    accepted = [w for w in wallets if w.review_state == "accepted"]

    rows: list[WalletWindowRow] = []
    skipped: list[SkippedWallet] = []

    for wallet in accepted:
        # find_evaluation_wallet only returns accepted records -- re-derive
        # via the same semantics rather than trusting our own filter alone,
        # so this stays in lockstep with evaluation_wallets.py if its
        # definition of "accepted and usable" ever grows a new condition.
        confirmed = find_evaluation_wallet(wallets, wallet.network, wallet.address)
        if confirmed is None:
            skipped.append(
                SkippedWallet(wallet.network, wallet.address, "not_accepted_per_registry_semantics")
            )
            continue

        run_dirs = wallet_run_dirs(behavioral_evidence_root, wallet.network, wallet.address)
        if not run_dirs:
            skipped.append(SkippedWallet(wallet.network, wallet.address, "missing_evidence"))
            continue

        for run_dir in run_dirs:
            try:
                run = load_preferred_behavioral_run(run_dir)
            except (BehavioralEvidenceError, KeyError, ValueError) as exc:
                skipped.append(
                    SkippedWallet(
                        wallet.network,
                        wallet.address,
                        f"unreadable_evidence:{run_dir.name}:{exc}",
                    )
                )
                continue

            behavioral_features = compute_behavioral_features_from_run(run, anchor_address=None)

            rows.append(
                build_wallet_window_row(
                    network=wallet.network,
                    address=wallet.address,
                    window_start=run.behavioral_window_start,
                    window_end=run.behavioral_window_end,
                    acquisition_completeness=run.acquisition_completeness,
                    verification_quality="history_only",
                    source_run_ids=(run.run_id,),
                    behavioral_features=behavioral_features,
                    control_category=wallet.control_category,
                    feature_definition_version=feature_definition_version,
                    data_mode=wallet.data_mode,
                    evaluation_source_reference=wallet.source_reference,
                )
            )

    deduped = dedupe_rows(rows)
    snapshot_hash = _snapshot_hash(registry_path, feature_definition_version, deduped)

    return MaterializationResult(
        rows=deduped,
        skipped=skipped,
        snapshot_hash=snapshot_hash,
        feature_definition_version=feature_definition_version,
        registry_path=str(registry_path),
    )


def _snapshot_hash(
    registry_path: Path, feature_definition_version: str, rows: list[WalletWindowRow]
) -> str:
    """A single hash covering the evaluation-registry file content, the
    feature-definition version, and the resulting row set's dedupe keys --
    changes to any of the three change the returned hash, which is exactly
    what makes an unchanged hash a meaningful "nothing here has drifted"
    signal (Stage 3B item 4/5)."""
    hasher = hashlib.sha256()
    hasher.update(registry_path.read_bytes() if registry_path.is_file() else b"")
    hasher.update(b"|feature_definition_version=")
    hasher.update(feature_definition_version.encode())
    for key in sorted(row.dedupe_key for row in rows):
        hasher.update(b"|row=")
        hasher.update("|".join(key).encode())
    return hasher.hexdigest()
