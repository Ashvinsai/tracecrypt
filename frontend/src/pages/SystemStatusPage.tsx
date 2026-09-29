import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { useState } from "react";
import { api, type Capability } from "../lib/api";
import { implementationStatus } from "../lib/status";
import { inputStyle } from "../lib/styles";
import { Badge, EmptyState, ErrorState, Loading, Panel, StatusBadge } from "../components/ui";

export default function SystemStatusPage() {
  const capabilities = useQuery({ queryKey: ["demo", "capabilities"], queryFn: api.demo.capabilities });
  const [filter, setFilter] = useState("");

  if (capabilities.isLoading) return <Loading rows={8} />;
  if (capabilities.isError)
    return <ErrorState message={(capabilities.error as Error).message} onRetry={() => capabilities.refetch()} />;

  const rows = (capabilities.data?.capabilities ?? []).filter((row) =>
    `${row.label} ${row.key} ${row.detail}`.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>System Capabilities</h1>
          <p>
            One implementation / configuration / live-verification model, read from the backend — not
            hardcoded in this UI. A recorded successful LIVE run is reported as{" "}
            <strong>historical</strong>; it never makes the current deployment live-verified.
          </p>
        </div>
        <div className="head-actions">
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter capabilities…"
            style={inputStyle}
            aria-label="Filter capabilities"
          />
        </div>
      </div>

      {rows.length === 0 ? (
        <EmptyState icon={Activity} title="No capability matches">
          No capability matches that filter.
        </EmptyState>
      ) : (
        <Panel title={`${rows.length} capabilities`} bodyClass="tight">
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Capability</th>
                    <th>Implementation</th>
                    <th>Configuration</th>
                    <th>Live verified</th>
                    <th>Historical run</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <CapabilityRow key={row.key} capability={row} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}

function CapabilityRow({ capability }: { capability: Capability }) {
  return (
    <tr>
      <td className="nowrap">
        <div style={{ color: "var(--text-primary)", fontWeight: 550 }}>{capability.label}</div>
        <span className="mono muted" style={{ fontSize: 10 }}>
          {capability.key}
        </span>
      </td>
      <td>
        <StatusBadge descriptor={implementationStatus(capability.implementation_status)} />
      </td>
      <td>
        <Badge tone={capability.configuration_status === "configured" ? "warning" : "neutral"}>
          {capability.configuration_status.replace(/_/g, " ")}
        </Badge>
      </td>
      <td>
        {capability.live_verified ? (
          <Badge tone="verified" title="Verified live in this deployment">
            Verified
          </Badge>
        ) : (
          <Badge tone="neutral" title="Configuration is not the same as a live verification">
            Not verified
          </Badge>
        )}
      </td>
      <td>
        {capability.historical_live_run_recorded ? (
          <Badge tone="cross-chain" title="A historical bundle is on file; not current live verification">
            on file
          </Badge>
        ) : (
          <Badge tone="neutral">none</Badge>
        )}
      </td>
      <td className="muted" style={{ maxWidth: 560 }}>
        {capability.detail}
      </td>
    </tr>
  );
}
