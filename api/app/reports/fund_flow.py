"""Fund-flow graph over one saved trace result (Stage 4 console).

``build_fund_flow`` turns a trace result into a directed multigraph: one node per
distinct wallet, one edge per observed transfer (the seed transfer included).
It is a pure function with a deterministic layout, so the same saved result
always draws the same picture.

What the graph is, and is not:

* Edges are observed token transfers only. Resource delegations, TRX funding,
  and inferred control relationships are separate evidence and are not drawn,
  so they can never be mistaken for a transfer.
* Two transfers between the same wallets stay two edges; a wallet reached by two
  branches stays one node. Nothing is merged by transaction hash.
* Amounts stay the exact strings the trace saved. Nothing is summed: a sum of
  drawn transfers is not a case-attributable amount (``allocation_unknown``).
* Left-to-right position is hop order, not a claim about chain order. A
  transfer whose ordering the source could not establish is drawn dashed.
* A node's colour comes from the branch ending the tracer recorded for it. A
  candidate lead is never drawn as a supported service.

Every string from the trace is untrusted and is escaped here; the embedded JSON
escapes ``<``, ``>`` and ``&`` so it cannot close its own script element.
"""

from __future__ import annotations

import html
import json
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

NODE_W = 196
NODE_H = 60
#: Column width leaves ~160 px between boxes for an amount label.
COL_W = NODE_W + 160
ROW_H = 96
PAD = 28
#: Above this many edges, per-edge amount labels are hidden to stay legible.
LABEL_EDGE_LIMIT = 60

#: Display names for the endpoint classes the tracer records. Anything else is
#: shown under its own name, styled as a generic boundary.
ROLE_LABELS = {
    "seed": "Seed / case link",
    "wallet": "Intermediate wallet",
    "known_service": "Supported service boundary",
    "deposit_candidate": "Candidate lead (not verified)",
    "unresolved": "Unresolved / boundary",
    "mixed": "Conflicting branch endings",
}
STYLED_ROLES = frozenset(ROLE_LABELS)


@dataclass(frozen=True)
class FlowEdge:
    index: int
    event_reference: str
    tx_hash: str | None
    source: str
    target: str
    amount_display: str | None
    amount_base_units: str | None
    symbol: str
    block_time: str | None
    ordering_ambiguous: bool
    execution_status: str | None
    confirmation_state: str | None
    hop_depth: Any
    is_seed: bool
    #: Set when the saved result predates ``seed_transfer`` and this edge was
    #: reconstructed from a branch ending's arrival event (the seed event).
    derived_from: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "event_reference": self.event_reference,
            "tx_hash": self.tx_hash,
            "from": self.source,
            "to": self.target,
            "amount_display": self.amount_display,
            "amount_base_units": self.amount_base_units,
            "symbol": self.symbol,
            "block_time": self.block_time,
            "ordering_ambiguous": self.ordering_ambiguous,
            "execution_status": self.execution_status,
            "confirmation_state": self.confirmation_state,
            "hop_depth": self.hop_depth,
            "is_seed_transfer": self.is_seed,
            "derived_from": self.derived_from,
        }


@dataclass
class FlowNode:
    index: int
    address: str
    role: str = "wallet"
    endpoint_classes: list[str] = field(default_factory=list)
    entity_name: str | None = None
    boundary_reasons: list[str] = field(default_factory=list)
    attribution_statuses: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    branches: list[int] = field(default_factory=list)
    #: Branches the tracer ended here because they rejoined an explored path.
    reconverged_branches: list[int] = field(default_factory=list)
    incoming: list[int] = field(default_factory=list)
    outgoing: list[int] = field(default_factory=list)
    layer: int = 0
    order: int = 0
    x: int = 0
    y: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "address": self.address,
            "role": self.role,
            "role_label": ROLE_LABELS.get(self.role, self.role.replace("_", " ")),
            "endpoint_classes": self.endpoint_classes,
            "entity_name": self.entity_name,
            "boundary_reasons": self.boundary_reasons,
            "attribution_statuses": self.attribution_statuses,
            "notes": self.notes,
            "branches": self.branches,
            "reconverged_branches": self.reconverged_branches,
            "incoming": self.incoming,
            "outgoing": self.outgoing,
            "hop_layer": self.layer,
        }


@dataclass
class FundFlowGraph:
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    branches: list[dict[str, Any]]
    warnings: list[str]
    acyclic: bool
    width: int
    height: int

    @property
    def is_empty(self) -> bool:
        return not self.edges

    def stats(self) -> dict[str, int]:
        endings = [b["endpoint_class"] for b in self.branches]
        reconverged = sum(len(n.reconverged_branches) for n in self.nodes)
        return {
            "wallets": len(self.nodes),
            "transfers": len(self.edges),
            "branches": len(self.branches),
            "supported_boundaries": endings.count("known_service"),
            "candidate_leads": endings.count("deposit_candidate"),
            "unresolved": endings.count("unresolved") - reconverged,
            "reconverged": reconverged,
            "max_hop_layer": max((n.layer for n in self.nodes), default=0),
            "ordering_ambiguous": sum(1 for e in self.edges if e.ordering_ambiguous),
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_json() for n in self.nodes],
            "edges": [e.to_json() for e in self.edges],
            "branches": self.branches,
            "warnings": self.warnings,
            "acyclic": self.acyclic,
            "stats": self.stats(),
            "drawn": "observed token transfers only",
        }


