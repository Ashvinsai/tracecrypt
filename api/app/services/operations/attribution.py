"""Rank observed receiving VASPs without inferring the sender's ownership."""
from __future__ import annotations
from collections import defaultdict
from typing import Any
from app.services.tracecrypt_intelligence import analyze_trace, verified_events, trace_digest

VASP_TYPES = {"exchange", "custodial_service", "payment_processor"}


def attribution_summary(trace: dict[str, Any]) -> dict[str, Any]:
    events, excluded = verified_events(trace)
    by_ref = {e["event_reference"]: e for e in events}
    network = trace.get("seed", {}).get("network_key")
    seed = trace.get("seed", {}).get("address")
    candidates = []
    rejected = []
    seen = set()
    for end in trace.get("branch_endings", []):
        label = end.get("label") or {}
        if not (end.get("endpoint_class") == "known_service" and
                end.get("attribution_status") == "supported" and
                label.get("review_state") == "accepted" and
                label.get("assertion_type") == "service_control" and
                label.get("entity_type") in VASP_TYPES and label.get("source_reference")):
            continue
        ref = end.get("arrival_event_reference")
        path = end.get("branch_path") or []
        arrival = by_ref.get(ref)
        if not path or path[-1] != ref or not arrival or arrival.get("to_address") != end.get("address") or any(r not in by_ref for r in path):
            rejected.append({"address": end.get("address"), "reason": "missing_or_unverified_deposit_path"})
            continue
        rows = [by_ref[r] for r in path]
        if (seed and rows[0].get("from_address") != seed) or any(a["to_address"] != b["from_address"] for a, b in zip(rows, rows[1:])):
            rejected.append({"address": end.get("address"), "reason": "disconnected_path"})
            continue
        # Chronology is established by the tracer; this view checks the path
        # continuity, verified evidence references and network/asset identity.
        assets = {e.get("asset", {}).get("token_contract") for e in rows}
        if len(assets) != 1:
            rejected.append({"address": end.get("address"), "reason": "asset_change_without_link_evidence"})
            continue
        key = (end["address"], tuple(path))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "network_key": network, "entity_name": label["entity_name"],
            "entity_type": label["entity_type"], "receiving_address": end["address"],
            "address_role": label.get("address_role", "unknown"),
            "deposit_address_role_verified": label.get("address_role") == "deposit",
            "direct_from_reported_wallet": len(path) == 1,
            "observed_transfer_hops": len(path), "arrival_event_reference": ref,
            "arrival_transaction_hash": arrival.get("tx_hash"),
            "arrival_time": arrival.get("block_time"),
            "observed_receipt_base_units": arrival.get("amount_base_units"),
            "asset": arrival.get("asset"), "path_event_references": path,
            "label_evidence": label, "case_amount_basis": "allocation_unknown",
            "sender_service_control": "not_inferred",
            "account_holder_identity": "requires_authorized_vasp_response",
        })
    candidates.sort(key=lambda c: (c["observed_transfer_hops"], c["arrival_time"] or "", c["receiving_address"], tuple(c["path_event_references"])))
    shortest = candidates[0]["observed_transfer_hops"] if candidates else None
    # Keep all equally near first receiving boundaries, not a misleading single winner.
    nearest = [c for c in candidates if c["observed_transfer_hops"] == shortest]
    intelligence = analyze_trace(trace)
    groups = defaultdict(set)
    for c in candidates:
        groups[(network, c["entity_name"])].add(c["receiving_address"])
    return {"version": "operations-2.0", "input_trace_sha256": trace_digest(trace),
        "status": "receiving_vasp_observed" if candidates else "unresolved",
        "data_mode": trace.get("scope", {}).get("data_mode", "UNKNOWN"),
        "coverage_status": trace.get("scope", {}).get("coverage_status", "unknown"),
        "nearest_within_observed_scope": nearest, "all_first_receiving_boundaries": candidates,
        "minimum_observed_transfer_hops": shortest, "rejected_paths": rejected,
        "excluded_events": excluded, "risk": intelligence["risk"],
        "reviewed_service_groups": [{"network_key": k[0], "entity_name": k[1], "addresses": sorted(v),
            "basis": "accepted sourced service-control labels only; no heuristic common ownership"} for k, v in sorted(groups.items())],
        "limitations": ["Nearest means fewest observed verified transfer hops within this bounded trace, not globally nearest.",
            "The first receiving service stops a path. Downstream pooled-service movements are not attributed to this victim.",
            "A receiving service label does not establish that the sending wallet belongs to that service.",
            "Observed amounts are not recoverable balances or allocated victim losses.",
            "Absence of a matched label is unresolved, not evidence that an address is safe."],
        "recommendations": intelligence["recommendations"]}
