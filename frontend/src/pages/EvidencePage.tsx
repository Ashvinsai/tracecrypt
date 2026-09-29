import { useQuery } from "@tanstack/react-query";
import { FileJson, Info, PackageCheck, RotateCcw } from "lucide-react";
import { api } from "../lib/api";
import { formatTime } from "../lib/format";
import { Badge, Callout, CopyableValue, EmptyState, ErrorState, Loading, Panel } from "../components/ui";

export default function EvidencePage() {
  const evidence = useQuery({ queryKey: ["demo", "evidence"], queryFn: api.demo.evidence });

  if (evidence.isLoading) return <Loading rows={5} />;
  if (evidence.isError)
    return <ErrorState message={(evidence.error as Error).message} onRetry={() => evidence.refetch()} />;

  const bundles = evidence.data?.bundles ?? [];

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Evidence Explorer</h1>
          <p>
            Saved evidence-export bundles. Each manifest is re-hashed on read. A hash match shows the
            files are unchanged since the run — it is not proof the attribution is correct or
            admissible.
          </p>
        </div>
      </div>

      <Panel title="Replay & integrity model">
        <div className="grid cols-3">
          <Step title="LIVE acquisition" body="Captured from a provider during a bounded run." />
          <Step title="Captured evidence" body="Raw provider exchanges and normalized transfers written to disk." />
          <Step title="Offline replay" body="Re-run with networking disabled; identical results, zero network calls." />
        </div>
        <Callout icon={RotateCcw} title="Why this matters.">
          Offline replay through the same pipeline is what makes the result reproducible without a
          chain connection. The replayed bundles are labelled RECORDED PUBLIC, never LIVE.
        </Callout>
      </Panel>

      {bundles.length === 0 ? (
        <EmptyState icon={FileJson} title="No evidence-export bundle on file">
          No saved export bundle is present in this checkout.
        </EmptyState>
      ) : (
        bundles.map((bundle) => {
          const manifest = bundle.manifest as {
            request_id?: string;
            data_mode?: string;
            coverage_status?: string;
            generated_at?: string;
            caveat?: string;
            files?: Record<string, string>;
          };
          const files = Object.entries(manifest.files ?? {});
          const fileStatus = new Map(bundle.integrity.files.map((file) => [file.file, file.status]));
          return (
            <Panel
              key={bundle.run_id}
              title={`Bundle ${bundle.run_id}`}
              actions={
                bundle.integrity.available ? (
                  <Badge tone={bundle.integrity.failed === 0 && bundle.integrity.missing === 0 ? "verified" : "danger"} icon={PackageCheck}>
                    {bundle.integrity.ok}/{bundle.integrity.checked} verified
                  </Badge>
                ) : (
                  <Badge tone="neutral">no manifest</Badge>
                )
              }
            >
              <div className="stack">
                <dl className="dl">
                  <dt>Request / preset</dt>
                  <dd className="mono">{manifest.request_id ?? "—"}</dd>
                  <dt>Data mode</dt>
                  <dd>
                    <Badge tone="cross-chain">{manifest.data_mode ?? "—"}</Badge>
                  </dd>
                  <dt>Coverage</dt>
                  <dd>{manifest.coverage_status ?? "—"}</dd>
                  <dt>Generated</dt>
                  <dd>{formatTime(manifest.generated_at ?? null)}</dd>
                  <dt>Printable report</dt>
                  <dd>
                    {manifest.request_id ? (
                      <a
                        href={`/console/evidence/${encodeURIComponent(manifest.request_id)}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open deterministic evidence report
                      </a>
                    ) : (
                      "—"
                    )}
                  </dd>
                </dl>
                <div className="table-wrap">
                  <div className="table-scroll" style={{ maxHeight: "none" }}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>File</th>
                          <th>Type</th>
                          <th>SHA-256</th>
                          <th>Integrity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {files.map(([name, hash]) => (
                          <tr key={name}>
                            <td className="mono">{name}</td>
                            <td className="muted">{name.split(".").pop()?.toUpperCase()}</td>
                            <td>
                              <CopyableValue value={hash} head={12} tail={8} label="hash" />
                            </td>
                            <td>
                              <Badge tone={fileStatus.get(name) === "ok" ? "verified" : "danger"}>
                                {fileStatus.get(name) ?? "unknown"}
                              </Badge>
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
            </Panel>
          );
        })
      )}
    </div>
  );
}

function Step({ title, body }: { title: string; body: string }) {
  return (
    <div className="panel" style={{ background: "var(--surface-2)" }}>
      <div className="panel-body">
        <strong>{title}</strong>
        <p className="muted" style={{ margin: "6px 0 0", fontSize: 12 }}>
          {body}
        </p>
      </div>
    </div>
  );
}