# -- building ------------------------------------------------------------------


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _edge(index: int, raw: Mapping[str, Any], *, is_seed: bool) -> FlowEdge:
    asset = raw.get("asset") or {}
    return FlowEdge(
        index=index,
        event_reference=str(raw.get("event_reference")),
        tx_hash=_text(raw.get("tx_hash")),
        source=str(raw.get("from_address")),
        target=str(raw.get("to_address")),
        amount_display=_text(raw.get("amount_display")),
        amount_base_units=_text(raw.get("amount_base_units")),
        symbol=str(asset.get("display_symbol") or ""),
        block_time=_text(raw.get("block_time")),
        ordering_ambiguous=bool(raw.get("ordering_ambiguous")),
        execution_status=_text(raw.get("execution_status")),
        confirmation_state=_text(raw.get("confirmation_state")),
        hop_depth=raw.get("hop_depth"),
        is_seed=is_seed,
    )


def build_fund_flow(trace: Mapping[str, Any]) -> FundFlowGraph:
    """Build the graph model from one saved trace result. Never raises on gaps."""

    warnings: list[str] = []
    seed = trace.get("seed") or {}
    seed_address = _text(seed.get("address"))
    seed_transfer = trace.get("seed_transfer")

    raw_edges: list[tuple[Mapping[str, Any], bool]] = []
    if isinstance(seed_transfer, Mapping):
        raw_edges.append((seed_transfer, True))
    for item in trace.get("observed_transfers") or []:
        if isinstance(item, Mapping):
            raw_edges.append((item, False))

    edges: list[FlowEdge] = []
    seen_refs: set[str] = set()
    for raw, is_seed in raw_edges:
        ref = _text(raw.get("event_reference"))
        if ref is None:
            warnings.append("A saved transfer has no event reference and is not drawn.")
            continue
        if ref in seen_refs:
            continue
        if not raw.get("from_address") or not raw.get("to_address"):
            warnings.append(f"Transfer {ref} is missing a sender or recipient and is not drawn.")
            continue
        seen_refs.add(ref)
        edges.append(_edge(len(edges), raw, is_seed=is_seed))

    nodes_by_address: dict[str, FlowNode] = {}

    def node(address: str) -> FlowNode:
        found = nodes_by_address.get(address)
        if found is None:
            found = FlowNode(index=len(nodes_by_address), address=address)
            nodes_by_address[address] = found
        return found

    if seed_address:
        node(seed_address).role = "seed"
    for edge in edges:
        node(edge.source).outgoing.append(edge.index)
        node(edge.target).incoming.append(edge.index)

    _derive_seed_edges(trace, edges, seed_address, node)

    edge_by_ref = {e.event_reference: e.index for e in edges}
    branches: list[dict[str, Any]] = []
    for number, ending in enumerate(trace.get("branch_endings") or [], start=1):
        if not isinstance(ending, Mapping):
            continue
        address = _text(ending.get("address"))
        endpoint_class = str(ending.get("endpoint_class") or "unresolved")
        path = [str(ref) for ref in ending.get("branch_path") or []]
        branches.append(
            {
                "number": number,
                "address": address,
                "endpoint_class": endpoint_class,
                "attribution_status": ending.get("attribution_status"),
                "boundary_reason": ending.get("boundary_reason"),
                "hop_depth": ending.get("hop_depth"),
                "event_references": path,
                "edges": [edge_by_ref[ref] for ref in path if ref in edge_by_ref],
                "undrawn_references": [ref for ref in path if ref not in edge_by_ref],
            }
        )
        if address is None:
            warnings.append(f"Branch {number} records no ending address.")
            continue
        target = node(address)
        target.branches.append(number)
        if endpoint_class == "unresolved" and not ending.get("boundary_reason") and target.outgoing:
            # The tracer records a branch that rejoined an already-explored path
            # as an ending with no boundary reason. Transfers continue from this
            # wallet, so it is a reconvergence point, not a boundary.
            target.reconverged_branches.append(number)
        elif endpoint_class not in target.endpoint_classes:
            target.endpoint_classes.append(endpoint_class)
        label = ending.get("label") or {}
        if isinstance(label, Mapping) and label.get("entity_name"):
            target.entity_name = str(label["entity_name"])
        for key, bucket in (
            ("boundary_reason", target.boundary_reasons),
            ("attribution_status", target.attribution_statuses),
            ("note", target.notes),
        ):
            value = _text(ending.get(key))
            if value is not None and value not in bucket:
                bucket.append(value)

    for n in nodes_by_address.values():
        if n.role == "seed" or not n.endpoint_classes:
            continue
        if len(n.endpoint_classes) == 1:
            n.role = n.endpoint_classes[0]
        else:
            # Two branches ended here differently. Show the conflict rather
            # than letting the stronger class win (D006).
            n.role = "mixed"
            warnings.append(
                f"{n.address} ends branches as {', '.join(n.endpoint_classes)}; "
                "drawn as conflicting."
            )

    for branch in branches:
        if branch["undrawn_references"]:
            warnings.append(
                f"Branch {branch['number']} names {len(branch['undrawn_references'])} "
                "transfer(s) that are not in the saved transfer list."
            )

    nodes = list(nodes_by_address.values())
    acyclic = _assign_layers(nodes, edges, seed_address, warnings)
    _order_within_layers(nodes, edges)
    width, height = _place(nodes)
    return FundFlowGraph(
        nodes=nodes,
        edges=edges,
        branches=branches,
        warnings=warnings,
        acyclic=acyclic,
        width=width,
        height=height,
    )


