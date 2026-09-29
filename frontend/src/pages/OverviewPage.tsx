import { useQuery } from "@tanstack/react-query";
import { Boxes, Layers, ShieldCheck, Waypoints } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type Capability } from "../lib/api";
import { truncate } from "../lib/format";
import { capabilityStatus, dataMode } from "../lib/status";
import { Badge, ChainMark, ErrorState, Loading, Panel, StatusBadge } from "../components/ui";

const HEALTH_KEYS: { key: string; label: string }[] = [
  { key: "tron_acquisition", label: "TRON" },
  { key: "evm_token_tracing", label: "Ethereum" },
  { key: "bsc_token_tracing", label: "BSC" },
  { key: "base_token_tracing", label: "Base" },
  { key: "bridge_tracing", label: "Circle CCTP" },
  { key: "system1_investigation_routing", label: "CLM routing" },
];

function byKey(capabilities: Capability[]): Record<string, Capability> {
  return Object.fromEntries(capabilities.map((capability) => [capability.key, capability]));
}

export default function OverviewPage() {
  const presets = useQuery({ queryKey: ["demo", "presets"], queryFn: api.demo.presets });
  const capabilities = useQuery({ queryKey: ["demo", "capabilities"], queryFn: api.demo.capabilities });
  const candidates = useQuery({ queryKey: ["demo", "candidates"], queryFn: api.demo.candidates });
  const cctp = useQuery({ queryKey: ["demo", "cctp"], queryFn: api.demo.cctp });

  if (presets.isLoading || capabilities.isLoading) return <Loading rows={6} />;
  if (presets.isError)
    return <ErrorState message={(presets.error as Error).message} onRetry={() => presets.refetch()} />;

  const rows = presets.data?.presets ?? [];
  const caps = byKey(capabilities.data?.capabilities ?? []);
  const candidateCount = (candidates.data?.reports ?? []).reduce(
    (sum, report) => sum + (report.report.candidates?.length ?? 0),
    0,
  );
  const verifiedBoundaries = rows.reduce((sum, row) => sum + row.known_service, 0);
  const unresolved = rows.reduce((sum, row) => sum + row.unresolved, 0);
  const candidateLeads = rows.reduce((sum, row) => sum + row.candidate, 0);
  const crossChain = cctp.data?.count ?? 0;

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Operational Overview</h1>
          <p>
            Saved evidence on this deployment. Every number is derived from the artifacts actually
            present on disk — aggregate values that the backend does not expose are shown as
            unavailable, never invented.
          </p>
        </div>
      </div>

      <div className="metric-row" role="group" aria-label="Operational metrics">
        <div className="metric">
          <div className="metric-value">{rows.length}</div>
          <div className="metric-label">Saved investigations</div>
          <div className="metric-hint">{rows.filter((row) => row.has_trace).length} with a trace on file</div>
        </div>
        <div className="metric">
          <div className="metric-value">{verifiedBoundaries}</div>
          <div className="metric-label">Verified service boundaries</div>
          <div className="metric-hint">reviewed, dated claims only</div>
        </div>
        <div className="metric">
          <div className="metric-value">{candidateLeads + candidateCount}</div>
          <div className="metric-label">Candidate leads</div>
          <div className="metric-hint">not ownership evidence</div>
        </div>
        <div className="metric">
          <div className="metric-value">{unresolved}</div>
          <div className="metric-label">Unresolved branch endings</div>
          <div className="metric-hint">the honest result, kept</div>
        </div>
        <div className="metric">
          <div className="metric-value">{crossChain}</div>
          <div className="metric-label">Cross-chain links</div>
          <div className="metric-hint">Circle CCTP V2 only</div>
        </div>
      </div>

      <Panel
        title="Provider & capability availability"
        actions={
          <Link className="btn sm" to="/system">
            Full capability matrix
          </Link>
        }
      >
        <div className="metric-row" style={{ border: 0 }}>
          {HEALTH_KEYS.map(({ key, label }) => {
            const capability = caps[key];
            return (
              <div className="metric" key={key}>
                <div style={{ fontSize: 14 }}>
                  {capability ? (
                    <StatusBadge descriptor={capabilityStatus(capability.status)} />
                  ) : (
                    <Badge tone="neutral">unknown</Badge>
                  )}
                </div>
                <div className="metric-label">{label}</div>
                <div className="metric-hint">
                  {capability?.historical_live_run_recorded
                    ? "historical live run on file"
                    : "no live run on file"}
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      <Panel title="Recent investigations">
        {rows.length === 0 ? (
          <div className="muted">No saved trace bundles are present on this checkout.</div>
        ) : (
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Seed address</th>
                    <th>Network</th>
                    <th>Mode</th>
                    <th className="num">Transfers</th>
                    <th>Outcome</th>
                    <th>Manifest</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td className="nowrap">
                        {row.has_trace ? (
                          <Link to={`/cases/${encodeURIComponent(row.id)}`}>
                            {truncate(row.id, 22, 6)}
                          </Link>
                        ) : (
                          truncate(row.id, 22, 6)
                        )}
                      </td>
                      <td>
                        <span className="mono" title={row.address}>
                          {truncate(row.address, 8, 6)}
                        </span>
                      </td>
                      <td>
                        <ChainMark chain={row.network} />
                      </td>
                      <td>
                        <StatusBadge descriptor={dataMode(row.data_mode)} />
                      </td>
                      <td className="num">{row.observed_transfers}</td>
                      <td>
                        {row.known_service > 0 ? (
                          <Badge tone="verified">{row.outcome_service ?? "verified boundary"}</Badge>
                        ) : row.candidate > 0 ? (
                          <Badge tone="candidate">candidate lead</Badge>
                        ) : (
                          <Badge tone="neutral">unresolved</Badge>
                        )}
                      </td>
                      <td>
                        <Badge
                          tone={row.integrity.available && row.integrity.failed === 0 ? "verified" : "neutral"}
                        >
                          {row.integrity.available
                            ? `${row.integrity.ok}/${row.integrity.checked}`
                            : "none"}
                        </Badge>
                      </td>
                      <td className="muted">
                        {row.has_trace ? "answerable" : row.error ? "no trace on file" : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Panel>

      <div className="grid cols-3">
        <QuickCard
          to="/cases"
          icon={Boxes}
          title="Open a demo case"
          body="Saved traces with graph, timeline, attribution, and evidence."
        />
        <QuickCard
          to="/cross-chain"
          icon={Waypoints}
          title="Cross-chain evidence"
          body="Circle CCTP V2 Ethereum to Base, source / protocol / destination."
        />
        <QuickCard
          to="/decision-support"
          icon={ShieldCheck}
          title="Decision support"
          body="Rules-authoritative routing with CLM in shadow mode only."
        />
      </div>
    </div>
  );
}

function QuickCard({
  to,
  icon: Icon,
  title,
  body,
}: {
  to: string;
  icon: typeof Layers;
  title: string;
  body: string;
}) {
  return (
    <Link
      to={to}
      className="panel"
      style={{ display: "block", padding: "var(--space-4)", textDecoration: "none" }}
    >
      <div className="row" style={{ gap: 10 }}>
        <span style={{ color: "var(--accent)" }}>
          <Icon size={18} aria-hidden="true" />
        </span>
        <strong>{title}</strong>
      </div>
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 12 }}>
        {body}
      </p>
    </Link>
  );
}
