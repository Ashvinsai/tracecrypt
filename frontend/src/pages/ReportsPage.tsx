import { useQuery } from "@tanstack/react-query";
import { FileText, Info } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { Badge, Callout, EmptyState, ErrorState, Loading, Panel } from "../components/ui";

const SECTIONS = [
  "Executive summary",
  "Fund flow",
  "Chronological trace",
  "Verified VASP boundary",
  "Candidate leads",
  "Cross-chain evidence",
  "Coverage limitations",
  "Evidence manifest",
  "Decision support appendix",
];

const FORMATS = [
  { name: "HTML", detail: "Deterministic printable evidence report", available: true },
  { name: "JSON", detail: "Exact saved trace result", available: true },
  { name: "CSV", detail: "Per-table CSV exports in the bundle", available: true },
  { name: "PDF", detail: "Rendered from the same HTML the report serves", available: true },
  { name: "SVG", detail: "Vector graph export", available: false },
];

export default function ReportsPage() {
  const presets = useQuery({ queryKey: ["demo", "presets"], queryFn: api.demo.presets });
  const evidence = useQuery({ queryKey: ["demo", "evidence"], queryFn: api.demo.evidence });

  if (presets.isLoading) return <Loading rows={6} />;
  if (presets.isError)
    return <ErrorState message={(presets.error as Error).message} onRetry={() => presets.refetch()} />;

  const rows = (presets.data?.presets ?? []).filter((row) => row.data_mode !== "SYNTHETIC");
  const bundles = evidence.data?.bundles ?? [];

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <p>
            Deterministic, reproducible evidence outputs. Every report carries its limitations and a
            hashed manifest. Nothing is auto-submitted or impersonates an officer.
          </p>
        </div>
      </div>

      <div className="grid cols-2">
        <Panel title="Report sections">
          <div className="stack" style={{ gap: 6 }}>
            {SECTIONS.map((section) => (
              <label key={section} className="row" style={{ gap: 8 }}>
                <input type="checkbox" defaultChecked disabled aria-label={section} />
                <span>{section}</span>
              </label>
            ))}
            <Callout icon={Info} title="Read-only surface.">
              Generating a fresh export runs a trace through the authenticated API (
              <code>POST /api/v1/traces/export</code>). This workspace serves saved outputs; open a
              case to download its saved report and trace JSON.
            </Callout>
          </div>
        </Panel>

        <Panel title="Export formats">
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Format</th>
                    <th>Detail</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {FORMATS.map((format) => (
                    <tr key={format.name}>
                      <td className="mono">{format.name}</td>
                      <td className="muted">{format.detail}</td>
                      <td>
                        <Badge tone={format.available ? "verified" : "neutral"}>
                          {format.available ? "available" : "not available"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="Saved reports">
        {rows.length === 0 ? (
          <EmptyState icon={FileText} title="No saved reports" />
        ) : (
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Mode</th>
                    <th>Evidence report</th>
                    <th>Trace JSON</th>
                    <th>Manifest</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <Link to={`/cases/${encodeURIComponent(row.id)}`}>{row.id}</Link>
                      </td>
                      <td>
                        <Badge tone="cross-chain">{row.data_mode}</Badge>
                      </td>
                      <td>
                        <a href={`/console/evidence/${encodeURIComponent(row.id)}`} target="_blank" rel="noreferrer">
                          Open HTML
                        </a>
                      </td>
                      <td>
                        <a href={`/console/trace/${encodeURIComponent(row.id)}`} target="_blank" rel="noreferrer">
                          Download JSON
                        </a>
                      </td>
                      <td>
                        <Badge tone={row.integrity.available && row.integrity.failed === 0 ? "verified" : "neutral"}>
                          {row.integrity.available ? `${row.integrity.ok}/${row.integrity.checked}` : "none"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Panel>

      <Panel title="Evidence bundles with generated PDF">
        {bundles.length === 0 ? (
          <div className="muted">No generated PDF export bundles are present.</div>
        ) : (
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Bundle</th>
                    <th>Request</th>
                    <th>Formats in bundle</th>
                    <th>Integrity</th>
                  </tr>
                </thead>
                <tbody>
                  {bundles.map((bundle) => {
                    const files = Object.keys((bundle.manifest.files as Record<string, string>) ?? {});
                    const formats = files.map((file) => file.split(".").pop()?.toUpperCase());
                    return (
                      <tr key={bundle.run_id}>
                        <td className="mono">{bundle.run_id}</td>
                        <td className="mono">{String(bundle.manifest.request_id ?? "—")}</td>
                        <td>
                          <div className="chip-row">
                            {formats.map((format, index) => (
                              <Badge key={index} tone="neutral">
                                {format}
                              </Badge>
                            ))}
                          </div>
                        </td>
                        <td>
                          <Badge tone={bundle.integrity.failed === 0 && bundle.integrity.missing === 0 ? "verified" : "danger"}>
                            {bundle.integrity.ok}/{bundle.integrity.checked}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
