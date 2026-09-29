import { X } from "lucide-react";
import type { BranchEnding, DemoPresetDetail, FlowEdge, FlowNode } from "../lib/api";
import { formatTime, humanize } from "../lib/format";
import { attributionStatus, endpointClass, executionStatus, reviewState } from "../lib/status";
import type { GraphSelection } from "../graph/FundFlowGraph";
import { Badge, Callout, CopyableValue, StatusBadge } from "./ui";

function Row({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </>
  );
}

function EndingPanel({ ending }: { ending: BranchEnding }) {
  const descriptor = endpointClass(ending.endpoint_class);
  return (
    <div className="stack">
      <div className="row wrap">
        <StatusBadge descriptor={descriptor} />
        <StatusBadge descriptor={attributionStatus(ending.attribution_status)} />
      </div>
      {ending.label ? (
        <div className="stack" style={{ gap: 4 }}>
          <div className="eyebrow">Label evidence</div>
          <dl className="dl">
            <Row term="Entity">{ending.label.entity_name}</Row>
            <Row term="Assertion">{humanize(ending.label.assertion_type)}</Row>
            <Row term="Role">{humanize(ending.label.address_role)}</Row>
            <Row term="Review">
              <StatusBadge descriptor={reviewState(ending.label.review_state)} />
            </Row>
            <Row term="Valid from">{formatTime(ending.label.valid_from)}</Row>
            <Row term="Valid to">{formatTime(ending.label.valid_to)}</Row>
            <Row term="Source">
              <span className="mono" style={{ fontSize: 11, overflowWrap: "anywhere" }}>
                {ending.label.source_reference}
              </span>
            </Row>
            <Row term="Source hash">
              <CopyableValue value={ending.label.source_hash} head={8} tail={6} label="source hash" />
            </Row>
          </dl>
        </div>
      ) : null}
      {ending.note ? <Callout title="Note">{ending.note}</Callout> : null}
    </div>
  );
}

function NodeInspect({ node, detail }: { node: FlowNode; detail: DemoPresetDetail }) {
  const endings = (detail.trace?.branch_endings ?? []).filter((ending) => ending.address === node.address);
  return (
    <div className="stack">
      <div className="row wrap">
        <Badge tone={node.role === "known_service" ? "verified" : node.role === "deposit_candidate" ? "candidate" : "neutral"}>
          {node.role_label}
        </Badge>
        <Badge tone="neutral">hop {node.hop_layer}</Badge>
        {node.entity_name ? <Badge tone="verified">{node.entity_name}</Badge> : null}
      </div>
      {node.role === "deposit_candidate" ? (
        <Callout tone="candidate" title="Candidate relationship.">
          This is an observed lead, not ownership evidence. A candidate never terminates a trace as
          a verified service boundary.
        </Callout>
      ) : null}
      <dl className="dl">
        <Row term="Address">
          <CopyableValue value={node.address} head={10} tail={8} label="address" />
        </Row>
        <Row term="Branches ending here">{node.branches.filter((b) => !node.reconverged_branches.includes(b)).join(", ") || "—"}</Row>
        <Row term="Reconverged here">{node.reconverged_branches.join(", ") || "—"}</Row>
        <Row term="Attribution">{node.attribution_statuses.map(humanize).join(", ") || "—"}</Row>
        <Row term="Boundary">{node.boundary_reasons.map(humanize).join(", ") || "—"}</Row>
      </dl>
      {endings.map((ending, index) => (
        <div className="inspector-section" key={index} style={{ padding: 0, border: 0 }}>
          <div className="eyebrow" style={{ marginBottom: 6 }}>
            Branch ending
          </div>
          <EndingPanel ending={ending} />
        </div>
      ))}
    </div>
  );
}

