import { useQuery } from "@tanstack/react-query";
import { Radar } from "lucide-react";
import { useState } from "react";
import { caseApi, useSession, watchApi } from "../lib/auth";
import { formatTime } from "../lib/format";
import { selectStyle } from "../lib/styles";
import { LoginPanel } from "../components/LoginPanel";
import { Badge, Callout, ErrorState, Loading, Panel } from "../components/ui";

export default function MonitoringPage() {
  const session = useSession();
  const [caseId, setCaseId] = useState<string>("");

  const cases = useQuery({ queryKey: ["cases"], queryFn: caseApi.list, enabled: Boolean(session.data), retry: false });
  const watches = useQuery({
    queryKey: ["watches", caseId],
    queryFn: () => watchApi.list(caseId),
    enabled: Boolean(caseId),
  });

  if (session.isLoading) return <Loading rows={4} />;
  if (!session.data) {
    return (
      <div className="stack lg">
        <div className="page-head">
          <div>
            <h1>Live Monitoring</h1>
            <p>Case-scoped watches and checkpointed polling.</p>
          </div>
        </div>
        <LoginPanel intro="Watches are case-scoped and require a signed-in session. Monitoring polls indexed provider history; it is not a mempool feed and is CLI-driven rather than always-on." />
      </div>
    );
  }

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Live Monitoring</h1>
          <p>Checkpointed polling of watched addresses. This is indexed-history polling, not a mempool feed.</p>
        </div>
      </div>

      <Callout tone="warning" icon={Radar} title="Monitoring mode: polling (CLI-driven).">
        A poll runs from <code>scripts/poll_watches.py --once</code>, not from an always-on
        background monitor. No live poll against the real provider is verified in this deployment.
      </Callout>

      {cases.isLoading ? (
        <Loading rows={3} />
      ) : cases.isError ? (
        <ErrorState message={(cases.error as Error).message} onRetry={() => cases.refetch()} />
      ) : (cases.data ?? []).length === 0 ? (
        <Panel title="Watches">
          <div className="muted">No cases exist in this organization. Create one under Case Intake.</div>
        </Panel>
      ) : (
        <Panel
          title="Watches"
          actions={
            <select value={caseId} onChange={(event) => setCaseId(event.target.value)} style={selectStyle}>
              <option value="">Select a case…</option>
              {(cases.data ?? []).map((record) => (
                <option key={record.id} value={record.id}>
                  {record.case_reference}
                </option>
              ))}
            </select>
          }
        >
          {!caseId ? (
            <div className="muted">Select a case to list its watches.</div>
          ) : watches.isLoading ? (
            <Loading rows={3} />
          ) : watches.isError ? (
            <ErrorState message={(watches.error as Error).message} onRetry={() => watches.refetch()} />
          ) : (watches.data ?? []).length === 0 ? (
            <div className="muted">
              No watches are configured for this case. Watches are created through the case API.
            </div>
          ) : (
            <div className="table-wrap">
              <div className="table-scroll" style={{ maxHeight: "none" }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Address</th>
                      <th>Network</th>
                      <th>Status</th>
                      <th>Last checkpoint</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(watches.data ?? []).map((watch) => (
                      <tr key={watch.id}>
                        <td className="mono">{watch.address}</td>
                        <td className="mono">{watch.network_key}</td>
                        <td>
                          <Badge tone="neutral">{watch.status}</Badge>
                        </td>
                        <td className="muted nowrap">{formatTime(watch.last_checkpoint_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
