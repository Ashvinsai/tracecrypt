import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Clock,
  ExternalLink,
  FileJson,
  Info,
  Link2,
  ScanLine,
  ShieldAlert,
  ShieldCheck,
  Table2,
  Waypoints,
} from "lucide-react";
import { Suspense, lazy, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import type { ColumnDef } from "@tanstack/react-table";
import {
  api,
  type BranchEnding,
  type CrossChainLink,
  type DemoPresetDetail,
  type FlowEdge,
  type ObservedTransfer,
} from "../lib/api";
import { formatTime, humanize, truncate } from "../lib/format";
import {
  attributionStatus,
  coverageStatus,
  dataMode,
  endpointClass,
  executionStatus,
  linkageStatus,
  reviewState,
} from "../lib/status";
import type { GraphSelection } from "../graph/FundFlowGraph";
import { DataTable } from "../components/DataTable";
import { Inspector } from "../components/Inspector";
import {
  Badge,
  Callout,
  ChainMark,
  CopyableValue,
  EmptyState,
  ErrorState,
  Loading,
  Panel,
  StatusBadge,
} from "../components/ui";

const FundFlowGraph = lazy(() => import("../graph/FundFlowGraph"));

type TabKey =
  | "graph"
  | "timeline"
  | "transactions"
  | "attribution"
  | "cross-chain"
  | "evidence"
  | "decision"
  | "notes";

const TABS: { key: TabKey; label: string; icon: typeof ScanLine }[] = [
  { key: "graph", label: "Graph", icon: Waypoints },
  { key: "timeline", label: "Timeline", icon: Clock },
  { key: "transactions", label: "Transactions", icon: Table2 },
  { key: "attribution", label: "Attribution", icon: ShieldCheck },
  { key: "cross-chain", label: "Cross-chain", icon: Link2 },
  { key: "evidence", label: "Evidence", icon: FileJson },
  { key: "decision", label: "Decision support", icon: ShieldAlert },
  { key: "notes", label: "Notes", icon: Info },
];

function allTransfers(detail: DemoPresetDetail): ObservedTransfer[] {
  const list: ObservedTransfer[] = [];
  if (detail.trace?.seed_transfer) list.push(detail.trace.seed_transfer);
  for (const transfer of detail.trace?.observed_transfers ?? []) list.push(transfer);
  return list;
}

export default function CaseWorkspacePage() {
  const { presetId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useQuery({
    queryKey: ["demo", "preset", presetId],
    queryFn: () => api.demo.preset(presetId),
    enabled: Boolean(presetId),
  });
  const tabParam = searchParams.get("tab") as TabKey | null;
  const [tab, setTabState] = useState<TabKey>(tabParam && TABS.some((t) => t.key === tabParam) ? tabParam : "graph");
  const setTab = (next: TabKey) => {
    setTabState(next);
    setSearchParams(next === "graph" ? {} : { tab: next }, { replace: true });
  };
  const [selection, setSelection] = useState<GraphSelection | null>(null);
  const [maxHop, setMaxHop] = useState<number | null>(null);

  if (query.isLoading) return <Loading rows={8} />;
  if (query.isError)
    return <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  const detail = query.data;
  if (!detail || !detail.trace) {
    return (
      <EmptyState icon={FileJson} title="No saved trace result for this case">
        {detail?.error ??
          "This prototype does not trace live on this surface. A missing saved artifact is not a finding about the case."}
      </EmptyState>
    );
  }

  const trace = detail.trace;
  const endings = trace.branch_endings ?? [];
  const counts: Partial<Record<TabKey, number>> = {
    transactions: allTransfers(detail).length,
    attribution: endings.length,
    "cross-chain": detail.cross_chain_links.length,
  };

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <div className="row wrap" style={{ marginBottom: 6 }}>
            <StatusBadge descriptor={dataMode(detail.data_mode)} />
            <ChainMark chain={trace.seed.network_key} />
            <Badge tone="neutral" title="Asset identity is (network, token contract); a ticker is display metadata">
              {trace.seed.asset.display_symbol}
            </Badge>
            <StatusBadge descriptor={coverageStatus(String(trace.scope.coverage_status ?? ""))} />
            {detail.capture_data_mode && detail.capture_data_mode !== detail.data_mode ? (
              <Badge tone="neutral">captured {detail.capture_data_mode}</Badge>
            ) : null}
          </div>
          <h1>{detail.title}</h1>
          <p>{detail.description}</p>
        </div>
        <div className="head-actions">
          <Link className="btn sm" to="/cases">
            All cases
          </Link>
          <a
            className="btn sm"
            href={`/console/evidence/${encodeURIComponent(detail.id)}`}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={13} /> Evidence report
          </a>
          <a
            className="btn sm"
            href={`/console/trace/${encodeURIComponent(detail.id)}`}
            target="_blank"
            rel="noreferrer"
            download
          >
            <FileJson size={13} /> Trace JSON
          </a>
        </div>
      </div>

      <div className="metric-row">
        <div className="metric">
          <div className="metric-value" style={{ fontFamily: "var(--font-mono)", fontSize: 14 }}>
            <CopyableValue value={trace.seed.address} head={10} tail={8} label="seed address" />
          </div>
          <div className="metric-label">Seed wallet · {trace.seed.network_key}</div>
        </div>
        <div className="metric">
          <div className="metric-value">{counts.transactions}</div>
          <div className="metric-label">Observed transfers</div>
        </div>
        <div className="metric">
          <div className="metric-value">{endings.filter((e) => e.endpoint_class === "known_service").length}</div>
          <div className="metric-label">Verified boundaries</div>
        </div>
        <div className="metric">
          <div className="metric-value">{endings.filter((e) => e.endpoint_class === "deposit_candidate").length}</div>
          <div className="metric-label">Candidate leads</div>
        </div>
        <div className="metric">
          <div className="metric-value">{endings.filter((e) => e.endpoint_class === "unresolved").length}</div>
          <div className="metric-label">Unresolved endings</div>
        </div>
      </div>

      {detail.scope_note ? (
        <Callout icon={Info} title="Scope.">
          {detail.scope_note}
        </Callout>
      ) : null}

      <div>
        <div className="tabs" role="tablist">
          {TABS.map((item) => (
            <button
              key={item.key}
              role="tab"
              aria-selected={tab === item.key}
              className={`tab${tab === item.key ? " active" : ""}`}
              onClick={() => setTab(item.key)}
            >
              <item.icon size={13} style={{ verticalAlign: "-2px", marginRight: 6 }} />
              {item.label}
              {counts[item.key] ? <span className="tab-count">{counts[item.key]}</span> : null}
            </button>
          ))}
        </div>

        <div className={tab === "graph" ? "main-layout" : undefined}>
          {tab === "graph" ? (
            <div className="stack" style={{ display: "grid", gridTemplateColumns: "1fr", gap: "var(--space-3)" }}>
              <div className="grid" style={{ gridTemplateColumns: "1fr", gap: "var(--space-3)" }}>
                <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 320px", gap: "var(--space-3)" }}>
                  <div>
                    <GraphLegend />
                    <Suspense fallback={<Loading rows={4} />}>
                      {detail.graph ? (
                        <FundFlowGraph
                          graph={detail.graph}
                          selection={selection}
                          onSelect={setSelection}
                          maxHop={maxHop}
                          initialPathOnly={searchParams.get("branches") !== "all"}
                        />
                      ) : null}
                    </Suspense>
                    <TimelineScrubber
                      detail={detail}
                      selection={selection}
                      onSelect={setSelection}
                    />
                  </div>
                  <GraphFilters detail={detail} maxHop={maxHop} setMaxHop={setMaxHop} />
                </div>
              </div>
            </div>
          ) : null}

          {tab === "timeline" ? (
            <TimelineTab detail={detail} onSelect={setSelection} />
          ) : null}
          {tab === "transactions" ? <TransactionsTab detail={detail} onSelect={setSelection} selection={selection} /> : null}
          {tab === "attribution" ? <AttributionTab detail={detail} /> : null}
          {tab === "cross-chain" ? <CrossChainTab detail={detail} /> : null}
          {tab === "evidence" ? <EvidenceTab detail={detail} /> : null}
          {tab === "decision" ? <DecisionSupportTab detail={detail} /> : null}
          {tab === "notes" ? <NotesTab /> : null}
        </div>
      </div>

      {detail.warnings.length > 0 ? (
        <Callout tone="warning" title="Artifact warnings.">
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {detail.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Callout>
      ) : null}

      {selection ? (
        <div className="inspector-drawer">
          <Inspector selection={selection} detail={detail} onClose={() => setSelection(null)} />
        </div>
      ) : null}
    </div>
  );
}

function GraphLegend() {
  return (
    <div className="legend" style={{ marginBottom: "var(--space-3)" }}>
      <span className="k">
        <span className="glyph circle" style={{ borderColor: "var(--accent)" }} /> seed / case link
      </span>
      <span className="k">
        <span className="glyph circle" /> intermediate wallet
      </span>
      <span className="k">
        <span className="glyph verified" /> verified service boundary
      </span>
      <span className="k">
        <span className="glyph candidate" /> candidate lead (not verified)
      </span>
      <span className="k">
        <span className="glyph boundary" /> coverage boundary
      </span>
    </div>
  );
}

function GraphFilters({
  detail,
  maxHop,
  setMaxHop,
}: {
  detail: DemoPresetDetail;
  maxHop: number | null;
  setMaxHop: (value: number | null) => void;
}) {
  const graph = detail.graph;
  if (!graph) return null;
  const max = graph.stats.max_hop_layer;
  return (
    <Panel title="Filters">
      <div className="stack">
        <label className="stack" style={{ gap: 4 }}>
          <span className="muted" style={{ fontSize: 11 }}>
            Maximum hop depth
          </span>
          <select
            value={maxHop ?? ""}
            onChange={(event) => setMaxHop(event.target.value === "" ? null : Number(event.target.value))}
          >
            <option value="">All hops</option>
            {Array.from({ length: max + 1 }, (_, index) => (
              <option key={index} value={index}>
                {index === 0 ? "Hop 0 (seed)" : `Up to hop ${index}`}
              </option>
            ))}
          </select>
        </label>
        <dl className="dl">
          <dt>Wallets</dt>
          <dd>{graph.stats.wallets}</dd>
          <dt>Transfers</dt>
          <dd>{graph.stats.transfers}</dd>
          <dt>Branches</dt>
          <dd>{graph.stats.branches}</dd>
          <dt>Reconverged</dt>
          <dd>{graph.stats.reconverged}</dd>
          <dt>Ordering unknown</dt>
          <dd>{graph.stats.ordering_ambiguous}</dd>
        </dl>
        <p className="muted" style={{ fontSize: 11 }}>
          {graph.warnings.length > 0
            ? `${graph.warnings.length} drawing warning(s); see the report.`
            : "No drawing warnings. Only observed token transfers are drawn."}
        </p>
      </div>
    </Panel>
  );
}

function TimelineScrubber({
  detail,
  selection,
  onSelect,
}: {
  detail: DemoPresetDetail;
  selection: GraphSelection | null;
  onSelect: (selection: GraphSelection) => void;
}) {
  const events = useMemo(() => buildTimeline(detail), [detail]);
  const [index, setIndex] = useState(events.length > 0 ? 0 : -1);
  if (events.length === 0) return null;
  const current = events[Math.max(0, index)];
  const select = (nextIndex: number) => {
    setIndex(nextIndex);
    const event = events[nextIndex];
    if (event.edge) onSelect({ kind: "edge", edge: event.edge });
  };
  return (
    <div className="timeline-scrubber">
      <span className="muted" style={{ fontSize: 11 }}>
        Chronology
      </span>
      <input
        type="range"
        min={0}
        max={events.length - 1}
        value={Math.max(0, index)}
        onChange={(event) => select(Number(event.target.value))}
        aria-label="Timeline position"
      />
      <span className="timeline-marker">
        {current.label} · {formatTime(current.time)}
      </span>
      <Badge tone={selection ? "verified" : "neutral"}>
        {current.time ? new Date(current.time).toISOString().slice(11, 19) + "Z" : "—"}
      </Badge>
    </div>
  );
}

interface TimelineEvent {
  label: string;
  time: string | null;
  edge: FlowEdge | null;
  transfer: ObservedTransfer;
  kind: string;
}

function buildTimeline(detail: DemoPresetDetail): TimelineEvent[] {
  const graph = detail.graph;
  const edgeByRef = new Map<string, FlowEdge>();
  for (const edge of graph?.edges ?? []) edgeByRef.set(edge.event_reference, edge);
  const transfers = allTransfers(detail);
  return transfers
    .map((transfer) => ({
      transfer,
      edge: edgeByRef.get(transfer.event_reference) ?? null,
      time: transfer.block_time,
      label: `${transfer.from_address ? truncate(transfer.from_address, 6, 4) : "?"} → ${
        transfer.to_address ? truncate(transfer.to_address, 6, 4) : "?"
      } · ${transfer.amount_display} ${transfer.asset.display_symbol}`,
      kind: transfer.hop_depth === 0 ? "Seed arrival" : `Hop ${transfer.hop_depth}`,
    }))
    .sort((a, b) => {
      if (!a.time && !b.time) return 0;
      if (!a.time) return 1;
      if (!b.time) return -1;
      return a.time.localeCompare(b.time);
    });
}

function TimelineTab({
  detail,
  onSelect,
}: {
  detail: DemoPresetDetail;
  onSelect: (selection: GraphSelection) => void;
}) {
  const events = useMemo(() => buildTimeline(detail), [detail]);
  if (events.length === 0)
    return (
      <EmptyState icon={Clock} title="No transfers recorded">
        The saved result holds no observed transfer to lay out. That describes what was saved, not
        the chain.
      </EmptyState>
    );
  return (
    <Panel title="Chronological trace">
      <div className="stack">
        {events.map((event, index) => (
          <div
            key={`${event.transfer.event_reference}-${index}`}
            className="row"
            style={{ alignItems: "flex-start", gap: "var(--space-4)", cursor: "pointer" }}
            onClick={() => event.edge && onSelect({ kind: "edge", edge: event.edge })}
          >
            <div style={{ width: 150, flex: "none" }} className="muted mono">
              {formatTime(event.time)}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row wrap" style={{ gap: 6 }}>
                <Badge tone={event.transfer.hop_depth === 0 ? "verified" : "neutral"}>{event.kind}</Badge>
                <StatusBadge descriptor={executionStatus(event.transfer.execution_status)} />
              </div>
              <div className="mono" style={{ fontSize: 12, marginTop: 4 }}>
                {event.transfer.from_address ? truncate(event.transfer.from_address, 8, 6) : "?"}
                <ArrowRight size={12} style={{ margin: "0 6px", verticalAlign: "-2px" }} />
                {event.transfer.to_address ? truncate(event.transfer.to_address, 8, 6) : "?"}
              </div>
            </div>
            <div className="mono" style={{ flex: "none" }}>
              {event.transfer.amount_display} {event.transfer.asset.display_symbol}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function TransactionsTab({
  detail,
  onSelect,
  selection,
}: {
  detail: DemoPresetDetail;
  onSelect: (selection: GraphSelection) => void;
  selection: GraphSelection | null;
}) {
  const [filter, setFilter] = useState("");
  const rows = allTransfers(detail);
  const edgeByRef = new Map<string, FlowEdge>();
  for (const edge of detail.graph?.edges ?? []) edgeByRef.set(edge.event_reference, edge);
  const selectedRef =
    selection?.kind === "edge" ? selection.edge.event_reference : selection?.kind === "node" ? "__node__" : "";

  const columns: ColumnDef<ObservedTransfer, unknown>[] = [
    { id: "hop", header: "Hop", accessorFn: (row) => row.hop_depth, cell: (info) => info.getValue<number>() },
    {
      id: "event",
      header: "Event",
      accessorFn: (row) => row.event_reference,
      cell: (info) => <CopyableValue value={String(info.getValue())} head={8} tail={6} label="event" />,
    },
    {
      id: "from",
      header: "From",
      accessorFn: (row) => row.from_address ?? "",
      cell: (info) => <CopyableValue value={String(info.getValue())} head={6} tail={5} label="sender" />,
    },
    {
      id: "to",
      header: "To",
      accessorFn: (row) => row.to_address ?? "",
      cell: (info) => <CopyableValue value={String(info.getValue())} head={6} tail={5} label="recipient" />,
    },
    {
      id: "amount",
      header: "Amount",
      accessorFn: (row) => row.amount_display,
      cell: (info) => {
        const row = info.row.original;
        return (
          <span className="mono">
            {row.amount_display} {row.asset.display_symbol}
          </span>
        );
      },
    },
    {
      id: "base",
      header: "Base units",
      accessorFn: (row) => row.amount_base_units,
      cell: (info) => <span className="mono">{String(info.getValue())}</span>,
    },
    {
      id: "time",
      header: "Block time",
      accessorFn: (row) => row.block_time ?? "",
      cell: (info) => formatTime(String(info.getValue()) || null),
    },
    {
      id: "exec",
      header: "Execution",
      accessorFn: (row) => row.execution_status,
      cell: (info) => <StatusBadge descriptor={executionStatus(String(info.getValue()))} />,
    },
    {
      id: "ordering",
      header: "Ordering",
      accessorFn: (row) => (row.ordering_ambiguous ? "not established" : "established"),
    },
  ];

  return (
    <Panel
      title="Observed transfers"
      actions={
        <input
          className="graph-toolbar"
          style={{ border: "1px solid var(--border-strong)", borderRadius: "var(--radius)", background: "var(--surface-2)", color: "var(--text-primary)", padding: "4px 8px" }}
          placeholder="Filter transfers…"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          aria-label="Filter transfers"
        />
      }
    >
      <DataTable
        columns={columns}
        data={rows}
        filter={filter}
        selectedRowId={selectedRef}
        rowId={(row) => row.event_reference}
        empty={<EmptyState icon={Table2} title="No transfers" />}
        onRowClick={(row) => {
          const edge = edgeByRef.get(row.event_reference);
          if (edge) onSelect({ kind: "edge", edge });
        }}
      />
    </Panel>
  );
}

function AttributionTab({ detail }: { detail: DemoPresetDetail }) {
  const endings = detail.trace?.branch_endings ?? [];
  const verified = endings.filter((ending) => ending.endpoint_class === "known_service");
  const candidates = endings.filter((ending) => ending.endpoint_class === "deposit_candidate");
  const unresolved = endings.filter(
    (ending) => ending.endpoint_class === "unresolved" || ending.endpoint_class === "boundary",
  );

  return (
    <div className="stack lg">
      <Panel title="Verified service boundary">
        {verified.length === 0 ? (
          <EmptyState icon={ShieldCheck} title="No reviewed VASP attribution found">
            No branch on this saved result ended at an accepted, dated service-control claim.
          </EmptyState>
        ) : (
          verified.map((ending) => <VerifiedEnding key={ending.address + ending.arrival_event_reference} ending={ending} />)
        )}
      </Panel>

      <Panel title="Investigative leads (candidates)">
        {candidates.length === 0 ? (
          <EmptyState icon={ShieldAlert} title="No candidate relationships recorded">
            This saved result has no deposit-candidate lead. Candidate leads appear only when an
            observed relationship matches a conservative rule.
          </EmptyState>
        ) : (
          <div className="stack">
            {candidates.map((ending) => (
              <Callout tone="candidate" key={ending.address} title="Candidate relationship — not ownership evidence.">
                <div className="mono" style={{ marginTop: 4 }}>
                  <CopyableValue value={ending.address} head={10} tail={8} label="candidate address" />
                </div>
                <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                  {ending.note ?? "Observed relationship only."}
                </div>
              </Callout>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Unresolved and bounded endings">
        {unresolved.length === 0 ? (
          <div className="muted">No unresolved endings.</div>
        ) : (
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Address</th>
                    <th>Endpoint</th>
                    <th>Boundary reason</th>
                    <th>Hop</th>
                  </tr>
                </thead>
                <tbody>
                  {unresolved.map((ending) => (
                    <tr key={ending.address + (ending.arrival_event_reference ?? "")}>
                      <td>
                        <CopyableValue value={ending.address} head={7} tail={6} label="address" />
                      </td>
                      <td>
                        <StatusBadge descriptor={endpointClass(ending.endpoint_class)} />
                      </td>
                      <td>{humanize(ending.boundary_reason)}</td>
                      <td className="num">{ending.hop_depth}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

function VerifiedEnding({ ending }: { ending: BranchEnding }) {
  const label = ending.label;
  return (
    <div className="stack" style={{ marginBottom: "var(--space-4)" }}>
      <div className="row wrap">
        <Badge tone="verified" icon={ShieldCheck}>
          REVIEWED SERVICE CONTROL
        </Badge>
        <Badge tone="neutral" icon={ShieldCheck}>
          {label?.entity_name ?? "Unknown service"}
        </Badge>
      </div>
      <dl className="dl">
        <dt>Observed address</dt>
        <dd>
          <CopyableValue value={ending.address} head={10} tail={8} label="service address" />
        </dd>
        <dt>Evidence type</dt>
        <dd>{humanize(label?.assertion_type)}</dd>
        <dt>Source</dt>
        <dd className="mono" style={{ fontSize: 11, overflowWrap: "anywhere" }}>
          {label?.source_reference ?? "—"}
        </dd>
        <dt>Validity window</dt>
        <dd>
          {formatTime(label?.valid_from)} → {formatTime(label?.valid_to)}
        </dd>
        <dt>Event time</dt>
        <dd>{formatTime(ending.label?.last_verified_at ?? null)}</dd>
        <dt>Review</dt>
        <dd>
          <StatusBadge descriptor={reviewState(label?.review_state)} />
        </dd>
        <dt>Attribution</dt>
        <dd>
          <StatusBadge descriptor={attributionStatus(ending.attribution_status)} />
        </dd>
      </dl>
      <Callout icon={Info}>
        The claim is scoped to the stated snapshot instant, not an interval of continuing control.
        Address role and case-value allocation remain unknown.
      </Callout>
    </div>
  );
}

function CrossChainTab({ detail }: { detail: DemoPresetDetail }) {
  const links = detail.cross_chain_links as unknown as CrossChainLink[];
  if (links.length === 0) {
    return (
      <EmptyState icon={Link2} title="No supported cross-chain protocol link for this event">
        Cross-chain continuation is protocol-specific and deliberately limited to Circle CCTP V2
        (Ethereum Mainnet to Base Mainnet USDC). Other bridges and asset changes remain unsupported
        boundaries — the tracer stops rather than inventing a continuation.
      </EmptyState>
    );
  }
  return (
    <div className="stack lg">
      {links.map((link, index) => (
        <CctpLinkPanel key={index} link={link} />
      ))}
    </div>
  );
}

export function CctpLinkPanel({ link }: { link: CrossChainLink }) {
  return (
    <Panel
      title="Circle CCTP V2 cross-chain link"
      actions={<StatusBadge descriptor={linkageStatus(link.linkage_status)} />}
    >
      <div className="stack lg">
        <Callout tone="cross-chain" icon={Waypoints} title="Protocol-verifiable boundary transition.">
          Reported as an explicit cross-chain link, never as a same-chain transfer.
        </Callout>
        <div className="grid cols-3">
          <ChainColumn
            title="Source blockchain"
            chain={link.source_network}
            rows={[
              ["Transaction", link.source_tx_hash],
              ["Block", String(link.source_block_number)],
              ["Block time", formatTime(link.source_block_time)],
              ["Domain", String(link.source_domain)],
              ["Burn event", link.source_burn_event_reference],
              ["Burned", link.source_burn_amount_base_units],
              ["Finality", link.source_finality ?? "—"],
            ]}
          />
          <ChainColumn
            title="Protocol / API"
            chain="CCTP"
            rows={[
              ["Attestation status", link.attestation_status],
              ["Attestation source", link.attestation_source],
              ["Message nonce", link.message_nonce],
              ["Message hash", link.message_hash],
              ["Signature verified locally", String(link.attestation_signature_verified)],
              ["Reconciliation", link.amount_reconciliation],
              ["Fees", link.fee_executed_base_units],
            ]}
          />
          <ChainColumn
            title="Destination blockchain"
            chain={link.destination_network}
            rows={[
              ["Transaction", link.destination_tx_hash ?? "—"],
              ["Block", link.destination_block_number ? String(link.destination_block_number) : "—"],
              ["Block time", formatTime(link.destination_block_time)],
              ["Domain", String(link.destination_domain)],
              ["Mint event", link.destination_mint_event_reference ?? "—"],
              ["Minted", link.observed_mint_and_withdraw_amount_base_units ?? "—"],
              ["Finality", link.destination_receipt_finality ?? "—"],
            ]}
          />
        </div>
        <Callout tone="candidate" icon={Info} title="API metadata is not local cryptographic proof.">
          Attestation status is <span className="mono">API_REPORTED_COMPLETE</span> from Circle's Iris
          API. Independent on-chain ECDSA signature verification is not executed locally.
        </Callout>
        {link.limitations.length > 0 ? (
          <div>
            <div className="eyebrow">Limitations</div>
            <ul className="muted" style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12 }}>
              {link.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

function ChainColumn({
  title,
  chain,
  rows,
}: {
  title: string;
  chain: string;
  rows: [string, string][];
}) {
  return (
    <div className="panel" style={{ background: "var(--surface-2)" }}>
      <div className="panel-head">
        <h3>{title}</h3>
        <span className="panel-actions">
          <ChainMark chain={chain} />
        </span>
      </div>
      <div className="panel-body">
        <dl className="dl">
          {rows.map(([term, value]) => (
            <div key={term} style={{ display: "contents" }}>
              <dt>{term}</dt>
              <dd className="mono" style={{ fontSize: 11 }}>
                {value.length > 28 ? (
                  <CopyableValue value={value} head={10} tail={8} label={term} />
                ) : (
                  value
                )}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

function EvidenceTab({ detail }: { detail: DemoPresetDetail }) {
  const manifest = detail.manifest as { files?: Record<string, string>; caveat?: string; data_mode?: string } | null;
  const files = Object.entries(manifest?.files ?? {});
  return (
    <div className="stack lg">
      <Panel title="Trace provenance">
        <dl className="dl">
          <dt>Data mode</dt>
          <dd>
            <StatusBadge descriptor={dataMode(detail.data_mode)} />
          </dd>
          <dt>Capture mode</dt>
          <dd>{detail.capture_data_mode ?? detail.data_mode}</dd>
          <dt>Engine version</dt>
          <dd className="mono">{String(detail.trace?.scope.engine_version ?? "—")}</dd>
          <dt>Label set</dt>
          <dd className="mono">{String(detail.trace?.scope.label_set_version ?? "—")}</dd>
          <dt>Analysis cutoff</dt>
          <dd>{formatTime(String(detail.trace?.scope.analysis_cutoff ?? ""))}</dd>
          <dt>Saved report</dt>
          <dd>
            {detail.has_report ? (
              <a href={`/console/evidence/${encodeURIComponent(detail.id)}`} target="_blank" rel="noreferrer">
                Open printable evidence report
              </a>
            ) : (
              "not saved for this preset"
            )}
          </dd>
        </dl>
      </Panel>

      <Panel title="Evidence manifest">
        {!manifest ? (
          <EmptyState icon={FileJson} title="No manifest on file">
            This saved result has no manifest, so its files are not hash-verified here.
          </EmptyState>
        ) : (
          <div className="stack">
            <div className="table-wrap">
              <div className="table-scroll" style={{ maxHeight: "none" }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>SHA-256</th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.map(([name, hash]) => (
                      <tr key={name}>
                        <td className="mono">{name}</td>
                        <td>
                          <CopyableValue value={hash} head={12} tail={8} label="hash" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            {manifest.caveat ? (
              <Callout icon={Info} title="Integrity is not correctness.">
                {manifest.caveat}
              </Callout>
            ) : null}
          </div>
        )}
      </Panel>

      <Panel title="Limitations">
        {(detail.trace?.limitations ?? []).length === 0 ? (
          <div className="muted">No additional limitation was recorded with this saved result.</div>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {detail.trace?.limitations.map((limitation) => (
              <li key={limitation.code + (limitation.address ?? "")} style={{ marginBottom: 6 }}>
                <span className="mono muted">{limitation.code}</span> — {limitation.message}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function DecisionSupportTab({ detail }: { detail: DemoPresetDetail }) {
  const routing = useQuery({ queryKey: ["demo", "routing"], queryFn: api.demo.routing });
  const hasCrossChain = detail.cross_chain_links.length > 0;
  if (routing.isLoading) return <Loading rows={4} />;
  const bundle = routing.data?.bundles?.[0];
  const comparison = bundle?.summary?.cross_chain_comparison as
    | { production_selected_action?: string; production_clm_choice?: string; production_clm_probs?: Record<string, number>; finding?: string }
    | undefined;

  return (
    <div className="stack lg">
      <Callout tone="decision" icon={ShieldAlert} title="DECISION SUPPORT METADATA — NOT BLOCKCHAIN EVIDENCE.">
        The System-1 router ranks predefined investigation actions over deterministic evidence state.
        Deterministic rules remain authoritative; the CLM runs in shadow mode and cannot modify
        evidence, assert ownership, or execute anything.
      </Callout>

      {hasCrossChain && comparison ? (
        <Panel title="Investigation routing (saved shadow validation)">
          <div className="stack">
            <dl className="dl">
              <dt>Actual action</dt>
              <dd className="mono">{comparison.production_selected_action ?? "—"}</dd>
              <dt>Selected by</dt>
              <dd>Deterministic rules (authoritative)</dd>
              <dt>CLM</dt>
              <dd>
                Shadow mode · choice <span className="mono">{comparison.production_clm_choice ?? "—"}</span>
              </dd>
              <dt>Execution</dt>
              <dd>Rules retained control regardless of the CLM ranking</dd>
            </dl>
            {comparison.production_clm_probs ? (
              <div>
                <div className="eyebrow">CLM ranked actions (relative, uncalibrated)</div>
                <div className="stack" style={{ marginTop: 6 }}>
                  {Object.entries(comparison.production_clm_probs)
                    .sort((a, b) => b[1] - a[1])
                    .map(([action, score]) => (
                      <div className="row" key={action} style={{ gap: 10 }}>
                        <span className="mono" style={{ minWidth: 230 }}>{action}</span>
                        <span className="mono muted">{score.toFixed(4)}</span>
                      </div>
                    ))}
                </div>
              </div>
            ) : null}
            {comparison.finding ? (
              <p className="muted" style={{ fontSize: 12 }}>
                {comparison.finding}
              </p>
            ) : null}
          </div>
        </Panel>
      ) : (
        <Panel title="Investigation routing">
          <EmptyState icon={ShieldAlert} title="No saved routing decision for this case">
            The router is validated on a fixed scenario set, not run per case on this read-only
            surface. Open Decision Support to inspect the saved validation — including an example
            where the CLM disagrees and the rules keep control.
          </EmptyState>
          <div className="row" style={{ marginTop: "var(--space-3)" }}>
            <Link className="btn sm" to="/decision-support">
              Open Decision Support
            </Link>
          </div>
        </Panel>
      )}
    </div>
  );
}

function NotesTab() {
  const [notes, setNotes] = useState("");
  return (
    <Panel title="Investigator notes">
      <textarea
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
        placeholder="Local working notes for this session…"
        style={{
          width: "100%",
          minHeight: 180,
          background: "var(--surface-inset)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius)",
          padding: "var(--space-3)",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          resize: "vertical",
        }}
      />
      <Callout icon={Info} title="Local only.">
        These notes are held in this browser tab and are not persisted, exported, or sent anywhere.
        Nothing here becomes evidence.
      </Callout>
    </Panel>
  );
}