function EdgeInspect({ edge }: { edge: FlowEdge }) {
  return (
    <div className="stack">
      <div className="row wrap">
        {edge.is_seed_transfer ? <Badge tone="verified">Seed transfer</Badge> : <Badge tone="neutral">Observed transfer</Badge>}
        <StatusBadge descriptor={executionStatus(edge.execution_status)} />
      </div>
      <dl className="dl">
        <Row term="Event ref">
          <CopyableValue value={edge.event_reference} head={10} tail={8} label="event reference" />
        </Row>
        <Row term="Transaction">
          <CopyableValue value={edge.tx_hash} head={10} tail={8} label="transaction hash" />
        </Row>
        <Row term="From">
          <CopyableValue value={edge.from} head={8} tail={6} label="sender" />
        </Row>
        <Row term="To">
          <CopyableValue value={edge.to} head={8} tail={6} label="recipient" />
        </Row>
        <Row term="Amount">
          <span className="mono">{edge.amount_display ?? "not recorded"} {edge.symbol}</span>
        </Row>
        <Row term="Base units">
          <CopyableValue value={edge.amount_base_units} head={10} tail={6} label="base units" mono />
        </Row>
        <Row term="Block time">{formatTime(edge.block_time)}</Row>
        <Row term="Confirmation">{edge.confirmation_state ?? "not recorded"}</Row>
        <Row term="Ordering">
          {edge.derived_from ? "not recorded" : edge.ordering_ambiguous ? "not established by source" : "established"}
        </Row>
      </dl>
      <div className="inspector-section" style={{ padding: 0, border: 0 }}>
        <div className="eyebrow" style={{ marginBottom: 6 }}>
          Provenance
        </div>
        <Badge tone="cross-chain" title="Saved from a recorded public/replay bundle">
          RECORDED PUBLIC
        </Badge>
        {edge.derived_from ? <p className="muted" style={{ fontSize: 11 }}>{edge.derived_from}</p> : null}
      </div>
      <Callout title="A transfer shows movement,">
        not ownership of these specific units. Case-value allocation stays unknown.
      </Callout>
    </div>
  );
}

export function Inspector({
  selection,
  detail,
  onClose,
}: {
  selection: GraphSelection | null;
  detail: DemoPresetDetail;
  onClose: () => void;
}) {
  const title =
    selection?.kind === "node"
      ? "Wallet"
      : selection?.kind === "edge"
        ? "Transfer"
        : selection?.kind === "branch"
          ? "Branch"
          : "Inspector";

  return (
    <aside className="inspector" aria-label="Inspector">
      <div className="inspector-head">
        <h3>{title}</h3>
        <button type="button" className="btn icon close" onClick={onClose} aria-label="Close inspector">
          <X size={14} />
        </button>
      </div>
      <div className="inspector-section">
        {!selection ? (
          <p className="muted">
            Select a wallet, a transfer, or a branch to inspect its evidence, provenance, and
            limitations. Nothing is recomputed here — every value comes from the saved result.
          </p>
        ) : selection.kind === "node" ? (
          <NodeInspect node={selection.node} detail={detail} />
        ) : selection.kind === "edge" ? (
          <EdgeInspect edge={selection.edge} />
        ) : (
          <div className="stack">
            <Badge tone="neutral">Branch {selection.branch.number}</Badge>
            <dl className="dl">
              <Row term="Ends at">
                <CopyableValue value={selection.branch.address} head={8} tail={6} label="address" />
              </Row>
              <Row term="Outcome">{selection.branch.endpoint_class}</Row>
              <Row term="Attribution">{humanize(selection.branch.attribution_status)}</Row>
              <Row term="Boundary">{humanize(selection.branch.boundary_reason)}</Row>
              <Row term="Transfers">{selection.branch.edges.length}</Row>
            </dl>
            {selection.branch.undrawn_references.length ? (
              <Callout tone="warning">
                {selection.branch.undrawn_references.length} transfer(s) named on this branch are not
                in the saved transfer list.
              </Callout>
            ) : null}
          </div>
        )}
      </div>
    </aside>
  );
}
