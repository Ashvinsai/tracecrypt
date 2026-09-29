import { useQuery } from "@tanstack/react-query";
import { Boxes, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { api, type PresetSummary } from "../lib/api";
import { truncate } from "../lib/format";
import { dataMode } from "../lib/status";
import { Badge, ChainMark, ErrorState, Loading, Panel, StatusBadge } from "../components/ui";

export default function DemoCasesPage() {
  const presets = useQuery({ queryKey: ["demo", "presets"], queryFn: api.demo.presets });

  if (presets.isLoading) return <Loading rows={6} />;
  if (presets.isError)
    return <ErrorState message={(presets.error as Error).message} onRetry={() => presets.refetch()} />;

  const rows = presets.data?.presets ?? [];
  const recorded = rows.filter((row) => row.data_mode === "RECORDED_PUBLIC");
  const synthetic = rows.filter((row) => row.data_mode === "SYNTHETIC");

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Demo Cases</h1>
          <p>
            Saved, allow-listed trace bundles discovered on disk. Each is presented as{" "}
            <strong>RECORDED PUBLIC</strong> or <strong>SYNTHETIC</strong> — a saved file never wears
            a LIVE badge, whatever mode captured it.
          </p>
        </div>
      </div>

      <Group title="Public recorded validation" rows={recorded} />
      <Group title="Synthetic fixtures" rows={synthetic} />
    </div>
  );
}

function Group({ title, rows }: { title: string; rows: PresetSummary[] }) {
  if (rows.length === 0) return null;
  return (
    <Panel title={title}>
      <div className="grid cols-2">
        {rows.map((row) => (
          <article key={row.id} className="panel" style={{ background: "var(--surface-2)" }}>
            <div className="panel-body stack">
              <div className="row wrap">
                <StatusBadge descriptor={dataMode(row.data_mode)} />
                <ChainMark chain={row.network} />
                {row.known_service > 0 ? (
                  <Badge tone="verified">{row.outcome_service ?? "verified boundary"}</Badge>
                ) : null}
                {row.candidate > 0 ? <Badge tone="candidate">{row.candidate} candidate</Badge> : null}
                {row.unresolved > 0 ? <Badge tone="neutral">{row.unresolved} unresolved</Badge> : null}
              </div>
              <div>
                <strong>{row.id}</strong>
                <p className="muted mono" style={{ margin: "2px 0 0", fontSize: 11 }}>
                  {truncate(row.address, 10, 8)}
                </p>
              </div>
              <div className="muted" style={{ fontSize: 11 }}>
                {row.observed_transfers} transfers · {row.branch_endings} branch endings ·{" "}
                {row.integrity.available ? `manifest ${row.integrity.ok}/${row.integrity.checked}` : "no manifest"}
              </div>
              <div className="row wrap" style={{ gap: 6 }}>
                <Link className="btn sm primary" to={`/cases/${encodeURIComponent(row.id)}`}>
                  <Boxes size={13} /> Open workspace
                </Link>
                {row.data_mode === "RECORDED_PUBLIC" ? (
                  <a
                    className="btn sm"
                    href={`/console/evidence/${encodeURIComponent(row.id)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink size={13} /> Evidence report
                  </a>
                ) : null}
              </div>
            </div>
          </article>
        ))}
      </div>
    </Panel>
  );
}

export function CrossChainShortcut() {
  return (
    <Link className="btn sm" to="/cross-chain">
      Cross-chain evidence
    </Link>
  );
}
