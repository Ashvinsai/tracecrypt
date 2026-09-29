"""TraceCrypt's useful investigative views, adapted to the CFA evidence contract.

This replaces (does not wrap) the unsafe upstream float-based pattern engine and
fixed-confidence campaign correlator. All rules inspect the observed, verified
subgraph only. No rule modifies labels, proves common ownership, identifies a
person, allocates victim funds, or establishes that an offence occurred.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict, deque
from typing import Any, Iterable

VERSION = "unified-rules-2.0"
DISCLAIMER = (
    "Behavioral indicators are investigative leads, not proof of fraud, laundering, "
    "common control, or victim-fund allocation. Missing flags do not mean a wallet is safe."
)
FINAL_STATES = {"confirmed"}  # No provisional/unknown/removed continuation.
RULE_WEIGHTS = {
    "rapid_forwarding": 20, "fan_in": 15, "fan_out": 15,
    "repeated_forwarding": 15, "peeling_like_split": 10,
    "cyclic_topology": 5, "protocol_boundary": 10,
}


def trace_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(dt.UTC) if parsed.tzinfo else None
    except ValueError:
        return None


def _amount(event: dict[str, Any]) -> int | None:
    value = event.get("amount_base_units")
    # A JSON float is already lossy; never round it into a forensic amount.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    if isinstance(value, str) and (not value.isascii() or not value.isdigit()):
        return None
    try:
        number = int(value)
    except (ValueError, TypeError):
        return None
    return number if 0 < number < 2**256 else None


def _asset(event: dict[str, Any], network: str) -> tuple[str, str, int]:
    a = event.get("asset") or {}
    return (network, str(a.get("token_contract") or "native"), int(a.get("decimals", 0)))


def verified_events(trace: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Deduplicate by network-scoped event identity; reject conflicting copies."""
    rows = ([trace["seed_transfer"]] if trace.get("seed_transfer") else []) + list(
        trace.get("observed_transfers") or [])
    network = str((trace.get("seed") or {}).get("network_key", ""))
    unique: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    excluded: dict[str, int] = defaultdict(int)
    for row in rows:
        ref = row.get("event_reference")
        if not isinstance(ref, str) or not ref:
            excluded["missing_event_identity"] += 1
            continue
        if row.get("execution_status") != "success" or row.get("confirmation_state") not in FINAL_STATES:
            excluded["execution_or_finality_unverified"] += 1
            continue
        if _amount(row) is None:
            excluded["non_positive_or_inexact_amount"] += 1
            continue
        if not row.get("from_address") or not row.get("to_address"):
            excluded["missing_participant"] += 1
            continue
        if ref in unique:
            old = unique[ref]
            comparable = ("from_address", "to_address", "amount_base_units", "block_time", "asset", "tx_hash")
            if any(old.get(k) != row.get(k) for k in comparable):
                conflicts.add(ref)
            else:
                excluded["duplicate_event"] += 1
            continue
        # CFA operates on a network-scoped trace. Do not merge raw rows from
        # a different network into the same graph.
        if row.get("network_key", network) != network:
            excluded["different_network"] += 1
            continue
        unique[ref] = row
    for ref in conflicts:
        unique.pop(ref, None)
    excluded["conflicting_event_identity"] += len(conflicts)
    return list(unique.values()), {k: v for k, v in excluded.items() if v}


def _pattern(rule: str, address: str, events: Iterable[dict[str, Any]],
             explanation: str, values: dict[str, Any]) -> dict[str, Any]:
    refs = sorted({e["event_reference"] for e in events})
    identity = hashlib.sha256(f"{rule}|{address}|{'|'.join(refs)}".encode()).hexdigest()[:16]
    return {
        "id": identity, "rule": rule, "address": address,
        "priority_points": RULE_WEIGHTS[rule], "status": "investigative_lead",
        "explanation": explanation, "observed_values": values,
        "event_references": refs, "limitation": DISCLAIMER,
    }


