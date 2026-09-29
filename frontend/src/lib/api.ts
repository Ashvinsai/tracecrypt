/**
 * API client for the investigator workspace.
 *
 * Amounts arrive as strings and stay strings. JavaScript's Number loses
 * precision above 2^53, far below a uint256 token amount, so no amount is ever
 * parsed into a number here (D004).
 *
 * Every capability, status and evidence value is fetched; nothing about what
 * the system supports is hardcoded in the UI.
 */

export type DataMode = "LIVE" | "RECORDED_PUBLIC" | "SYNTHETIC";

export interface Envelope<T> {
  data: T;
  meta: {
    data_mode: DataMode;
    request_id: string;
    engine_version: string;
    label_set_version: string;
    analysis_cutoff: string;
  };
}

export interface Network {
  key: string;
  display_name: string;
  family: string;
  chain_id: number | null;
  is_supported: boolean;
}

export interface Asset {
  network_id: string;
  kind: string;
  token_contract: string | null;
  decimals: number;
  display_symbol: string;
  issuer_reference: string | null;
  verified_at: string | null;
  is_supported: boolean;
}

export interface Capability {
  key: string;
  label: string;
  status: string;
  detail: string;
  implementation_status: string;
  configuration_status: string;
  live_verified: boolean;
  historical_live_run_recorded: boolean;
  trained_real_model?: boolean;
}

export interface MetaPayload {
  supported_networks: Network[];
  supported_assets: Asset[];
  capabilities: Record<string, boolean | string>;
  capability_details: Capability[];
  budgets: Record<string, number | string>;
}

export interface IntegrityFile {
  file: string;
  expected: string;
  actual: string | null;
  status: "ok" | "mismatch" | "missing";
}

export interface Integrity {
  checked: number;
  ok: number;
  failed: number;
  missing: number;
  files: IntegrityFile[];
  available: boolean;
  caveat?: string;
}

export interface PresetSummary {
  id: string;
  title: string;
  scenario: string;
  data_mode: DataMode;
  address: string;
  network: string | null;
  observed_transfers: number;
  branch_endings: number;
  unresolved: number;
  candidate: number;
  known_service: number;
  outcome_category: string | null;
  outcome_service: string | null;
  has_trace: boolean;
  error: string | null;
  integrity: Integrity;
}

export interface ObservedTransfer {
  event_reference: string;
  tx_hash: string | null;
  from_address: string | null;
  to_address: string | null;
  amount_base_units: string;
  amount_display: string;
  asset: { token_contract: string | null; decimals: number; display_symbol: string };
  block_time: string | null;
  chain_sequence: string | null;
  ordering_ambiguous: boolean;
  execution_status: string;
  confirmation_state: string;
  hop_depth: number;
  acquisition_id: string | null;
}

export interface LabelEvidence {
  entity_name: string;
  entity_type: string;
  assertion_type: string;
  address_role: string;
  review_state: string;
  source_reference: string;
  retrieval_date: string | null;
  methodology: string;
  reviewer: string | null;
  valid_from: string | null;
  valid_to: string | null;
  last_verified_at: string | null;
  label_set_version: string;
  source_hash: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_reference: string | null;
}

export interface BranchEnding {
  address: string;
  endpoint_class: "known_service" | "deposit_candidate" | "unresolved" | "boundary";
  attribution_status: string;
  boundary_reason: string | null;
  hop_depth: number;
  branch_path: string[];
  arrival_event_reference: string | null;
  observed_amount_base_units: string | null;
  observed_amount_display: string | null;
  case_amount_basis: string;
  label: LabelEvidence | null;
  note: string | null;
}

export interface Limitation {
  code: string;
  message: string;
  address: string | null;
  event_reference: string | null;
}

export interface TraceResult {
  seed: {
    address: string;
    event_reference: string | null;
    network_key: string;
    asset: { token_contract: string | null; display_symbol: string; decimals: number };
  };
  scope: Record<string, unknown>;
  seed_transfer: ObservedTransfer | null;
  observed_transfers: ObservedTransfer[];
  branch_endings: BranchEnding[];
  cross_chain_links: Record<string, unknown>[];
  limitations: Limitation[];
  budget_use: Record<string, number | string>;
  acquisitions: Record<string, unknown>[];
  disclaimer?: string;
}

export interface FlowNode {
  index: number;
  address: string;
  role: string;
  role_label: string;
  endpoint_classes: string[];
  entity_name: string | null;
  boundary_reasons: string[];
  attribution_statuses: string[];
  notes: string[];
  branches: number[];
  reconverged_branches: number[];
  incoming: number[];
  outgoing: number[];
  hop_layer: number;
}

export interface FlowEdge {
  index: number;
  event_reference: string;
  tx_hash: string | null;
  from: string;
  to: string;
  amount_display: string | null;
  amount_base_units: string | null;
  symbol: string;
  block_time: string | null;
  ordering_ambiguous: boolean;
  execution_status: string | null;
  confirmation_state: string | null;
  hop_depth: number;
  is_seed_transfer: boolean;
  derived_from: string | null;
}

export interface FlowBranch {
  number: number;
  address: string | null;
  endpoint_class: string;
  attribution_status: string | null;
  boundary_reason: string | null;
  hop_depth: number;
  event_references: string[];
  edges: number[];
  undrawn_references: string[];
}

export interface FundFlowGraph {
  nodes: FlowNode[];
  edges: FlowEdge[];
  branches: FlowBranch[];
  warnings: string[];
  acyclic: boolean;
  stats: {
    wallets: number;
    transfers: number;
    branches: number;
    supported_boundaries: number;
    candidate_leads: number;
    unresolved: number;
    reconverged: number;
    max_hop_layer: number;
    ordering_ambiguous: number;
  };
  drawn: string;
}

