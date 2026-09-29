import { useQuery } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import { formatTime, humanize, truncate } from "../lib/format";
import { reviewState } from "../lib/status";
import { Badge, Callout, CopyableValue, EmptyState, ErrorState, Loading, Panel, StatusBadge } from "../components/ui";

export default function AttributionPage() {
  const presets = useQuery({ queryKey: ["demo", "presets"], queryFn: api.demo.presets });
  const candidates = useQuery({ queryKey: ["demo", "candidates"], queryFn: api.demo.candidates });

  if (presets.isLoading || candidates.isLoading) return <Loading rows={6} />;
  if (presets.isError)
    return <ErrorState message={(presets.error as Error).message} onRetry={() => presets.refetch()} />;

  const reports = candidates.data?.reports ?? [];
  const verified = reports
    .map((report) => ({ runId: report.run_id, anchor: report.report.anchor }))
    .filter((entry) => entry.anchor && Object.keys(entry.anchor).length > 0);

  const allCandidates = reports.flatMap((report) =>
    (report.report.candidates ?? []).map((candidate) => ({
      runId: report.run_id,
      candidate: candidate as Record<string, unknown>,
    })),
  );

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Attribution &amp; VASP Intelligence</h1>
          <p>
            Verified service-control claims are kept strictly separate from candidate leads. A
            candidate is an observed relationship, never ownership, service control, or guilt.
          </p>
        </div>
      </div>

      <Panel title="Verified service boundaries (reviewed service control)">
        {verified.length === 0 ? (
          <EmptyState icon={ShieldCheck} title="No reviewed service-control claims on file">
            The reviewed registry and saved candidate-neighborhood reports hold no accepted
            service-control anchor in this checkout.
          </EmptyState>
        ) : (
          <div className="stack lg">
            {verified.map(({ runId, anchor }) => (
              <div className="stack" key={runId}>
                <div className="row wrap">
                  <Badge tone="verified" icon={ShieldCheck}>
                    REVIEWED SERVICE CONTROL
                  </Badge>
                  <Badge tone="neutral">{anchor.entity_name}</Badge>
                  <Badge tone="neutral">{runId}</Badge>
                </div>
                <dl className="dl">
                  <dt>Observed address</dt>
                  <dd>
                    <CopyableValue value={anchor.address} head={10} tail={8} label="anchor address" />
                  </dd>
                  <dt>Evidence type</dt>
                  <dd>{humanize(anchor.assertion_type)}</dd>
                  <dt>Review state</dt>
                  <dd>
                    <StatusBadge descriptor={reviewState(anchor.review_state)} />
                  </dd>
                  <dt>Validity</dt>
                  <dd>
                    {formatTime(anchor.valid_from)} → {formatTime(anchor.valid_to)}
                  </dd>
                  <dt>Source</dt>
                  <dd className="mono" style={{ fontSize: 11, overflowWrap: "anywhere" }}>
                    {anchor.source_reference}
                  </dd>
                  <dt>Source hash</dt>
                  <dd>
                    <CopyableValue value={anchor.source_hash} head={12} tail={8} label="source hash" />
                  </dd>
                </dl>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Investigative leads (candidate relationships)">
        {allCandidates.length === 0 ? (
          <EmptyState icon={ShieldAlert} title="No candidate relationships">
            No bounded discovery report in this checkout surfaced a deposit candidate.
          </EmptyState>
        ) : (
          <div className="stack lg">
            <Callout tone="candidate" title="Candidate relationship — not ownership evidence.">
              These leads are generated from observed transactions by a conservative rule. They never
              become a verified service boundary and cannot terminate a trace.
            </Callout>
            <div className="table-wrap">
              <div className="table-scroll" style={{ maxHeight: "none" }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Address</th>
                      <th>Candidate type</th>
                      <th>Anchor</th>
                      <th>Review</th>
                      <th>First seen</th>
                      <th>Last seen</th>
                      <th>Evidence refs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {allCandidates.map(({ runId, candidate }) => {
                      const anchor = candidate.anchor as { entity_name?: string } | undefined;
                      return (
                        <tr key={`${runId}-${String(candidate.address)}`}>
                          <td>
                            <CopyableValue value={String(candidate.address)} head={8} tail={6} label="candidate" />
                          </td>
                          <td>
                            <Badge tone="candidate">{String(candidate.relationship_type)}</Badge>
                          </td>
                          <td>{anchor?.entity_name ?? "—"}</td>
                          <td>
                            <StatusBadge descriptor={reviewState(String(candidate.review_status))} />
                          </td>
                          <td className="nowrap muted">{formatTime(String(candidate.first_observed_at ?? ""))}</td>
                          <td className="nowrap muted">{formatTime(String(candidate.last_observed_at ?? ""))}</td>
                          <td className="mono">
                            {truncate((candidate.evidence_references as string[] | undefined)?.[0] ?? "—", 12, 6)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