def _has_cycle(adjacency: dict[str, set[str]]) -> bool:
    # Kahn's algorithm is bounded O(V+E), unlike unbounded simple-cycle enumeration.
    indegree = {node: 0 for node in adjacency}
    for targets in adjacency.values():
        for target in targets:
            indegree[target] = indegree.get(target, 0) + 1
    queue = deque(n for n, d in indegree.items() if d == 0)
    seen = 0
    while queue:
        n = queue.popleft()
        seen += 1
        for target in adjacency.get(n, set()):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return seen != len(indegree)


def analyze_trace(trace: dict[str, Any]) -> dict[str, Any]:
    events, excluded = verified_events(trace)
    network = str((trace.get("seed") or {}).get("network_key", ""))
    incoming: dict[tuple[str, tuple], list[dict]] = defaultdict(list)
    outgoing: dict[tuple[str, tuple], list[dict]] = defaultdict(list)
    adjacency: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    for e in events:
        a = _asset(e, network)
        outgoing[(e["from_address"], a)].append(e)
        incoming[(e["to_address"], a)].append(e)
        adjacency[e["from_address"]].add(e["to_address"])
        adjacency.setdefault(e["to_address"], set())
        reverse[e["to_address"]].add(e["from_address"])
    endings = trace.get("branch_endings") or []
    # Only the tracing engine's reviewed supported labels establish a service.
    services = {b["address"] for b in endings if b.get("endpoint_class") == "known_service"
                and b.get("attribution_status") == "supported"
                and (b.get("label") or {}).get("review_state") == "accepted"}
    patterns: list[dict] = []
    intermediaries: list[dict] = []
    for key in sorted(set(incoming) | set(outgoing)):
        address, asset = key
        ins, outs = incoming[key], outgoing[key]
        if address in services:
            continue  # Routine exchange aggregation is not a fraud flag.
        senders = {e["from_address"] for e in ins}
        recipients = {e["to_address"] for e in outs}
        if len(senders) >= 3:
            patterns.append(_pattern("fan_in", address, ins,
                "At least three distinct senders appear in the observed subgraph; ordinary collection services can behave similarly.",
                {"distinct_senders": len(senders), "asset_contract": asset[1]}))
        if len(recipients) >= 3:
            patterns.append(_pattern("fan_out", address, outs,
                "At least three distinct recipients appear in the observed subgraph; payouts and payroll can behave similarly.",
                {"distinct_recipients": len(recipients), "asset_contract": asset[1]}))
        # Match adjacent receive/send observations, each at most once. Do not
        # take abs(time delta), assume timestamps, or add unlike assets.
        ordered = sorted([(e, "in") for e in ins] + [(e, "out") for e in outs],
                         key=lambda item: (_time(item[0].get("block_time")) or dt.datetime.min.replace(tzinfo=dt.UTC),
                                           item[0].get("chain_sequence") or "", item[0]["event_reference"]))
        rapid_pairs = []
        for previous, current in zip(ordered, ordered[1:]):
            a, direction_a = previous
            b, direction_b = current
            if direction_a != "in" or direction_b != "out":
                continue
            ta, tb = _time(a.get("block_time")), _time(b.get("block_time"))
            if not ta or not tb or a.get("ordering_ambiguous") or b.get("ordering_ambiguous"):
                continue
            elapsed = (tb - ta).total_seconds()
            # A strict positive delay prevents fabricated intra-block ordering.
            ai, bi = _amount(a), _amount(b)
            if 0 < elapsed <= 3600 and ai is not None and bi is not None and 85 * ai <= 100 * bi <= 105 * ai:
                rapid_pairs.append((a, b, elapsed))
        if rapid_pairs:
            a, b, elapsed = rapid_pairs[0]
            patterns.append(_pattern("rapid_forwarding", address, (a, b),
                "A similar-sized outgoing transfer followed an incoming transfer within one hour. This is a timing/amount relationship, not allocation proof.",
                {"elapsed_seconds": int(elapsed), "received_base_units": a["amount_base_units"],
                 "sent_base_units": b["amount_base_units"], "asset_contract": asset[1]}))
        if len(rapid_pairs) >= 3:
            patterns.append(_pattern("repeated_forwarding", address,
                [e for pair in rapid_pairs for e in pair[:2]],
                "Three or more distinct receive/send timing pairs were observed; this does not establish exchange control or a sweep role.",
                {"observed_pairs": len(rapid_pairs), "asset_contract": asset[1]}))
        if len(recipients) == 2 and len(outs) == 2:
            small, large = sorted(_amount(e) or 0 for e in outs)
            total = small + large
            times = [_time(e.get("block_time")) for e in outs]
            if total and small * 100 <= total * 10 and all(times) and abs((times[0] - times[1]).total_seconds()) <= 3600:
                patterns.append(_pattern("peeling_like_split", address, outs,
                    "Two unequal outgoing transfers occurred within an hour. A change/payment pattern is an alternative explanation.",
                    {"smaller_base_units": str(small), "larger_base_units": str(large), "asset_contract": asset[1]}))
        if ins and outs:
            facts = []
            if rapid_pairs:
                facts.append("observed_rapid_forwarding")
            if len(senders) >= 3:
                facts.append("observed_fan_in")
            if len(recipients) >= 3:
                facts.append("observed_fan_out")
            intermediaries.append({
                "address": address, "asset_contract": asset[1], "status": "observed_intermediary",
                "factors": facts, "incoming_sources": len(senders), "outgoing_destinations": len(recipients),
                "event_references": sorted({e["event_reference"] for e in ins + outs}),
                "wallet_lifespan": "unknown", "emptied_balance": "unknown",
                "common_control": "not_established", "limitation": DISCLAIMER,
            })
    cycles = _has_cycle(adjacency)
    if cycles:
        patterns.append(_pattern("cyclic_topology", "", [],
            "The observed address graph contains a directed cycle. This is a topology flag, not a proven circular laundering path.", {}))
    for b in endings:
        if b.get("boundary_reason") in ("bridge", "privacy_mechanism", "opaque_contract", "unsupported_asset_change"):
            patterns.append(_pattern("protocol_boundary", b["address"], [],
                "Tracing encountered a declared protocol/asset boundary. Unsupported continuation remains unresolved.",
                {"boundary_reason": b["boundary_reason"]}))
    # Count each rule once per trace: a larger acquired graph must not inflate
    # the score merely by duplicating equivalent local observations.
    active_rules = sorted({p["rule"] for p in patterns})
    points = min(100, sum(RULE_WEIGHTS[r] for r in active_rules))
    priority = "high" if points >= 45 else "medium" if points >= 20 else "low" if points else "unscored"
    nearest = []
    verified_refs = {e["event_reference"] for e in events}
    for b in endings:
        if b["address"] not in services:
            continue
        if b.get("arrival_event_reference") not in verified_refs:
            continue
        if any(ref not in verified_refs for ref in b.get("branch_path", [])):
            continue
        label = b.get("label") or {}
        nearest.append({
            "address": b["address"], "entity_name": label.get("entity_name"),
            "hop_depth": b.get("hop_depth"), "arrival_event_reference": b.get("arrival_event_reference"),
            "branch_path": b.get("branch_path", []), "address_role": label.get("address_role", "unknown"),
            "source_reference": label.get("source_reference"),
            "direct_deposit_role_verified": label.get("address_role") == "deposit",
            "sender_service_control": "not_inferred", "case_amount_basis": b.get("case_amount_basis", "allocation_unknown"),
        })
    nearest.sort(key=lambda b: (b.get("hop_depth") if b.get("hop_depth") is not None else 10**9, b["address"]))
    transfers_by_asset: dict[tuple, dict] = {}
    for e in events:
        key = _asset(e, network)
        item = transfers_by_asset.setdefault(key, {"network": key[0], "token_contract": key[1],
            "decimals": key[2], "observed_transfer_count": 0, "gross_edge_base_units": 0})
        item["observed_transfer_count"] += 1
        item["gross_edge_base_units"] += _amount(e) or 0
    totals = [{**item, "gross_edge_base_units": str(item["gross_edge_base_units"])} for item in transfers_by_asset.values()]
    coverage = (trace.get("scope") or {}).get("coverage_status", "unknown")
    recommendations = [
        {"action": "preserve_evidence", "reason": "Preserve this exact saved trace, its acquisition references and checksums."},
        {"action": "review_scope", "reason": "Review coverage, finality, labels, token identity and incident linkage before relying on any lead."},
    ]
    if nearest:
        recommendations.append({"action": "review_vasp_request", "reason": "A reviewed service boundary was reached. Prepare an information/preservation draft for human review; do not infer an account owner or send automatically."})
    if coverage != "complete_within_scope" or excluded:
        recommendations.append({"action": "resolve_data_gaps", "reason": "Incomplete or unverified observations must be resolved before making a completeness claim."})
    return {
        "version": VERSION, "input_trace_sha256": trace_digest(trace), "disclaimer": DISCLAIMER,
        "data_mode": (trace.get("scope") or {}).get("data_mode", "UNKNOWN"),
        "coverage_status": coverage, "excluded_events": excluded,
        "risk": {"priority": priority, "score": points, "score_kind": "heuristic_triage_points_not_probability",
                 "rules_triggered": active_rules, "trained_model": False},
        "patterns": patterns, "intermediaries": intermediaries, "service_boundaries": nearest,
        "graph_metrics": {"wallet_count": len(adjacency), "transfer_count": len(events),
                          "unique_directed_pairs": sum(len(t) for t in adjacency.values()),
                          "has_directed_cycle": cycles,
                          "junctions": sorted(n for n in adjacency if len(adjacency[n]) >= 3 or len(reverse[n]) >= 3)},
        "observed_volume": totals,
        "volume_note": "Gross edge volume counts the same funds again at each hop. It is not victim loss, unique value, recoverable balance, or a taint allocation.",
        "allocation": "unknown; the defective TraceCrypt haircut calculation is not used",
        "recommendations": recommendations,
    }


