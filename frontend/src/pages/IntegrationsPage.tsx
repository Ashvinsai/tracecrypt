import { useQuery } from "@tanstack/react-query";
import { Plug } from "lucide-react";
import { api, type Capability } from "../lib/api";
import { Badge, Callout, ChainMark, EmptyState, ErrorState, Loading, Panel } from "../components/ui";

interface IntegrationRow {
  name: string;
  detail: string;
  chain?: string;
  status: "connected" | "configured" | "not_configured" | "not_built" | "partial";
  note: string;
}

function byKey(capabilities: Capability[]): Record<string, Capability> {
  return Object.fromEntries(capabilities.map((capability) => [capability.key, capability]));
}

function rpcRow(name: string, chain: string, capability: Capability | undefined): IntegrationRow {
  if (!capability) {
    return { name, chain, status: "not_configured", detail: "Capability not reported", note: "Unavailable" };
  }
  if (capability.configuration_status === "configured") {
    return {
      name,
      chain,
      status: "configured",
      detail: "RPC endpoint configured in this process",
      note: "The URL is never rendered; only whether it is configured.",
    };
  }
  return {
    name,
    chain,
    status: "not_configured",
    detail: "No RPC endpoint configured",
    note: "Configured value hidden by design; none is present.",
  };
}

/** Government connectors: status is read from the backend, never asserted here. */
function governmentRow(name: string, capability: Capability | undefined): IntegrationRow {
  if (!capability) {
    return { name, status: "not_configured", detail: "Capability not reported", note: "Unavailable" };
  }
  const status: IntegrationRow["status"] =
    capability.implementation_status === "not_built"
      ? "not_built"
      : capability.configuration_status === "not_configured"
        ? "not_configured"
        : "partial";
  return {
    name,
    status,
    detail: "Complaint-system connector",
    note: capability.detail || "Not built and not configured by policy.",
  };
}

export default function IntegrationsPage() {
  const capabilities = useQuery({ queryKey: ["demo", "capabilities"], queryFn: api.demo.capabilities });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });

  if (capabilities.isLoading) return <Loading rows={6} />;
  if (capabilities.isError)
    return <ErrorState message={(capabilities.error as Error).message} onRetry={() => capabilities.refetch()} />;

  const caps = byKey(capabilities.data?.capabilities ?? []);
  const rows: IntegrationRow[] = [
    {
      name: "TRON provider (TronGrid)",
      chain: "tron",
      status: caps.tron_acquisition?.configuration_status === "configured" ? "configured" : "not_configured",
      detail: "TRON/TRC-20 acquisition adapter",
      note: caps.tron_acquisition?.historical_live_run_recorded
        ? "Historical LIVE validation bundle on file."
        : "No historical LIVE bundle on file.",
    },
    rpcRow("Ethereum Mainnet RPC", "ethereum", caps.evm_token_tracing),
    rpcRow("BNB Smart Chain RPC", "bsc", caps.bsc_token_tracing),
    rpcRow("Base Mainnet RPC", "base", caps.base_token_tracing),
    {
      name: "Circle Iris API (CCTP V2)",
      chain: "CCTP",
      status: caps.bridge_tracing?.historical_live_run_recorded ? "partial" : "not_configured",
      detail: "Attestation metadata for CCTP V2 cross-chain links",
      note: "Attestation is API-reported; local ECDSA verification is not executed.",
    },
    {
      name: "CLM (System-1 router)",
      status: caps.system1_investigation_routing?.configuration_status === "configured" ? "configured" : "not_configured",
      detail: "Optional action-ranking model, shadow mode only",
      note: "Shadow only; rules remain authoritative. Endpoint is never rendered.",
    },
    governmentRow("NCRP", caps.government_connectors),
    governmentRow("SAHYOG", caps.government_connectors),
  ];

  const assets = meta.data?.supported_assets ?? [];

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Integrations</h1>
          <p>
            Provider and connector status. Secret values are never rendered — only whether a setting
            is present. &ldquo;Configured&rdquo; is not the same as &ldquo;live-verified&rdquo;.
          </p>
        </div>
      </div>

      <Panel title="Providers & connectors">
        {rows.length === 0 ? (
          <EmptyState icon={Plug} title="No integrations reported" />
        ) : (
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Integration</th>
                    <th>Chain</th>
                    <th>Status</th>
                    <th>Detail</th>
                    <th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.name}>
                      <td style={{ color: "var(--text-primary)" }}>{row.name}</td>
                      <td>{row.chain ? <ChainMark chain={row.chain} /> : "—"}</td>
                      <td>
                        <Badge
                          tone={
                            row.status === "configured"
                              ? "warning"
                              : row.status === "partial"
                                ? "cross-chain"
                                : row.status === "connected"
                                  ? "verified"
                                  : "neutral"
                          }
                        >
                          {row.status.replace(/_/g, " ")}
                        </Badge>
                      </td>
                      <td className="muted">{row.detail}</td>
                      <td className="muted">{row.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Panel>

      <Panel title="Configured assets (identity, not ticker)">
        <Callout title="Asset identity is (network, token contract).">
          A ticker is display metadata only. Verified issuer references are shown where present.
        </Callout>
        {assets.length === 0 ? (
          <div className="muted" style={{ marginTop: 8 }}>
            No assets are registered in the local database.
          </div>
        ) : (
          <div className="table-wrap" style={{ marginTop: "var(--space-3)" }}>
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Contract</th>
                    <th className="num">Decimals</th>
                    <th>Supported</th>
                    <th>Issuer reference</th>
                  </tr>
                </thead>
                <tbody>
                  {assets.map((asset) => (
                    <tr key={asset.token_contract ?? asset.display_symbol}>
                      <td className="mono">{asset.display_symbol}</td>
                      <td className="mono">{asset.token_contract ?? "native"}</td>
                      <td className="num">{asset.decimals}</td>
                      <td>
                        <Badge tone={asset.is_supported ? "verified" : "neutral"}>
                          {asset.is_supported ? "supported" : "not supported"}
                        </Badge>
                      </td>
                      <td className="muted">{asset.issuer_reference ?? "—"}</td>
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