export interface DemoPresetDetail {
  id: string;
  title: string;
  scenario: string;
  data_mode: DataMode;
  capture_data_mode: string | null;
  address: string;
  description: string;
  scope_note: string;
  error: string | null;
  warnings: string[];
  has_outcome: boolean;
  has_comparison: boolean;
  has_report: boolean;
  trace: TraceResult | null;
  graph: FundFlowGraph | null;
  outcome: Record<string, unknown> | null;
  comparison: Record<string, unknown> | null;
  behavioral: Record<string, unknown> | null;
  behavioral_manifest: Record<string, unknown> | null;
  manifest: Record<string, unknown> | null;
  cross_chain_links: Record<string, unknown>[];
}

export interface CrossChainLink {
  protocol_family: string;
  protocol_generation: number;
  linkage_status: "COMPLETE" | "INCOMPLETE" | "FAILED" | "AMBIGUOUS" | string;
  source_network: string;
  source_chain_id: number;
  source_domain: number;
  source_tx_hash: string;
  source_block_number: number;
  source_block_time: string | null;
  source_finality: string | null;
  source_burn_event_reference: string;
  source_message_event_reference: string;
  message_nonce: string;
  api_event_nonce: string | number | null;
  message_hash: string;
  attestation_status: string;
  attestation_source: string;
  attestation_signature_verified: boolean;
  attestation_length_bytes: number | null;
  signature_blob_count: number | null;
  burn_token: string;
  mint_token: string;
  depositor: string;
  mint_recipient: string;
  source_burn_amount_base_units: string;
  max_fee_base_units: string;
  fee_executed_base_units: string;
  observed_mint_and_withdraw_amount_base_units: string | null;
  observed_recipient_usdc_amount_base_units: string | null;
  amount_reconciliation: string;
  destination_network: string;
  destination_chain_id: number;
  destination_domain: number;
  destination_tx_hash: string | null;
  destination_receive_event_reference: string | null;
  destination_mint_event_reference: string | null;
  destination_block_number: number | null;
  destination_block_time: string | null;
  destination_receipt_finality: string | null;
  destination_execution_status: string | null;
  evidence_references: string[];
  limitations: string[];
}

export interface CctpBundle {
  run_id: string;
  protocol: string;
  route: string;
  link: CrossChainLink;
  transfers: Record<string, unknown>[];
  receipts: Record<string, unknown> | null;
  discovery: Record<string, unknown> | null;
  manifest: Record<string, unknown> | null;
  capture_data_mode: string | null;
  presented_data_mode: DataMode;
  integrity: Integrity;
  files_present: Record<string, boolean>;
}

export interface RoutingBundle {
  run_id: string;
  manifest: Record<string, unknown>;
  summary: Record<string, unknown>;
  scenarios: RoutingScenario[];
  model_info: Record<string, unknown> | null;
  environment: Record<string, unknown> | null;
  latencies: Record<string, unknown> | null;
  integrity: Integrity;
  files_present: Record<string, boolean>;
}

export interface RoutingScenario {
  scenario_id: string;
  scenario_source: string;
  actual_selected_action: string | null;
  expected_curated_action: string | null;
  clm_choice: string | null;
  shadow_agreement: boolean;
  guard_results: Record<string, { action_key: string; decision: string; reason: string }>;
  rule_ranked_actions: { action: string; score: number; reason?: string | null }[];
  clm_relative_action_probabilities: Record<string, number> | null;
  serialized_model_state?: string;
}

export interface CandidateReportBundle {
  run_id: string;
  report: {
    report_type: string;
    network: string;
    anchor: Record<string, string>;
    candidates: Record<string, unknown>[];
    coverage: Record<string, number | boolean>;
    limitations: string[];
    disclaimer: string;
    observation_window: Record<string, string>;
  };
  manifest: Record<string, unknown> | null;
  integrity: Integrity;
}

export interface EvidenceBundle {
  run_id: string;
  manifest: Record<string, unknown>;
  integrity: Integrity;
  report_download: string | null;
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error?.message ?? `request failed: ${response.status}`;
    throw new Error(message);
  }
  return (await response.json()) as T;
}

async function getData<T>(path: string): Promise<T> {
  const envelope = await get<Envelope<T>>(path);
  return envelope.data;
}

export const api = {
  health: () => get<{ status: string }>("/healthz"),
  meta: () => getData<MetaPayload>("/api/v1/meta"),
  metaEnvelope: () => get<Envelope<MetaPayload>>("/api/v1/meta"),
  demo: {
    presets: () => getData<{ presets: PresetSummary[]; count: number }>("/api/v1/demo/presets"),
    preset: (id: string) =>
      getData<DemoPresetDetail>(`/api/v1/demo/presets/${encodeURIComponent(id)}`),
    cctp: () => getData<{ bundles: CctpBundle[]; count: number }>("/api/v1/demo/cctp"),
    routing: () =>
      getData<{ bundles: RoutingBundle[]; comparisons: { name: string; comparison: Record<string, unknown> }[]; count: number }>(
        "/api/v1/demo/routing",
      ),
    candidates: () =>
      getData<{ reports: CandidateReportBundle[]; count: number }>("/api/v1/demo/candidates"),
    evidence: () =>
      getData<{ bundles: EvidenceBundle[]; count: number }>("/api/v1/demo/evidence"),
    capabilities: () =>
      getData<{ capabilities: Capability[]; data_mode: DataMode }>("/api/v1/demo/capabilities"),
  },
};

export function apiBase(): string {
  return BASE || window.location.origin;
}