def correlate_traces(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exact network/mode-scoped address intersections, not ownership clusters.

    Inputs must already have been organization-authorized by the caller. Shared
    reviewed service/protocol endpoints are excluded globally within each scope,
    and multiple runs of a single case are not counted as multiple complaints.
    """
    scope_addresses: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    excluded: set[tuple[str, str, str]] = set()
    for record in records:
        trace = record["trace"]
        network = (trace.get("seed") or {}).get("network_key", "")
        mode = (trace.get("scope") or {}).get("data_mode", "UNKNOWN")
        case_id = str(record["case_id"])
        events, _ = verified_events(trace)
        for b in trace.get("branch_endings", []):
            if b.get("endpoint_class") == "known_service" or b.get("boundary_reason") in ("bridge", "privacy_mechanism", "opaque_contract"):
                excluded.add((network, mode, b["address"]))
        for e in events:
            for a in (e["from_address"], e["to_address"]):
                scope_addresses[(network, mode, a)][case_id].add(e["event_reference"])
    links = []
    for key, cases in sorted(scope_addresses.items()):
        if len(cases) < 2 or key in excluded:
            continue
        network, mode, address = key
        links.append({
            "network_key": network, "data_mode": mode, "shared_address": address,
            "case_ids": sorted(cases), "case_count": len(cases),
            "evidence_by_case": {c: sorted(refs) for c, refs in sorted(cases.items())},
            "status": "cross_case_investigative_lead", "common_control": "not_established",
            "limitation": "An exact address overlap is not proof of a shared offender or campaign. Shared known service/protocol endpoints are excluded. Missing labels and shared third parties remain possible.",
        })
    return links
