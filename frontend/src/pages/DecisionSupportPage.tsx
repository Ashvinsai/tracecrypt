import { useQuery } from "@tanstack/react-query";
import { Gavel, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { api, type RoutingScenario } from "../lib/api";
import { humanize, percent } from "../lib/format";
import { Badge, Callout, EmptyState, ErrorState, Loading, Panel } from "../components/ui";

export default function DecisionSupportPage() {
  const routing = useQuery({ queryKey: ["demo", "routing"], queryFn: api.demo.routing });
  const [index, setIndex] = useState(0);

  if (routing.isLoading) return <Loading rows={6} />;
  if (routing.isError)
    return <ErrorState message={(routing.error as Error).message} onRetry={() => routing.refetch()} />;

  const bundles = routing.data?.bundles ?? [];
  const comparisons = routing.data?.comparisons ?? [];
  if (bundles.length === 0) {
    return (
      <EmptyState icon={Gavel} title="No routing validation bundle on file">
        No System-1 routing shadow-validation bundle is present in this checkout.
      </EmptyState>
    );
  }

  const bundle = bundles[0];
  const summary = bundle.summary as Record<string, number | string>;
  const scenarios = bundle.scenarios ?? [];
  const scenario: RoutingScenario | undefined = scenarios[index];
  const crossChain = summary.cross_chain_comparison as
    | {
        production_selected_action?: string;
        production_clm_choice?: string;
        production_clm_probs?: Record<string, number>;
        finding?: string;
      }
    | undefined;
  const failure = summary.failure_test_result as
    | { router_requested?: string; router_used?: string; shadow_status?: string; fallback_successful?: boolean; shadow_failure_reason?: string }
    | undefined;
  const safety = summary.adversarial_safety_result as
    | { injected_candidates?: string[]; actual_selected_action?: string; forbidden_actions_rejected?: boolean; unsafe_action_execution_rate?: number }
    | undefined;

  return (
    <div className="stack lg">
      <div className="page-head">
        <div>
          <h1>Decision Support</h1>
          <p>
            The System-1 investigation router ranks predefined actions over deterministic evidence.
            Deterministic rules remain authoritative; the CLM runs in shadow mode. This is decision
            support metadata, not blockchain evidence and not an AI fraud classifier.
          </p>
        </div>
      </div>

      <Callout tone="decision" icon={ShieldAlert} title="DECISION SUPPORT METADATA — NOT BLOCKCHAIN EVIDENCE.">
        Relative action scores are uncalibrated model preferences and did not control execution.
        Deterministic rules kept strict control with 0% unsafe execution.
      </Callout>

      <div className="metric-row">
        <div className="metric">
          <div className="metric-value">{String(summary.scenario_count ?? scenarios.length)}</div>
          <div className="metric-label">Evaluation scenarios</div>
        </div>
        <div className="metric">
          <div className="metric-value">{percent(Number(summary.rules_clm_top1_agreement))}</div>
          <div className="metric-label">Rules / CLM top-1 agreement</div>
        </div>
        <div className="metric">
          <div className="metric-value">{percent(Number(summary.clm_top3_coverage_of_curated_preferred_action))}</div>
          <div className="metric-label">CLM top-3 coverage</div>
        </div>
        <div className="metric">
          <div className="metric-value">{percent(Number(summary.unsafe_action_execution_rate))}</div>
          <div className="metric-label">Unsafe execution rate</div>
        </div>
        <div className="metric">
          <div className="metric-value">{Math.round(Number(summary.median_clm_latency_ms))} ms</div>
          <div className="metric-label">Median CLM latency</div>
        </div>
      </div>

      <Panel
        title="Scenario routing decision"
        actions={
          <select value={index} onChange={(event) => setIndex(Number(event.target.value))}>
            {scenarios.map((item, itemIndex) => (
              <option key={item.scenario_id} value={itemIndex}>
                {item.scenario_id}
              </option>
            ))}
          </select>
        }
      >
        {scenario ? (
          <div className="stack lg">
            <div className="row wrap">
              <Badge tone="decision">Artifact class: DECISION_SUPPORT_METADATA</Badge>
              <Badge tone={scenario.shadow_agreement ? "verified" : "warning"}>
                {scenario.shadow_agreement ? "Rules / CLM agree" : "Rules / CLM disagree — rules retained control"}
              </Badge>
              <Badge tone="neutral">{scenario.scenario_source}</Badge>
            </div>

            <div className="grid cols-2">
              <div className="stack">
                <div className="eyebrow">Actual action (authoritative)</div>
                <div className="mono" style={{ fontSize: 15, color: "var(--text-primary)" }}>
                  {scenario.actual_selected_action ?? "—"}
                </div>
                <div className="muted" style={{ fontSize: 11 }}>
                  Selected by deterministic rules. Expected: {scenario.expected_curated_action ?? "—"}
                </div>
                <div className="eyebrow" style={{ marginTop: 8 }}>
                  CLM shadow choice
                </div>
                <div className="mono" style={{ fontSize: 15, color: scenario.shadow_agreement ? "var(--evidence-verified)" : "var(--candidate)" }}>
                  {scenario.clm_choice ?? "—"}
                </div>
                <div className="muted" style={{ fontSize: 11 }}>
                  Shadow only — the model did not execute anything.
                </div>
                {scenario.shadow_agreement ? null : (
                  <div style={{ color: "var(--candidate)", fontSize: 11 }}>
                    Execution retained deterministic rule selection.
                  </div>
                )}
              </div>

              <div className="stack">
                <div className="eyebrow">CLM ranked actions (relative, uncalibrated)</div>
                {scenario.clm_relative_action_probabilities ? (
                  Object.entries(scenario.clm_relative_action_probabilities)
                    .sort((a, b) => b[1] - a[1])
                    .map(([action, score]) => (
                      <div className="row" key={action} style={{ gap: 10 }}>
                        <span className="mono" style={{ minWidth: 220 }}>
                          {action}
                        </span>
                        <span className="mono muted">{score.toFixed(3)}</span>
                      </div>
                    ))
                ) : (
                  <div className="muted">No CLM probabilities recorded.</div>
                )}
              </div>
            </div>

            <div>
              <div className="eyebrow">Deterministic policy guard</div>
              <div className="table-wrap" style={{ marginTop: 6 }}>
                <div className="table-scroll" style={{ maxHeight: "none" }}>
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Action</th>
                        <th>Decision</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.values(scenario.guard_results ?? {}).map((guard) => (
                        <tr key={guard.action_key}>
                          <td className="mono">{guard.action_key}</td>
                          <td>
                            <Badge tone={guard.decision === "ALLOWED" ? "verified" : "danger"}>{guard.decision}</Badge>
                          </td>
                          <td className="muted">{guard.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </Panel>

      <div className="grid cols-2">
        <Panel title="Cross-chain routing case">
          {crossChain ? (
            <div className="stack">
              <dl className="dl">
                <dt>Actual action</dt>
                <dd className="mono">{crossChain.production_selected_action ?? "—"}</dd>
                <dt>CLM shadow choice</dt>
                <dd className="mono">{crossChain.production_clm_choice ?? "—"}</dd>
              </dl>
              {crossChain.finding ? (
                <p className="muted" style={{ fontSize: 12 }}>
                  {crossChain.finding}
                </p>
              ) : null}
            </div>
          ) : (
            <div className="muted">No cross-chain comparison recorded.</div>
          )}
        </Panel>

        <Panel title="Failure & safety fallbacks">
          <div className="stack">
            {failure ? (
              <dl className="dl">
                <dt>Requested router</dt>
                <dd className="mono">{failure.router_requested}</dd>
                <dt>Router used</dt>
                <dd className="mono">{failure.router_used}</dd>
                <dt>Shadow status</dt>
                <dd>
                  <Badge tone={failure.shadow_status === "failed" ? "warning" : "verified"}>
                    {failure.shadow_status}
                  </Badge>
                </dd>
                <dt>Fallback</dt>
                <dd>{failure.fallback_successful ? "rules served the request" : "—"}</dd>
              </dl>
            ) : null}
            {safety ? (
              <div className="stack" style={{ gap: 4 }}>
                <div className="eyebrow">Adversarial injected actions</div>
                <div className="chip-row">
                  {(safety.injected_candidates ?? []).map((action) => (
                    <Badge key={action} tone={action.startsWith("FREEZE") || action.startsWith("DECLARE") ? "danger" : "neutral"}>
                      {action}
                    </Badge>
                  ))}
                </div>
                <div className="muted" style={{ fontSize: 12 }}>
                  Forbidden actions rejected: {String(safety.forbidden_actions_rejected)} · unsafe
                  execution rate {percent(Number(safety.unsafe_action_execution_rate))}
                </div>
              </div>
            ) : null}
          </div>
        </Panel>
      </div>

      {comparisons.length > 0 ? (
        <Panel title="Cross-stage comparison">
          <div className="table-wrap">
            <div className="table-scroll" style={{ maxHeight: "none" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th className="num">Scenarios</th>
                    <th className="num">Top-1 agreement</th>
                    <th className="num">Top-3 coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {comparisons.flatMap(({ name, comparison }) =>
                    Object.entries((comparison.stages as Record<string, Record<string, number>>) ?? {}).map(
                      ([stage, values]) => (
                        <tr key={`${name}-${stage}`}>
                          <td className="mono">{stage}</td>
                          <td className="num">{values.total_scenarios}</td>
                          <td className="num">{percent(values.top1_agreement_rate)}</td>
                          <td className="num">{percent(values.top3_coverage_rate)}</td>
                        </tr>
                      ),
                    ),
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </Panel>
      ) : null}

      <Panel title="Model & environment">
        <dl className="dl">
          {Object.entries((bundle.manifest.metadata as Record<string, string>) ?? {})
            .filter(([key]) => !/key|token|secret|url/i.test(key))
            .map(([key, value]) => (
              <div key={key} style={{ display: "contents" }}>
                <dt>{humanize(key)}</dt>
                <dd className="mono" style={{ fontSize: 11 }}>
                  {String(value)}
                </dd>
              </div>
            ))}
        </dl>
        <Callout title="Notice.">{String(bundle.manifest.caveat ?? "")}</Callout>
      </Panel>
    </div>
  );
}
