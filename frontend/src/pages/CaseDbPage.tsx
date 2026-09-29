import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ScanLine, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { caseApi, useSession } from "../lib/auth";
import { formatTime } from "../lib/format";
import { dataMode } from "../lib/status";
import { inputStyle } from "../lib/styles";
import { LoginPanel } from "../components/LoginPanel";
import { Badge, Callout, CopyableValue, EmptyState, ErrorState, Loading, Panel, StatusBadge } from "../components/ui";

export default function CaseDbPage() {
  const session = useSession();
  const client = useQueryClient();
  const [reference, setReference] = useState("");
  const [title, setTitle] = useState("");
  const [network, setNetwork] = useState("tron");
  const [address, setAddress] = useState("");
  const [validation, setValidation] = useState<{ valid: boolean; canonical_address?: string; reason?: string } | null>(null);
  const [validating, setValidating] = useState(false);

  const cases = useQuery({
    queryKey: ["cases"],
    queryFn: caseApi.list,
    enabled: Boolean(session.data),
    retry: false,
  });

  if (session.isLoading) return <Loading rows={4} />;
  if (!session.data) {
    return (
      <div className="stack lg">
        <div className="page-head">
          <div>
            <h1>Case Intake</h1>
            <p>Complaint and case intake against the organization-scoped case API.</p>
          </div>
        </div>
        <LoginPanel intro="Every case and seed route is organization-scoped server-side. Run make seed-demo to create the local demo account, or sign in with an existing account." />
      </div>
    );
  }

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Case Intake</h1>
          <p>
            Signed in as <strong>{session.data.email}</strong> ·{" "}
            {session.data.organizations.map((organization) => organization.name).join(", ")}
          </p>
        </div>
      </div>

      <div className="grid cols-2">
        <Panel title="New investigation">
          <form
            className="stack"
            onSubmit={async (event) => {
              event.preventDefault();
              await caseApi.create({ case_reference: reference, title });
              setReference("");
              setTitle("");
              client.invalidateQueries({ queryKey: ["cases"] });
            }}
          >
            <label className="stack" style={{ gap: 4 }}>
              <span className="muted" style={{ fontSize: 11 }}>
                Complaint / case reference
              </span>
              <input value={reference} onChange={(event) => setReference(event.target.value)} required style={inputStyle} />
            </label>
            <label className="stack" style={{ gap: 4 }}>
              <span className="muted" style={{ fontSize: 11 }}>
                Title
              </span>
              <input value={title} onChange={(event) => setTitle(event.target.value)} required style={inputStyle} />
            </label>
            <button type="submit" className="btn primary" style={{ alignSelf: "flex-start" }}>
              Create investigation
            </button>
          </form>
        </Panel>

        <Panel title="Validate a reported wallet address">
          <div className="stack">
            <Callout icon={ShieldCheck} title="Address validation checks syntax only.">
              It verifies network compatibility. It does <strong>not</strong> establish ownership, and a
              network is never inferred from the address string.
            </Callout>
            <div className="row wrap" style={{ gap: 8 }}>
              <select value={network} onChange={(event) => setNetwork(event.target.value)} style={inputStyle}>
                <option value="tron">TRON</option>
                <option value="ethereum">Ethereum</option>
                <option value="bsc">BNB Smart Chain</option>
                <option value="base">Base</option>
              </select>
              <input
                value={address}
                onChange={(event) => setAddress(event.target.value)}
                placeholder="Reported wallet address"
                style={{ ...inputStyle, flex: 1 }}
              />
              <button
                type="button"
                className="btn"
                disabled={validating || !address}
                onClick={async () => {
                  setValidating(true);
                  try {
                    setValidation(await caseApi.validateAddress(network, address));
                  } finally {
                    setValidating(false);
                  }
                }}
              >
                Validate
              </button>
            </div>
            {validation ? (
              <div className="stack" style={{ gap: 4 }}>
                <Badge tone={validation.valid ? "verified" : "danger"}>
                  {validation.valid ? "valid on this network" : "invalid"}
                </Badge>
                {validation.canonical_address ? (
                  <CopyableValue value={validation.canonical_address} head={10} tail={8} label="canonical address" />
                ) : null}
                {validation.reason ? <span className="muted">{validation.reason}</span> : null}
              </div>
            ) : null}
          </div>
        </Panel>
      </div>

      <Panel title="Cases in this organization">
        {cases.isLoading ? (
          <Loading rows={3} />
        ) : cases.isError ? (
          <ErrorState message={(cases.error as Error).message} onRetry={() => cases.refetch()} />
        ) : (cases.data ?? []).length === 0 ? (
          <EmptyState icon={ScanLine} title="No cases yet">
            Create one above. Seeding the demo database (<code>make seed-demo</code>) also loads a
            synthetic fixture case.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Reference</th>
                    <th>Title</th>
                    <th>Mode</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {(cases.data ?? []).map((record) => (
                    <tr key={record.id}>
                      <td className="mono">{record.case_reference}</td>
                      <td>{record.title}</td>
                      <td>
                        <StatusBadge descriptor={dataMode(record.data_mode)} />
                      </td>
                      <td className="muted nowrap">{formatTime(record.created_at)}</td>
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
