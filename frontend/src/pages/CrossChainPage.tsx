import { useQuery } from "@tanstack/react-query";
import { Link2, Waypoints } from "lucide-react";
import { api } from "../lib/api";
import { formatTime } from "../lib/format";
import { Callout, EmptyState, ErrorState, Loading, Panel, StatusBadge } from "../components/ui";
import { CctpLinkPanel } from "./CaseWorkspacePage";
import { Badge } from "../components/ui";

export default function CrossChainPage() {
  const cctp = useQuery({ queryKey: ["demo", "cctp"], queryFn: api.demo.cctp });

  if (cctp.isLoading) return <Loading rows={5} />;
  if (cctp.isError)
    return <ErrorState message={(cctp.error as Error).message} onRetry={() => cctp.refetch()} />;

  const bundles = cctp.data?.bundles ?? [];

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Cross-Chain Investigation</h1>
          <p>
            Protocol-verifiable cross-chain continuation. Supported deliberately for{" "}
            <strong>Circle CCTP V2</strong> only, on the{" "}
            <strong>Ethereum Mainnet to Base Mainnet USDC</strong> route. Other bridges and asset
            changes are unsupported boundaries — the tracer stops rather than inventing a link.
          </p>
        </div>
      </div>

      {bundles.length === 0 ? (
        <EmptyState icon={Link2} title="No cross-chain validation bundle on file">
          No Circle CCTP V2 bundle is present in this checkout.
        </EmptyState>
      ) : (
        bundles.map((bundle) => (
          <div className="stack lg" key={bundle.run_id}>
            <Panel
              title={`Validation bundle ${bundle.run_id}`}
              actions={
                <>
                  <Badge tone="cross-chain">{bundle.route}</Badge>
                  <StatusBadge descriptor={{ tone: "cross-chain", label: bundle.presented_data_mode, meaning: "Presented as saved public evidence" }} />
                </>
              }
            >
              <div className="stack">
                <dl className="dl">
                  <dt>Capture mode</dt>
                  <dd>{bundle.capture_data_mode ?? "—"}</dd>
                  <dt>Manifest integrity</dt>
                  <dd>
                    {bundle.integrity.available ? (
                      <Badge tone={bundle.integrity.failed === 0 ? "verified" : "danger"}>
                        {bundle.integrity.ok}/{bundle.integrity.checked} verified
                      </Badge>
                    ) : (
                      <Badge tone="neutral">no manifest</Badge>
                    )}
                  </dd>
                  <dt>Saved report</dt>
                  <dd>
                    <a href="/dashboard" target="_blank" rel="noreferrer">
                      Open saved bundle pages
                    </a>
                  </dd>
                </dl>
                <Callout icon={Waypoints} title="How to read this.">
                  The three columns below are the source blockchain, the protocol/API attestation,
                  and the destination blockchain. Circle API metadata (
                  <span className="mono">API_REPORTED_COMPLETE</span>) is shown as such and is never
                  presented as locally verified cryptographic proof.
                </Callout>
              </div>
            </Panel>
            <CctpLinkPanel link={bundle.link} />
            {bundle.transfers.length > 0 ? (
              <Panel title="Normalized protocol transfers">
                <div className="table-wrap">
                  <div className="table-scroll" style={{ maxHeight: "none" }}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Network</th>
                          <th>Event</th>
                          <th>From</th>
                          <th>To</th>
                          <th>Amount</th>
                          <th>Transaction</th>
                        </tr>
                      </thead>
                      <tbody>
                        {bundle.transfers.map((transfer, index) => {
                          const row = transfer as Record<string, string>;
                          return (
                            <tr key={index}>
                              <td className="mono">{row.network}</td>
                              <td>
                                <Badge tone="cross-chain">{row.event_type}</Badge>
                              </td>
                              <td className="mono">{row.from_address?.slice(0, 10)}…</td>
                              <td className="mono">{row.to_address?.slice(0, 10)}…</td>
                              <td className="mono">
                                {row.amount_base_units} ({row.asset_symbol})
                              </td>
                              <td className="mono">{row.transaction_hash?.slice(0, 12)}…</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </Panel>
            ) : null}
            {bundle.link.destination_block_time ? (
              <div className="muted" style={{ fontSize: 11 }}>
                Destination block time {formatTime(bundle.link.destination_block_time)} · source block
                time {formatTime(bundle.link.source_block_time)}
              </div>
            ) : null}
          </div>
        ))
      )}
    </div>
  );
}
