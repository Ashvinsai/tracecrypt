"""Operational status: what is actually built, partial, or blocked.

Two read-only facilities, both grounded in real state rather than aspiration:

* ``build_capabilities`` returns one row per feature, each with a status drawn
  from what the repository and the saved readiness report actually say. It
  never reports a feature as available because it is planned, and it reports
  the anomaly ranker as blocked while no model has been trained.

* ``verify_manifest_hashes`` re-hashes the files a saved bundle's manifest
  lists and compares them to the recorded digests. A match shows the files are
  unchanged since the run; it is not proof the attribution is correct (the
  manifest's own caveat says so, and this module repeats it).

Nothing here contacts a network, reads the database, or writes anything.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

STATUS_AVAILABLE = "available"
STATUS_CONFIGURED = "configured"
STATUS_PARTIAL = "partial"
STATUS_NOT_BUILT = "not_built"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_BLOCKED = "blocked"

STATUS_LABELS = {
    STATUS_AVAILABLE: "available",
    STATUS_CONFIGURED: "configured",
    STATUS_PARTIAL: "partial",
    STATUS_NOT_BUILT: "not built",
    STATUS_NOT_CONFIGURED: "not configured",
    STATUS_BLOCKED: "blocked",
}


def _cap(
    key: str,
    label: str,
    status: str,
    detail: str,
    *,
    implementation_status: str | None = None,
    configuration_status: str = "not_required",
    live_verified: bool = False,
    historical_live_run_recorded: bool = False,
    trained_real_model: bool | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "implementation_status": implementation_status
        or ("not_built" if status == STATUS_NOT_BUILT else "implemented"),
        "configuration_status": configuration_status,
        "live_verified": live_verified,
        "historical_live_run_recorded": historical_live_run_recorded,
    }
    if trained_real_model is not None:
        row["trained_real_model"] = trained_real_model
    return row


def legacy_capabilities(capabilities: list[dict[str, Any]]) -> dict[str, Any]:
    """Adapt canonical capability records to the stable legacy meta fields."""

    by_key = {capability["key"]: capability for capability in capabilities}
    live = by_key["live_acquisition"]
    return {
        "live_tracing": live["configuration_status"] == "configured"
        and live["live_verified"],
        "tracing_engine": by_key["chronological_tracing"]["implementation_status"]
        == "implemented",
        "label_registry": by_key["label_registry"]["implementation_status"] == "implemented",
        "monitoring": (
            "POLLING_ONLY"
            if by_key["monitoring"]["implementation_status"] == "implemented"
            else "NOT BUILT"
        ),
        "evidence_export": by_key["evidence_export"]["implementation_status"] == "implemented",
        "government_connectors": (
            "NOT CONFIGURED"
            if by_key["government_connectors"]["configuration_status"] == "not_configured"
            else by_key["government_connectors"]["status"].upper()
        ),
        "mock_complaint_queue": (
            "MOCK_LOCAL_QUEUE_ONLY"
            if by_key["mock_complaint_queue"]["implementation_status"] == "implemented"
            else "NOT BUILT"
        ),
    }


def capability_details(
    *,
    live_key_configured: bool,
    configured_data_mode: str,
    readiness: Mapping[str, Any] | None = None,
    saved_run_count: int = 0,
    anomaly_evaluation: Mapping[str, Any] | None = None,
    historical_live_run_recorded: bool = False,
    evm_networks: Mapping[str, Mapping[str, bool]] | None = None,
    cctp_historical_recorded: bool = False,
) -> list[dict[str, Any]]:
    """Canonical capability catalog for API and dashboard consumers."""

    return build_capabilities(
        readiness=readiness,
        saved_run_count=saved_run_count,
        live_key_configured=live_key_configured,
        configured_data_mode=configured_data_mode,
        anomaly_evaluation=anomaly_evaluation,
        historical_live_run_recorded=historical_live_run_recorded,
        evm_networks=evm_networks,
        cctp_historical_recorded=cctp_historical_recorded,
    )


def evm_network_states(settings: Any) -> dict[str, dict[str, bool]]:
    """Per-EVM-network facts for ``build_capabilities``, from real state only.

    ``rpc_configured`` is whether *this process* has that network's own RPC
    setting; ``historical_live_run_recorded`` is whether an intact, successful
    LIVE bundle for *that* network is on disk. The two are independent, and
    neither makes the current deployment live-verified.
    """
    from app.adapters.evm import EVM_NETWORKS
    from app.services import demo_presets

    return {
        key: {
            "rpc_configured": settings.evm_rpc_url(key) is not None,
            "historical_live_run_recorded": demo_presets.has_recorded_successful_live_validation(
                network_key=key
            ),
        }
        for key in EVM_NETWORKS
    }


#: Capability key and label per EVM network. ``evm_token_tracing`` keeps its
#: original key (Ethereum, Task 05) so existing consumers are unaffected.
_EVM_CAPABILITY_ROWS: dict[str, tuple[str, str, str]] = {
    "ethereum": ("evm_token_tracing", "Ethereum ERC-20 acquisition and tracing", "Ethereum"),
    "bsc": ("bsc_token_tracing", "BNB Smart Chain BEP-20 acquisition and tracing", "BSC"),
    "base": ("base_token_tracing", "Base ERC-20 acquisition and tracing", "Base"),
}


def _evm_token_capabilities(
    evm_networks: Mapping[str, Mapping[str, bool]],
) -> list[dict[str, Any]]:
    from app.adapters.evm import EVM_NETWORKS

    rows = []
    for network_key, (key, label, short) in _EVM_CAPABILITY_ROWS.items():
        config = EVM_NETWORKS[network_key]
        state = evm_networks.get(network_key) or {}
        configured = bool(state.get("rpc_configured"))
        historical = bool(state.get("historical_live_run_recorded"))
        base = (
            f"Generic EVM JSON-RPC adapter for {config.display_name} (chain id "
            f"{config.chain_id}): chain-id verification, strict Transfer log decoding, "
            "receipt-based execution, provider finalized/safe finality classification "
            "(unknown when unsupported, never a confirmation-count fallback), bounded "
            "eth_getLogs range splitting and timestamp<->block resolution, reusing the "
            "same chronological tracer as TRON. "
        )
        evidence = (
            f"A bounded, real {config.display_name} LIVE acquisition succeeded and was "
            "replayed offline through the same adapter with zero network calls "
            "(var/live-validation/). This is one historical validation, not a "
            "continuously live-verified deployment: the current endpoint may differ "
            "and no recurring live check exists. "
            if historical
            else f"No bounded {config.display_name} LIVE validation bundle is on file; "
            "live_verified stays false until one is run. "
        )
        configuration = (
            f"{config.rpc_env_var} is configured in this process. "
            if configured
            else f"{config.rpc_env_var} is not configured in this process. "
        )
        scope = (
            f"Native {config.native_symbol} value transfers, internal calls, other EVM "
            f"chains, cross-chain continuation, and a {short} VASP termination are out "
            "of scope."
        )
        rows.append(
            _cap(
                key,
                label,
                STATUS_PARTIAL,
                base + evidence + configuration + scope,
                implementation_status="implemented",
                configuration_status="configured" if configured else "not_configured",
                live_verified=False,
                historical_live_run_recorded=historical,
            )
        )
    return rows


def build_capabilities(
    *,
    readiness: Mapping[str, Any] | None,
    saved_run_count: int,
    live_key_configured: bool,
    configured_data_mode: str,
    anomaly_evaluation: Mapping[str, Any] | None = None,
    historical_live_run_recorded: bool = False,
    #: Per EVM network (``evm_network_states``): ``rpc_configured`` and
    #: ``historical_live_run_recorded``. Separate from the TRON-scoped
    #: ``historical_live_run_recorded`` above: one network's bundle must never
    #: credit another network's capability.
    evm_networks: Mapping[str, Mapping[str, bool]] | None = None,
    cctp_historical_recorded: bool = False,
) -> list[dict[str, Any]]:
    """One row per capability, with a status derived from real state.

    ``readiness`` is the saved evaluation-readiness report (or None).
    ``anomaly_evaluation`` is the saved Stage 3C evaluation report (or None).
    The ranker is ``partial``: the code exists and runs, but it has only been
    demonstrated on SYNTHETIC rows, no model has been trained on real data, and
    no real-corpus accuracy/precision/recall/AUC figure is produced here.
    """

    readiness = readiness or {}
    evm_networks = evm_networks or {}
    evm_evidence = (
        ", ".join(
            key
            for key in _EVM_CAPABILITY_ROWS
            if (evm_networks.get(key) or {}).get("historical_live_run_recorded")
        )
        or "none"
    )
    ready_to_train = readiness.get("no_model_trained_in_this_report") is False
    readiness_status = str(readiness.get("status") or "NOT_READY_FOR_REAL_EVALUATION")
    real_wallets = readiness.get("real_wallet_count", 0)
    materialized = readiness.get("materialized_window_count_real", 0)
    split_feasible = readiness.get("model_dataset_split_feasible", False)
    saved_evaluation_kind = str((anomaly_evaluation or {}).get("evaluation_kind") or "")
    saved_evaluation_label = saved_evaluation_kind.replace("_", " ")

    if live_key_configured and configured_data_mode == "LIVE":
        live_status = STATUS_CONFIGURED
        live_configuration_status = "configured"
        live_detail = (
            "A TronGrid key is configured and the process is in LIVE mode. "
            "Current live verification is not implied by configuration. "
            + (
                "A successful historical LIVE validation bundle is on file; "
                "it does not verify current credentials or provider availability."
                if historical_live_run_recorded
                else "No successful historical LIVE validation bundle is verified."
            )
        )
    elif live_key_configured:
        live_status = STATUS_PARTIAL
        live_configuration_status = "not_configured"
        live_detail = (
            f"A TronGrid key is configured, but the process is in "
            f"{configured_data_mode} mode; live acquisition would need "
            "CFA_DATA_MODE=LIVE."
        )
    else:
        live_status = STATUS_NOT_CONFIGURED
        live_configuration_status = "not_configured"
        live_detail = (
            "No TronGrid key is configured; live tracing is disabled rather "
            "than run unauthenticated."
        )

    # The ranker is implemented and can fit/score, but only against synthetic
    # data: partial, never available, until a real model exists.
    ml_status = STATUS_PARTIAL
    if saved_evaluation_kind:
        ml_detail = (
            f"An Isolation Forest ranker (scikit-learn) is implemented and a "
            f"{saved_evaluation_label} evaluation is saved. No model has been "
            "trained on real data and no real-corpus metric is reported."
        )
    else:
        ml_detail = (
            "An Isolation Forest ranker (scikit-learn) is implemented and runs as "
            "a SYNTHETIC pipeline demonstration. No model has been trained on real "
            "data and no real-corpus metric is reported."
        )
    if ready_to_train:
        ml_detail += " The readiness report now says the corpus is usable."

    if saved_evaluation_kind:
        held_status = STATUS_PARTIAL
        held_detail = (
            f"A held-out precision@k evaluation is saved ({saved_evaluation_label}). It "
            "is review-prioritization only -- not a real-corpus accuracy claim -- and "
            "no real model has been trained."
        )
    else:
        held_status = STATUS_PARTIAL
        held_detail = (
            "Held-out precision@k and confounder machinery exists and runs on the "
            "synthetic demonstration; no evaluation report has been saved and no "
            "real corpus is ready."
        )

    # Monitoring code exists and is tested offline, but no live poll has ever
    # run against the real provider: partial, never available (D029).
    monitoring_detail = (
        "Checkpointed polling of the watched TRC-20 asset with idempotent, "
        "database-deduplicated alerts (scripts/poll_watches.py --once; "
        "/api/v1/cases/{id}/watches). Tested offline on SYNTHETIC and "
        "RECORDED_PUBLIC data. Polling of indexed provider history -- not a "
        "mempool feed; an explicit local evidence outbox can write pending "
        "investigator notification packages, but nothing is sent externally. "
    )
    if live_key_configured and configured_data_mode == "LIVE":
        monitoring_detail += (
            "Live polling is configured but has not been verified against the "
            "real provider here."
        )
    else:
        monitoring_detail += "Live polling is not configured (needs a TronGrid key and LIVE mode)."

    corpus_status = STATUS_PARTIAL
    corpus_detail = (
        f"{real_wallets} real evaluation wallet(s) on file, {materialized} "
        f"materialized window(s); model dataset split feasible={split_feasible}; "
        f"readiness {readiness_status}."
    )

    return [
        _cap(
            "case_intake",
            "Authenticated complaint/case seed intake",
            STATUS_PARTIAL,
            "Organization-scoped case and address/incident seed APIs are implemented; "
            "transaction hash and event references are not persisted, and real "
            "complaint-system intake is not connected.",
        ),
        _cap(
            "tron_acquisition",
            "TRON acquisition adapter",
            live_status,
            "TRON/TRC-20 history, receipt verification, pagination, and recorded replay "
            "are implemented; live operation requires LIVE mode and a configured key.",
            configuration_status=live_configuration_status,
            live_verified=False,
            historical_live_run_recorded=historical_live_run_recorded,
        ),
        _cap(
            "chronological_tracing",
            "Chronological tracing engine",
            STATUS_AVAILABLE,
            "Bounded forward walk over event/path state; saved trace results exist.",
            live_verified=False,
        ),
        _cap(
            "label_registry",
            "Reviewed label registry",
            STATUS_AVAILABLE,
            "CSV-backed accepted service claims with review state and dated validity.",
            configuration_status="configured",
        ),
        _cap(
            "uncertainty_reporting",
            "Uncertainty and boundary reporting",
            STATUS_AVAILABLE,
            "Coverage gaps, unresolved branches, ordering uncertainty, execution, "
            "attribution, and allocation_unknown are carried into reports.",
        ),
        _cap(
            "service_outcome",
            "Service-outcome classification (Stage 3A)",
            STATUS_AVAILABLE,
            "Per-claim outcome layer; the eight status axes stay separate.",
        ),
        _cap(
            "evidence_export",
            "Printable and JSON evidence export",
            STATUS_AVAILABLE,
            "POST /api/v1/traces/export: a zip of the deterministic HTML report, "
            "a generated PDF rendered from that same HTML, per-table CSV files, "
            "and a checksum manifest (Stage 4, D026).",
        ),
        _cap(
            "legal_request_drafts",
            "Draft information/preservation/asset-restriction requests",
            STATUS_AVAILABLE,
            "POST /api/v1/traces/legal-request-draft: field checklist sourced "
            "from OKX's own published LEA request guide; an asset-restriction "
            "draft against a pooled-role or role-unknown address is refused, "
            "not silently drafted (Stage 4, D027). Nothing is ever sent.",
        ),
        _cap(
            "fund_flow_visualization",
            "Saved-trace fund-flow visualization",
            STATUS_AVAILABLE,
            "Server-rendered graph visualizes observed edges from saved, allow-listed "
            "traces; no live tracing occurs on the graph route.",
        ),
        _cap(
            "saved_run_explorer",
            "Saved-run explorer and dashboard",
            STATUS_AVAILABLE,
            f"{saved_run_count} saved run(s) on file.",
        ),
        _cap(
            "data_mode_enforcement",
            "Data-mode enforcement",
            STATUS_AVAILABLE,
            "LIVE / RECORDED PUBLIC / SYNTHETIC are distinct; a saved file is never shown as LIVE.",
        ),
        _cap(
            "live_acquisition",
            "Live TRON acquisition",
            live_status,
            live_detail,
            configuration_status=live_configuration_status,
            live_verified=False,
            historical_live_run_recorded=historical_live_run_recorded,
        ),
        _cap(
            "bundle_integrity",
            "Saved-bundle integrity check",
            STATUS_AVAILABLE,
            "Manifest SHA-256 digests are re-verified on the dashboard.",
        ),
        _cap("monitoring", "New-event monitoring and alerts", STATUS_PARTIAL, monitoring_detail),
        _cap(
            "investigator_notification_outbox",
            "Investigator notification outbox",
            STATUS_PARTIAL,
            "Writes pending, checksummed local notification packages; there is no "
            "external email, webhook, queue, or agency delivery.",
        ),
        _cap(
            "ml_anomaly_ranking",
            "ML anomaly ranking (Isolation Forest)",
            ml_status,
            ml_detail,
            trained_real_model=False,
        ),
        _cap(
            "held_out_evaluation",
            "Held-out precision / coverage evaluation",
            held_status,
            held_detail,
        ),
        _cap("evaluation_corpus", "Evaluation corpus", corpus_status, corpus_detail),
        _cap(
            "government_connectors",
            "Government connectors",
            STATUS_NOT_CONFIGURED,
            "NCRP / SAHYOG and similar remain NOT CONFIGURED by policy -- no real "
            "portal, credential, or agency data-sharing agreement exists.",
            implementation_status="not_built",
            configuration_status="not_configured",
        ),
        _cap(
            "mock_complaint_queue",
            "Local complaint intake",
            STATUS_PARTIAL,
            "GET /api/v1/complaints/mock: a fixed, fictional local fixture "
            "(fixtures/mock_complaints.json), not a live connector to NCRP, "
            "SAHYOG, or any real portal (D028). A seed-draft endpoint shapes a "
            "suggested case seed; nothing is created automatically.",
        ),
        _cap(
            "multi_chain",
            "Additional networks",
            STATUS_PARTIAL,
            "TRON plus a generic EVM JSON-RPC adapter serving Ethereum Mainnet and BNB "
            "Smart Chain Mainnet token Transfer-log tracing through the same "
            f"chronological tracer (api/app/adapters/evm.py). Historical LIVE + replay "
            f"bundles on file: {evm_evidence}. See evm_token_tracing and "
            "bsc_token_tracing. Other ecosystems, native-value/internal-call tracing, "
            "and cross-chain continuation are not supported.",
            implementation_status="implemented",
        ),
        *_evm_token_capabilities(evm_networks),
        _cap(
            "wallet_clustering",
            "VASP-neighborhood candidate discovery",
            STATUS_PARTIAL,
            "Bounded TRON/TRC-20 USDT reports surface address-specific deposit leads "
            "and unresolved candidate relationships around a reviewed anchor; the saved "
            "public discovery yielded one unreviewed, single-event deposit lead and one "
            "anchor with zero candidates. These are not ownership clusters; no candidate "
            "establishes service control or terminates a trace.",
        ),
        _cap(
            "bridge_tracing",
            "Bridge and cross-chain continuation",
            STATUS_PARTIAL,
            (
                "Protocol-verifiable Circle CCTP V2 continuation is implemented for "
                "Ethereum Mainnet -> Base Mainnet USDC transfers. Source burn, Iris API "
                "attestation, and Base destination receive/mint are reconciled. "
                + (
                    "A historical LIVE validation bundle is on file. "
                    if cctp_historical_recorded
                    else "No historical LIVE validation bundle is on file. "
                )
                + "Other bridges, protocols, and asset changes remain unsupported boundaries."
            ),
            implementation_status="partial",
            historical_live_run_recorded=cctp_historical_recorded,
        ),
        _cap(
            "system1_investigation_routing",
            "System-1 investigation routing (CLM)",
            STATUS_PARTIAL,
            "Optional System-1 action-ranking layer with deterministic eligibility filter, "
            "deterministic policy guard, and rules-authoritative execution. CLM operates "
            "in shadow mode and cannot modify blockchain evidence or attribution claims.",
            implementation_status="implemented",
            configuration_status="not_configured",
            live_verified=False,
        ),
    ]


def verify_manifest_hashes(
    manifest: Mapping[str, Any] | None,
    base_dir: Path | None,
) -> dict[str, Any]:
    """Re-hash the files a manifest lists and compare to the recorded digests.

    Returns per-file status plus counts. A mismatched or missing file is
    reported, never silently ignored.
    """

    if not manifest or base_dir is None:
        return {"checked": 0, "ok": 0, "failed": 0, "missing": 0, "files": [], "available": False}

    files = manifest.get("files") or {}
    rows: list[dict[str, Any]] = []
    ok = failed = missing = 0
    for relative, expected in sorted(files.items()):
        path = base_dir / relative
        actual: str | None = None
        if not path.is_file():
            status = "missing"
            missing += 1
        else:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual == expected:
                status = "ok"
                ok += 1
            else:
                status = "mismatch"
                failed += 1
        rows.append(
            {
                "file": relative,
                "expected": expected,
                "actual": actual,
                "status": status,
            }
        )
    return {
        "checked": len(files),
        "ok": ok,
        "failed": failed,
        "missing": missing,
        "files": rows,
        "available": True,
        "caveat": manifest.get("caveat"),
    }