def _derive_seed_edges(
    trace: Mapping[str, Any],
    edges: list[FlowEdge],
    seed_address: str | None,
    node: Any,
) -> None:
    """Reconstruct the seed transfer for results saved before ``seed_transfer``.

    Only when a branch ending's arrival event *is* the seed event: then the
    sender is the seed address and the recipient and amount are the ending's
    own recorded facts. Any other missing event stays undrawn and is reported,
    because its sender is not known.
    """
    seed_event = _text((trace.get("seed") or {}).get("event_reference"))
    if seed_address is None or seed_event is None:
        return
    if any(e.event_reference == seed_event for e in edges):
        return
    asset = (trace.get("seed") or {}).get("asset") or {}
    for ending in trace.get("branch_endings") or []:
        if not isinstance(ending, Mapping) or ending.get("arrival_event_reference") != seed_event:
            continue
        target = _text(ending.get("address"))
        if target is None:
            continue
        edge = FlowEdge(
            index=len(edges),
            event_reference=seed_event,
            tx_hash=seed_event.split(":")[1] if seed_event.count(":") >= 2 else None,
            source=seed_address,
            target=target,
            amount_display=_text(ending.get("observed_amount_display")),
            amount_base_units=_text(ending.get("observed_amount_base_units")),
            symbol=str(asset.get("display_symbol") or ""),
            block_time=None,
            ordering_ambiguous=False,
            execution_status=None,
            confirmation_state=None,
            hop_depth=ending.get("hop_depth"),
            is_seed=True,
            derived_from=(
                "the branch ending's arrival event: this saved result predates the "
                "seed_transfer field, so time and execution are not recorded here"
            ),
        )
        edges.append(edge)
        node(edge.source).outgoing.append(edge.index)
        node(edge.target).incoming.append(edge.index)
        return


def _assign_layers(
    nodes: list[FlowNode], edges: list[FlowEdge], seed: str | None, warnings: list[str]
) -> bool:
    index = {n.address: n for n in nodes}
    successors: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {n.address: 0 for n in nodes}
    for e in edges:
        if e.source == e.target:
            continue
        successors[e.source].append(e.target)
        indegree[e.target] += 1

    # Longest-path layering when the wallet graph is acyclic: every edge then
    # points left to right. With a cycle, fall back to breadth-first distance.
    queue = deque(sorted((a for a, d in indegree.items() if d == 0), key=lambda a: index[a].index))
    remaining = dict(indegree)
    topo: list[str] = []
    while queue:
        current = queue.popleft()
        topo.append(current)
        for nxt in successors[current]:
            remaining[nxt] -= 1
            if remaining[nxt] == 0:
                queue.append(nxt)
    acyclic = len(topo) == len(nodes)

    layer: dict[str, int] = {}
    if acyclic:
        for address in topo:
            layer.setdefault(address, 0)
            for nxt in successors[address]:
                layer[nxt] = max(layer.get(nxt, 0), layer[address] + 1)
    else:
        warnings.append(
            "The observed transfers revisit a wallet (a cycle); layers show "
            "breadth-first hop distance, so some edges point backwards."
        )
        start = seed if seed in index else (nodes[0].address if nodes else None)
        if start is not None:
            layer[start] = 0
            frontier = deque([start])
            while frontier:
                current = frontier.popleft()
                for nxt in successors[current]:
                    if nxt not in layer:
                        layer[nxt] = layer[current] + 1
                        frontier.append(nxt)
        unreached = [n for n in nodes if n.address not in layer]
        deepest = max(layer.values(), default=0)
        for n in unreached:
            layer[n.address] = deepest + 1

    if seed in index:
        reachable = {seed}
        frontier = deque([seed])
        while frontier:
            current = frontier.popleft()
            for nxt in successors[current]:
                if nxt not in reachable:
                    reachable.add(nxt)
                    frontier.append(nxt)
        stray = [n.address for n in nodes if n.address not in reachable]
        if stray:
            warnings.append(
                f"{len(stray)} wallet(s) are not connected to the seed by a saved transfer."
            )

    for n in nodes:
        n.layer = layer.get(n.address, 0)
    return acyclic


def _order_within_layers(nodes: list[FlowNode], edges: list[FlowEdge]) -> None:
    by_layer: dict[int, list[FlowNode]] = defaultdict(list)
    for n in nodes:
        by_layer[n.layer].append(n)
    index = {n.address: n for n in nodes}
    predecessors: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.source != e.target:
            predecessors[e.target].append(e.source)

    for layer in sorted(by_layer):
        members = sorted(by_layer[layer], key=lambda n: n.index)
        for position, n in enumerate(members):
            n.order = position
    # Two barycentre sweeps: pull each wallet towards its senders to reduce crossings.
    for _ in range(2):
        for layer in sorted(by_layer):
            members = by_layer[layer]

            def key(n: FlowNode) -> tuple[float, int]:
                preds = [index[p] for p in predecessors[n.address] if index[p].layer < n.layer]
                if not preds:
                    return (float(n.order), n.index)
                return (sum(p.order for p in preds) / len(preds), n.index)

            for position, n in enumerate(sorted(members, key=key)):
                n.order = position


