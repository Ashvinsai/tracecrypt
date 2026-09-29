import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CopyableValue } from "../components/ui";
import { Inspector } from "../components/Inspector";
import type { DemoPresetDetail } from "../lib/api";
import DecisionSupportPage from "../pages/DecisionSupportPage";
import IntegrationsPage from "../pages/IntegrationsPage";

function envelope(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      data,
      meta: {
        data_mode: "SYNTHETIC",
        request_id: "test",
        engine_version: "0.1.0",
        label_set_version: "0",
        analysis_cutoff: "2026-09-27T00:00:00+00:00",
      },
    }),
  } as unknown as Response;
}

function wrap(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("address display", () => {
  it("shows a truncated value but exposes the full value for copying", async () => {
    render(<CopyableValue value="0x38a1c011890bc95fd4b43b622e1432c859d097bc" head={6} tail={4} label="address" />);
    expect(screen.getByText("0x38a1…97bc")).toBeInTheDocument();
    expect(screen.getByTitle("0x38a1c011890bc95fd4b43b622e1432c859d097bc")).toBeInTheDocument();
  });
});

const candidateDetail = {
  id: "test",
  title: "test",
  scenario: "saved",
  data_mode: "RECORDED_PUBLIC",
  capture_data_mode: "LIVE",
  address: "TSeed",
  description: "",
  scope_note: "",
  error: null,
  warnings: [],
  has_outcome: false,
  has_comparison: false,
  has_report: false,
  trace: {
    seed: { address: "TSeed", event_reference: null, network_key: "tron", asset: { token_contract: null, display_symbol: "USDT", decimals: 6 } },
    scope: {},
    seed_transfer: null,
    observed_transfers: [],
    branch_endings: [
      {
        address: "TCandidate",
        endpoint_class: "deposit_candidate",
        attribution_status: "candidate",
        boundary_reason: null,
        hop_depth: 1,
        branch_path: [],
        arrival_event_reference: null,
        observed_amount_base_units: null,
        observed_amount_display: null,
        case_amount_basis: "allocation_unknown",
        label: null,
        note: "single observed transfer",
      },
    ],
    cross_chain_links: [],
    limitations: [],
    budget_use: {},
    acquisitions: [],
  },
  graph: null,
  outcome: null,
  comparison: null,
  behavioral: null,
  behavioral_manifest: null,
  manifest: null,
  cross_chain_links: [],
} as unknown as DemoPresetDetail;

describe("inspector distinguishes candidates from verified service", () => {
  it("shows an explicit non-ownership warning for a candidate node", () => {
    wrap(
      <Inspector
        detail={candidateDetail}
        onClose={() => {}}
        selection={{
          kind: "node",
          node: {
            index: 0,
            address: "TCandidate",
            role: "deposit_candidate",
            role_label: "Candidate lead (not verified)",
            endpoint_classes: ["deposit_candidate"],
            entity_name: null,
            boundary_reasons: [],
            attribution_statuses: ["candidate"],
            notes: [],
            branches: [1],
            reconverged_branches: [],
            incoming: [],
            outgoing: [],
            hop_layer: 1,
          },
        }}
      />,
    );
    expect(screen.getByText(/not ownership evidence/i)).toBeInTheDocument();
  });

  it("prompts the investigator when nothing is selected", () => {
    wrap(<Inspector detail={candidateDetail} onClose={() => {}} selection={null} />);
    expect(screen.getByText(/Select a wallet, a transfer, or a branch/i)).toBeInTheDocument();
  });
});

describe("decision support keeps rules authoritative", () => {
  it("shows the rule action as authoritative when the CLM disagrees", async () => {
    const routingPayload = {
      bundles: [
        {
          run_id: "r1",
          manifest: { artifact_class: "DECISION_SUPPORT_METADATA", caveat: "not blockchain evidence", metadata: {} },
          summary: {
            scenario_count: 1,
            rules_clm_top1_agreement: 0.3,
            clm_top3_coverage_of_curated_preferred_action: 0.8,
            unsafe_action_execution_rate: 0,
            median_clm_latency_ms: 76,
            cross_chain_comparison: null,
            failure_test_result: { router_requested: "shadow_clm", router_used: "rules", shadow_status: "failed", fallback_successful: true },
            adversarial_safety_result: { injected_candidates: ["FREEZE_FUNDS_AUTOMATICALLY"], forbidden_actions_rejected: true, unsafe_action_execution_rate: 0 },
          },
          scenarios: [
            {
              scenario_id: "01_SAME_CHAIN_CONTINUATION",
              scenario_source: "RECORDED_DERIVED",
              actual_selected_action: "CONTINUE_SAME_CHAIN",
              expected_curated_action: "CONTINUE_SAME_CHAIN",
              clm_choice: "STOP_COVERAGE_GAP",
              shadow_agreement: false,
              guard_results: {},
              rule_ranked_actions: [],
              clm_relative_action_probabilities: { STOP_COVERAGE_GAP: 0.5 },
            },
          ],
          integrity: { available: false, checked: 0, ok: 0, failed: 0, missing: 0, files: [] },
          files_present: {},
          model_info: {},
          environment: {},
          latencies: {},
        },
      ],
      comparisons: [],
      count: 1,
    };
    vi.stubGlobal("fetch", vi.fn(async () => envelope(routingPayload)));
    wrap(<DecisionSupportPage />);
    await waitFor(() => expect(screen.getByText(/Rules \/ CLM disagree/i)).toBeInTheDocument());
    expect(screen.getByText(/rules retained control/i)).toBeInTheDocument();
    expect(screen.getByText("CONTINUE_SAME_CHAIN")).toBeInTheDocument();
  });
});

describe("unsupported integrations are shown as not built", () => {
  it("renders NCRP and SAHYOG as not built without a secret value", async () => {
    const capabilities = {
      data_mode: "SYNTHETIC",
      capabilities: [
        { key: "tron_acquisition", label: "TRON", status: "partial", detail: "", implementation_status: "implemented", configuration_status: "configured", live_verified: false, historical_live_run_recorded: true },
        { key: "government_connectors", label: "Government connectors", status: "not_configured", detail: "not configured", implementation_status: "not_built", configuration_status: "not_configured", live_verified: false, historical_live_run_recorded: false },
      ],
    };
    const metaPayload = { supported_assets: [], supported_networks: [], capabilities: {}, capability_details: [], budgets: {} };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/meta")) return envelope(metaPayload);
        return envelope(capabilities);
      }),
    );
    const { container } = wrap(<IntegrationsPage />);
    await waitFor(() => expect(screen.getAllByText(/NCRP/).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/not built/i).length).toBeGreaterThan(0);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/api[_-]?key/i);
    expect(text).not.toMatch(/bearer /i);
  });
});

// A tiny interaction check so keyboard/pointer selection is exercised end to end.
describe("copy interaction", () => {
  it("copies the full value to the clipboard", async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<CopyableValue value="TFullAddressValue123" head={4} tail={3} label="address" />);
    await userEvent.click(screen.getByRole("button", { name: /copy address/i }));
    expect(writeText).toHaveBeenCalledWith("TFullAddressValue123");
  });
});