def _place(nodes: list[FlowNode]) -> tuple[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for n in nodes:
        counts[n.layer] += 1
    tallest = max(counts.values(), default=1)
    layers = max(counts, default=0) + 1
    for n in nodes:
        offset = (tallest - counts[n.layer]) * ROW_H // 2
        n.x = PAD + n.layer * COL_W
        n.y = PAD + offset + n.order * ROW_H
    width = PAD * 2 + (layers - 1) * COL_W + NODE_W
    height = PAD * 2 + (tallest - 1) * ROW_H + NODE_H + 60
    return width, height


# -- rendering -------------------------------------------------------------------


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def short(value: Any, keep: int = 16) -> str:
    text = "" if value is None else str(value)
    if len(text) <= keep:
        return text
    head = (keep - 1) // 2 + 1
    tail = keep - 1 - head
    return f"{text[:head]}…{text[-tail:]}" if tail > 0 else f"{text[:head]}…"


def _role_class(role: str) -> str:
    return role if role in STYLED_ROLES else "boundary"


def _node_title(n: FlowNode) -> str:
    if n.role == "known_service" and n.entity_name:
        return n.entity_name
    return ROLE_LABELS.get(n.role, n.role.replace("_", " "))


def _node_subline(n: FlowNode) -> str:
    if n.role == "seed":
        return "hop 0"
    if n.boundary_reasons:
        return f"hop {n.layer} · {n.boundary_reasons[0].replace('_', ' ')}"
    if n.reconverged_branches and not n.endpoint_classes:
        return f"hop {n.layer} · branches reconverge"
    if n.branches:
        return f"hop {n.layer} · branch end"
    return f"hop {n.layer}"


def _edge_geometry(
    edges: Sequence[FlowEdge], nodes: Mapping[str, FlowNode]
) -> dict[int, tuple[str, float, float]]:
    """SVG path data and a label anchor for every edge."""

    groups: dict[tuple[str, str], list[FlowEdge]] = defaultdict(list)
    for e in edges:
        groups[(e.source, e.target)].append(e)

    geometry: dict[int, tuple[str, float, float]] = {}
    x1: float
    y1: float
    x2: float
    y2: float
    for (source, target), members in groups.items():
        a, b = nodes[source], nodes[target]
        count = len(members)
        for k, e in enumerate(members):
            spread = (k - (count - 1) / 2) * 14
            if source == target:
                x, y = a.x + NODE_W, a.y + NODE_H / 2 + spread
                path = f"M{x},{y - 10} C{x + 60},{y - 50} {x + 60},{y + 50} {x},{y + 10}"
                geometry[e.index] = (path, x + 48, y)
            elif b.layer > a.layer:
                x1, y1 = a.x + NODE_W, a.y + NODE_H / 2 + spread
                x2, y2 = b.x, b.y + NODE_H / 2 + spread
                dx = (x2 - x1) / 2
                path = f"M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}"
                geometry[e.index] = (path, (x1 + x2) / 2, (y1 + y2) / 2)
            else:
                # Same layer or backwards (only with a cycle): arc below both.
                x1, y1 = a.x + NODE_W / 2 + spread, a.y + NODE_H
                x2, y2 = b.x + NODE_W / 2 + spread, b.y + NODE_H
                dip = max(y1, y2) + 46 + abs(spread) * 2
                path = f"M{x1},{y1} C{x1},{dip} {x2},{dip} {x2},{y2}"
                geometry[e.index] = (path, (x1 + x2) / 2, dip - 10)
    return geometry


def render_fund_flow_svg(graph: FundFlowGraph) -> str:
    """The graph as inline SVG. Deterministic; every text value escaped."""

    by_address = {n.address: n for n in graph.nodes}
    geometry = _edge_geometry(graph.edges, by_address)
    show_labels = len(graph.edges) <= LABEL_EDGE_LIMIT

    edge_parts: list[str] = []
    for e in graph.edges:
        path, lx, ly = geometry[e.index]
        classes = ["ff-edge"]
        if e.ordering_ambiguous:
            classes.append("ambiguous")
        if e.is_seed:
            classes.append("seed-edge")
        if e.execution_status not in (None, "success"):
            classes.append("exec-unverified")
        if e.derived_from:
            classes.append("derived")
        amount = f"{e.amount_display} {e.symbol}".strip() if e.amount_display else ""
        described = (
            f"Transfer {amount or 'amount not recorded'} from {e.source} to {e.target}"
            f"{' at ' + e.block_time if e.block_time else ''}"
            f"{' (ordering not established)' if e.ordering_ambiguous else ''}"
            f"{' (reconstructed from ' + e.derived_from + ')' if e.derived_from else ''}"
        )
        label = ""
        if show_labels and e.amount_display:
            label = (
                f"<text class='ff-elabel' x='{lx:.1f}' y='{ly - 6:.1f}' text-anchor='middle'>"
                f"{_e(short(e.amount_display, 15))} {_e(e.symbol)}</text>"
            )
        edge_parts.append(
            f"<g class='{' '.join(classes)}' data-edge='{e.index}' tabindex='0' role='button' "
            f"aria-label='{_e(described)}'><title>{_e(described)}\n{_e(e.event_reference)}</title>"
            f"<path class='ff-hit' d='{path}'/>"
            f"<path class='ff-line' d='{path}' marker-end='url(#ff-arrow)'/>{label}</g>"
        )

    node_parts: list[str] = []
    for n in graph.nodes:
        role = _role_class(n.role)
        title = _node_title(n)
        described = f"{title}: {n.address}"
        if n.boundary_reasons:
            described += f" ({', '.join(n.boundary_reasons)})"
        node_parts.append(
            f"<g class='ff-node role-{_e(role)}' data-node='{n.index}' tabindex='0' role='button' "
            f"aria-label='{_e(described)}' transform='translate({n.x},{n.y})'>"
            f"<title>{_e(described)}</title>"
            f"<rect width='{NODE_W}' height='{NODE_H}' rx='9'/>"
            f"<text class='ff-role' x='12' y='18'>{_e(short(title, 30))}</text>"
            f"<text class='ff-addr' x='12' y='36'>{_e(short(n.address, 24))}</text>"
            f"<text class='ff-sub' x='12' y='52'>{_e(short(_node_subline(n), 32))}</text></g>"
        )

    return (
        f"<svg class='ff-svg' xmlns='http://www.w3.org/2000/svg' "
        f"viewBox='0 0 {graph.width} {graph.height}' width='{graph.width}' "
        f"height='{graph.height}' role='group' aria-labelledby='ff-svg-title ff-svg-desc'>"
        "<title id='ff-svg-title'>Fund-flow graph of observed transfers</title>"
        f"<desc id='ff-svg-desc'>{len(graph.nodes)} wallets and {len(graph.edges)} observed "
        "transfers, laid out left to right by hop. Resource delegations and inferred "
        "relationships are not drawn.</desc>"
        "<defs><marker id='ff-arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' "
        "markerHeight='7' orient='auto-start-reverse'><path class='ff-arrowhead' "
        "d='M0,0 L10,5 L0,10 z'/></marker></defs>"
        f"<g class='ff-edges'>{''.join(edge_parts)}</g>"
        f"<g class='ff-nodes'>{''.join(node_parts)}</g></svg>"
    )


def graph_json_script(graph: FundFlowGraph) -> str:
    """The graph model embedded for the page script, safe inside a script element."""

    payload = json.dumps(graph.to_json(), sort_keys=True)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f"<script type='application/json' id='ff-data'>{payload}</script>"


GRAPH_STYLE = """
.ff-layout { display: grid; grid-template-columns: 1fr; gap: 12px; }
.ff-canvas { overflow: auto; border: 1px solid var(--line); border-radius: 10px;
  background: var(--surface-2); max-height: 72vh; }
.ff-svg { display: block; font-family: ui-sans-serif, system-ui, sans-serif; }
.ff-node rect { fill: var(--panel); stroke: var(--line-strong); stroke-width: 1.5; }
.ff-node.role-seed rect { fill: var(--seed-bg); stroke: var(--accent); stroke-width: 2; }
.ff-node.role-known_service rect { fill: var(--green-bg); stroke: var(--green); stroke-width: 2; }
.ff-node.role-deposit_candidate rect { fill: var(--amber-bg); stroke: var(--amber);
  stroke-width: 2; stroke-dasharray: 6 4; }
.ff-node.role-unresolved rect, .ff-node.role-boundary rect { fill: var(--grey-bg);
  stroke: var(--line-strong); }
.ff-node.role-mixed rect { fill: var(--red-bg); stroke: var(--red); stroke-dasharray: 3 3; }
.ff-node text { fill: var(--ink); }
.ff-role { font-size: 11px; font-weight: 700; letter-spacing: .02em; }
.ff-addr { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
.ff-sub { font-size: 10.5px; fill: var(--muted) !important; }
.ff-node, .ff-edge { cursor: pointer; outline: none; }
.ff-node:focus-visible rect, .ff-node.selected rect { stroke: var(--accent); stroke-width: 3; }
.ff-line { fill: none; stroke: var(--muted); stroke-width: 1.8; }
.ff-hit { fill: none; stroke: transparent; stroke-width: 14; }
.ff-edge.seed-edge .ff-line { stroke: var(--accent); stroke-width: 2.4; }
.ff-edge.ambiguous .ff-line { stroke-dasharray: 7 5; }
.ff-edge.exec-unverified .ff-line, .ff-edge.derived .ff-line { stroke-dasharray: 2 4; }
.ff-edge:focus-visible .ff-line, .ff-edge.selected .ff-line {
  stroke: var(--accent); stroke-width: 3.2; }
.ff-arrowhead { fill: var(--muted); }
.ff-elabel { font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; fill: var(--ink);
  paint-order: stroke; stroke: var(--surface-2); stroke-width: 4px; stroke-linejoin: round; }
.ff-svg.has-focus .ff-node:not(.lit), .ff-svg.has-focus .ff-edge:not(.lit) { opacity: .22; }
.ff-controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 0 0 10px; }
.ff-controls select { font: inherit; padding: 5px 8px; border-radius: 6px;
  border: 1px solid var(--line-strong); background: var(--panel); color: var(--ink); }
.ff-details { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px;
  background: var(--panel); font-size: 13px; min-height: 64px; }
.ff-details h3 { margin: 0 0 8px; font-size: 14px; }
.ff-details dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 4px 10px; }
.ff-details dt { color: var(--muted); }
.ff-details dd { margin: 0; overflow-wrap: anywhere; }
.ff-details .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.ff-details ul { margin: 6px 0 0; padding-left: 18px; }
.legend .swatch.mixed { background: var(--red-bg); border-color: var(--red); }
.legend .swatch.wallet { background: var(--panel); border-color: var(--line-strong); }
.legend .swatch.dashed { border-style: dashed; }
.legend .line { display: inline-block; width: 26px; border-top: 2px solid var(--muted);
  vertical-align: middle; margin-right: 6px; }
.legend .line.dashed { border-top-style: dashed; }
.legend .line.seed { border-top-color: var(--accent); }
@media print { .ff-canvas { max-height: none; overflow: visible; } .ff-details { display: none; } }
"""

GRAPH_SCRIPT = """
(function () {
  var dataEl = document.getElementById("ff-data");
  var svg = document.querySelector(".ff-svg");
  if (!dataEl || !svg) { return; }
  var data = JSON.parse(dataEl.textContent);
  var panel = document.getElementById("ff-details");
  var branchSelect = document.getElementById("ff-branch");
  var nodesEl = svg.querySelectorAll(".ff-node");
  var edgesEl = svg.querySelectorAll(".ff-edge");
  var baseW = svg.getAttribute("width"), baseH = svg.getAttribute("height"), zoom = 1;

  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    if (cls) { e.className = cls; }
    return e;
  }
  function row(dl, term, value, mono) {
    if (value === undefined || value === null || value === "") { return; }
    dl.appendChild(el("dt", term));
    dl.appendChild(el("dd", value, mono ? "mono" : ""));
  }
  function clear() {
    svg.classList.remove("has-focus");
    [].forEach.call(svg.querySelectorAll(".lit, .selected"), function (e) {
      e.classList.remove("lit"); e.classList.remove("selected");
    });
  }
  function mark(kind, i, cls) {
    var e = svg.querySelector("[data-" + kind + "='" + i + "']");
    if (e) { e.classList.add(cls); }
  }
  function light(nodeIdx, edgeIdx) {
    clear();
    svg.classList.add("has-focus");
    nodeIdx.forEach(function (i) { mark("node", i, "lit"); });
    edgeIdx.forEach(function (i) { mark("edge", i, "lit"); });
  }
  function nodeIndexOf(address) {
    for (var i = 0; i < data.nodes.length; i++) {
      if (data.nodes[i].address === address) { return i; }
    }
    return -1;
  }
  function transferLine(edge, direction) {
    var who = direction === "in" ? edge.from : edge.to;
    return (direction === "in" ? "from " : "to ") + who + " \\u2014 " +
      (edge.amount_display ? edge.amount_display + " " + edge.symbol : "amount not recorded") +
      (edge.block_time ? " \\u00b7 " + edge.block_time : "") +
      (edge.ordering_ambiguous ? " \\u00b7 ordering not established" : "");
  }
  function showNode(i) {
    var n = data.nodes[i];
    var inc = n.incoming, out = n.outgoing;
    light([i].concat(inc.map(function (k) { return nodeIndexOf(data.edges[k].from); }))
             .concat(out.map(function (k) { return nodeIndexOf(data.edges[k].to); })),
          inc.concat(out));
    mark("node", i, "selected");
    panel.textContent = "";
    var heading = n.entity_name && n.role === "known_service" ? n.entity_name : n.role_label;
    panel.appendChild(el("h3", heading));
    var dl = el("dl");
    row(dl, "Address", n.address, true);
    row(dl, "Role", n.role_label);
    row(dl, "Hop layer", n.hop_layer);
    var ended = n.branches.filter(function (b) { return n.reconverged_branches.indexOf(b) < 0; });
    row(dl, "Branch endings", ended.join(", "));
    row(dl, "Reconverged here", n.reconverged_branches.join(", "));
    row(dl, "Attribution", n.attribution_statuses.join(", "));
    row(dl, "Boundary", n.boundary_reasons.join(", "));
    panel.appendChild(dl);
    var parts = [
      ["Received (" + inc.length + ")", inc, "in"],
      ["Sent (" + out.length + ")", out, "out"]
    ];
    parts.forEach(function (part) {
      if (!part[1].length) { return; }
      panel.appendChild(el("h3", part[0]));
      var ul = el("ul");
      part[1].forEach(function (k) {
        ul.appendChild(el("li", transferLine(data.edges[k], part[2]), "mono"));
      });
      panel.appendChild(ul);
    });
    n.notes.forEach(function (note) { panel.appendChild(el("p", note, "note")); });
    if (n.role === "deposit_candidate") {
      panel.appendChild(el("p", "A candidate lead is not a verified service boundary.", "note"));
    }
  }
  function showEdge(i) {
    var e = data.edges[i];
    light([nodeIndexOf(e.from), nodeIndexOf(e.to)], [i]);
    mark("edge", i, "selected");
    panel.textContent = "";
    panel.appendChild(el("h3", e.is_seed_transfer ? "Seed transfer" : "Observed transfer"));
    var dl = el("dl");
    row(dl, "Event", e.event_reference, true);
    row(dl, "Transaction", e.tx_hash, true);
    row(dl, "From", e.from, true);
    row(dl, "To", e.to, true);
    row(dl, "Amount", e.amount_display ? e.amount_display + " " + e.symbol : "not recorded", true);
    row(dl, "Base units", e.amount_base_units, true);
    row(dl, "Block time", e.block_time);
    row(dl, "Execution", e.execution_status);
    row(dl, "Confirmation", e.confirmation_state);
    var ordering = e.ordering_ambiguous ? "not established by the source" : "established";
    row(dl, "Ordering", e.derived_from ? "not recorded" : ordering);
    row(dl, "Reconstructed from", e.derived_from);
    panel.appendChild(dl);
    panel.appendChild(el("p",
      "A transfer shows movement, not ownership of these specific units.", "note"));
  }
  function reset() {
    clear();
    panel.textContent = "";
    panel.appendChild(el("h3", "Details"));
    panel.appendChild(el("p",
      "Select a wallet or a transfer, or choose a branch above. Esc clears.", "note"));
    if (branchSelect) { branchSelect.value = ""; }
  }
  function activate(ev, fn) {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(); }
  }
  [].forEach.call(nodesEl, function (g) {
    var i = Number(g.getAttribute("data-node"));
    g.addEventListener("click", function () { showNode(i); });
    g.addEventListener("keydown", function (ev) { activate(ev, function () { showNode(i); }); });
  });
  [].forEach.call(edgesEl, function (g) {
    var i = Number(g.getAttribute("data-edge"));
    g.addEventListener("click", function () { showEdge(i); });
    g.addEventListener("keydown", function (ev) { activate(ev, function () { showEdge(i); }); });
  });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") { reset(); } });
  if (branchSelect) {
    branchSelect.addEventListener("change", function () {
      if (!branchSelect.value) { reset(); return; }
      var b = data.branches[Number(branchSelect.value)];
      var nodeIdx = [];
      b.edges.forEach(function (k) {
        nodeIdx.push(nodeIndexOf(data.edges[k].from));
        nodeIdx.push(nodeIndexOf(data.edges[k].to));
      });
      if (b.address) { nodeIdx.push(nodeIndexOf(b.address)); }
      light(nodeIdx, b.edges);
      panel.textContent = "";
      panel.appendChild(el("h3", "Branch " + b.number));
      var dl = el("dl");
      row(dl, "Ends at", b.address, true);
      row(dl, "Outcome", b.endpoint_class);
      row(dl, "Attribution", b.attribution_status);
      row(dl, "Boundary", b.boundary_reason);
      row(dl, "Transfers", b.edges.length);
      panel.appendChild(dl);
      if (b.undrawn_references.length) {
        panel.appendChild(el("p", b.undrawn_references.length +
          " transfer(s) on this branch are not in the saved transfer list.", "note"));
      }
    });
  }
  function setZoom(z) {
    zoom = Math.max(0.4, Math.min(2.5, z));
    svg.setAttribute("width", String(Math.round(baseW * zoom)));
    svg.setAttribute("height", String(Math.round(baseH * zoom)));
  }
  var zin = document.querySelector(".js-ff-zoom-in");
  var zout = document.querySelector(".js-ff-zoom-out");
  var zreset = document.querySelector(".js-ff-zoom-reset");
  if (zin) { zin.addEventListener("click", function () { setZoom(zoom * 1.2); }); }
  if (zout) { zout.addEventListener("click", function () { setZoom(zoom / 1.2); }); }
  if (zreset) { zreset.addEventListener("click", function () { setZoom(1); }); }
  var canvas = svg.parentNode;
  if (canvas && canvas.clientWidth && baseW > canvas.clientWidth) {
    // Start fitted to the available width, but never so small the text is unreadable.
    setZoom(Math.max(0.6, (canvas.clientWidth - 4) / baseW));
  }
  reset();
})();
"""


def render_fund_flow_body(
    *,
    graph: FundFlowGraph | None,
    trace: Mapping[str, Any] | None,
    preset_links: Sequence[tuple[str, str, bool]],
    mode_note: str,
    message: str | None = None,
) -> str:
    """The page body: presets, summary tiles, the graph, and the transfer table."""

    current = " aria-current='page'"
    options = "".join(
        f"<a class='btn{'' if active else ' secondary'}' href='{_e(href)}'"
        f"{current if active else ''}>{_e(label)}</a>"
        for href, label, active in preset_links
    )
    head = (
        "<div class='card' id='result'><h2>Fund flow</h2>"
        "<p class='note'>Observed token transfers from one saved trace result, drawn as a "
        "graph: one box per wallet, one arrow per transfer, left to right by hop. "
        f"{_e(mode_note)}</p>"
        f"<div class='cta-row'>{options}</div>"
        + (f"<p class='note'><strong>{_e(message)}</strong></p>" if message else "")
        + "</div>"
    )
    if graph is None or trace is None:
        return head + (
            "<div class='card'><h2>No graph</h2><p>No saved trace result is selected, so "
            "there is nothing to draw. This is not a statement that the address had no "
            "activity.</p></div>"
        )
    if graph.is_empty:
        return head + (
            "<div class='card'><h2>No transfers recorded</h2><p>The saved result holds no "
            "observed transfer to draw. That describes what was saved, not the chain.</p>"
            + _warnings(graph)
            + "</div>"
        )

    stats = graph.stats()
    seed = trace.get("seed") or {}
    asset = seed.get("asset") or {}
    tiles = "".join(
        f"<div class='tile'><div class='big'>{_e(value)}</div>"
        f"<div class='lbl'>{_e(label)}</div></div>"
        for value, label in (
            (stats["wallets"], "wallets"),
            (stats["transfers"], "observed transfers"),
            (stats["branches"], "branches"),
            (stats["supported_boundaries"], "supported service boundaries"),
            (stats["candidate_leads"], "candidate leads"),
            (stats["unresolved"], "unresolved endings"),
            (stats["reconverged"], "branches reconverged"),
            (stats["max_hop_layer"], "deepest hop layer"),
            (stats["ordering_ambiguous"], "ordering not established"),
        )
    )
    summary = (
        "<div class='card'><h2>Summary</h2>"
        f"<div class='tiles'>{tiles}</div>"
        "<p class='note'>Seed <span class='mono'>"
        f"{_e(seed.get('address'))}</span> on {_e(seed.get('network_key'))}, asset contract "
        f"<span class='mono'>{_e(asset.get('token_contract'))}</span> "
        f"({_e(asset.get('display_symbol'))}, display only). No amounts are summed: a total "
        "of drawn transfers is not a case-attributable amount (allocation_unknown).</p>"
        + _warnings(graph)
        + "</div>"
    )

    branch_options = "".join(
        f"<option value='{i}'>Branch {b['number']} → {_e(b['endpoint_class'])} "
        f"({_e(short(b['address'], 14))})</option>"
        for i, b in enumerate(graph.branches)
    )
    legend = (
        "<div class='legend'>"
        "<span class='k'><span class='swatch seed'></span>seed / case link</span>"
        "<span class='k'><span class='swatch wallet'></span>intermediate wallet</span>"
        "<span class='k'><span class='swatch known_service'></span>"
        "supported service boundary</span>"
        "<span class='k'><span class='swatch deposit_candidate dashed'></span>"
        "candidate lead (not verified)</span>"
        "<span class='k'><span class='swatch unresolved'></span>unresolved / boundary</span>"
        "<span class='k'><span class='line seed'></span>seed transfer</span>"
        "<span class='k'><span class='line'></span>observed transfer</span>"
        "<span class='k'><span class='line dashed'></span>ordering not established</span>"
        "</div>"
    )
    if any(e.derived_from for e in graph.edges):
        legend += (
            "<p class='note'>A dotted seed arrow is reconstructed from the branch ending's "
            "arrival event: this saved result predates the stored seed transfer, so its "
            "block time and execution status are not recorded here.</p>"
        )
    if len(graph.edges) > LABEL_EDGE_LIMIT:
        legend += (
            f"<p class='note'>{len(graph.edges)} transfers: amount labels are hidden on the "
            "graph to keep it legible. Every amount is in the table below.</p>"
        )
    graph_card = (
        "<div class='card' id='graph'><h2>Graph</h2>"
        f"{legend}"
        "<div class='ff-controls no-print'>"
        "<label for='ff-branch'>Highlight</label>"
        f"<select id='ff-branch'><option value=''>All branches</option>{branch_options}</select>"
        "<button type='button' class='secondary js-ff-zoom-out' aria-label='Zoom out'>−</button>"
        "<button type='button' class='secondary js-ff-zoom-in' aria-label='Zoom in'>+</button>"
        "<button type='button' class='secondary js-ff-zoom-reset'>Reset zoom</button>"
        "</div>"
        "<div class='ff-layout'>"
        f"<div class='ff-canvas'>{render_fund_flow_svg(graph)}</div>"
        "<aside class='ff-details' id='ff-details' aria-live='polite'></aside>"
        "</div>"
        "<p class='note'>Only observed token transfers are drawn. Resource delegations, TRX "
        "funding, and inferred control relationships are separate evidence (see the Demo "
        "page's Evidence layers) and never appear as arrows. A path is a sequence of "
        "transfers, not ownership of fungible units; left-to-right position is hop order, "
        "not a claim about chain order.</p>"
        f"{graph_json_script(graph)}"
        "</div>"
    )
    return head + summary + graph_card + _transfer_table(graph) + _limitations(trace)


def _warnings(graph: FundFlowGraph) -> str:
    if not graph.warnings:
        return ""
    items = "".join(f"<li>{_e(w)}</li>" for w in graph.warnings)
    return f"<div class='note'><strong>Drawing notes</strong><ul>{items}</ul></div>"


def _ordering_text(e: FlowEdge) -> str:
    if e.derived_from:
        return "not recorded"
    return "not established" if e.ordering_ambiguous else "established"


def _transfer_table(graph: FundFlowGraph) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{e.index + 1}</td>"
        f"<td class='mono' title='{_e(e.event_reference)}'>{_e(short(e.event_reference, 28))}"
        f"{' (seed)' if e.is_seed else ''}{' (reconstructed)' if e.derived_from else ''}</td>"
        f"<td class='mono' title='{_e(e.source)}'>{_e(short(e.source, 18))}</td>"
        f"<td class='mono' title='{_e(e.target)}'>{_e(short(e.target, 18))}</td>"
        f"<td class='mono'>{_e(e.amount_display)} {_e(e.symbol)}</td>"
        f"<td>{_e(e.block_time or 'not recorded')}</td>"
        f"<td>{_ordering_text(e)}</td>"
        f"<td>{_e(e.execution_status or 'not recorded')} / "
        f"{_e(e.confirmation_state or 'not recorded')}</td>"
        "</tr>"
        for e in graph.edges
    )
    return (
        "<div class='card'><h2>Transfers drawn</h2>"
        "<p class='note'>The same edges as the graph, with exact amounts. This table is "
        "the accessible and print-safe form of the picture.</p>"
        "<div class='table-scroll'><table><thead><tr><th>#</th><th>Event</th><th>From</th>"
        "<th>To</th><th>Amount</th><th>Block time</th><th>Ordering</th>"
        "<th>Execution / confirmation</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></div>"
    )


def _limitations(trace: Mapping[str, Any]) -> str:
    saved = [str(item) for item in trace.get("limitations") or []]
    items = "".join(f"<li>{_e(item)}</li>" for item in saved) or (
        "<li>No additional limitation was recorded with this saved result.</li>"
    )
    disclaimer = trace.get("disclaimer")
    return (
        "<div class='card'><h2>Limitations</h2>"
        f"<ul>{items}</ul>"
        + (f"<p class='note'>{_e(disclaimer)}</p>" if disclaimer else "")
        + "</div>"
    )
