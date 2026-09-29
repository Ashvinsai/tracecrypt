# Schema and API contract — v0.1.0

Binding for phase 02 onward. Changes here are decisions (`docs/DECISIONS.md`),
not refactors.

## Conventions
- Primary keys: UUIDv4, column `id`.
- Timestamps: `timestamptz`, UTC. `*_at` = wall clock of an action.
- Amounts: `NUMERIC(78,0)`, Python `int`, JSON **string** (D004).
- Every table carrying observation has `data_mode` in `{LIVE, RECORDED_PUBLIC, SYNTHETIC}` (D009).
- Enum columns are native Postgres enums, defined once in `app/models/enums.py`.

## Enumerations

```
network_family      : account | utxo
asset_kind          : native | token
execution_status    : success | failed | reverted | unknown
confirmation_state  : provisional | confirmed | removed | unknown
coverage_status     : complete_within_scope | partial | unknown | failed
attribution_status  : supported | inferred | candidate | conflicted | unresolved | unsupported
case_flow_linkage   : established | partial | not_established | ambiguous
boundary_reason     : service_boundary | hop_limit | event_limit | time_limit |
                      api_budget | unsupported_asset_change | bridge |
                      privacy_mechanism | opaque_contract | no_outgoing_activity |
                      ambiguous_ordering | cancelled | provider_failure
event_kind          : transfer | approval | internal_transfer | contract_call | unknown
entity_type         : exchange | custodial_service | payment_processor | mixer |
                      bridge | merchant | gambling | sanctioned_entity | unknown
address_role        : deposit | hot_wallet | cold_reserve | withdrawal |
                      settlement | unknown
assertion_type      : service_control | deposit_candidate | complaint_allegation |
                      public_abuse_report | sanctions_tag
review_state        : unreviewed | accepted | rejected | quarantined | conflicted
data_mode           : LIVE | RECORDED_PUBLIC | SYNTHETIC
trace_run_status    : queued | running | partial | completed | failed | cancelled
watch_poll_status   : running | succeeded | partial | provider_failure | truncated | refused
alert_state         : active | retracted
```

## Tables

### Identity and tenancy
- **organizations** `(id, name, slug UQ, created_at)`
- **users** `(id, email UQ, password_hash, display_name, is_active, created_at)`
- **memberships** `(id, user_id, organization_id, role, created_at)` — UQ `(user_id, organization_id)`

### Chain reference data
- **networks** `(id, key UQ, display_name, family, chain_id NULL, caip2 NULL, native_asset_symbol, is_supported, notes)`
  - `chain_id` is NULL for TRON; present for EVM. Never used to infer a network from an address (D002).
- **assets** `(id, network_id, kind, token_contract NULL, decimals, display_symbol, issuer_reference NULL, verified_at NULL, data_mode, is_supported)`
  - UQ `(network_id, kind, token_contract)` — `token_contract` NULL only for the native asset.
  - `display_symbol` is metadata. Nothing joins on it (D003).
- **addresses** `(id, network_id, canonical_address, original_input, address_format, first_observed_at, data_mode)`
  - UQ `(network_id, canonical_address)` (D002).

### Observation
- **blocks** `(id, network_id, height, block_hash, parent_hash NULL, block_time, is_canonical, observed_at, data_mode)` — UQ `(network_id, block_hash)`
- **transactions** `(id, network_id, tx_hash, execution_status, fee_base_units NULL, raw_reference NULL, data_mode)` — UQ `(network_id, tx_hash)`
- **transaction_inclusions** `(id, transaction_id, block_id, index_in_block NULL, is_canonical, observed_at)` — UQ `(transaction_id, block_id)`
  - History, not a single FK. A reorg adds a row and flips `is_canonical`; it never deletes (T7).
- **transfer_events** `(id, network_id, transaction_id, asset_id, event_reference, event_kind, from_address_id NULL, to_address_id NULL, amount_base_units, execution_status, confirmation_state, block_id NULL, block_time NULL, chain_sequence NULL, ordering_ambiguous, is_zero_value, parser_version, data_mode, created_at)`
  - UQ `(network_id, event_reference)` (D005).
  - `chain_sequence` is a sortable tuple encoded as text: `<height>:<index_in_block>:<event_index>`. NULL with `ordering_ambiguous = true` when receipt evidence is missing.
  - Approvals and failed executions are stored (they are evidence) but are excluded from confirmed transfer paths by query, never by deletion.
- **acquisitions** `(id, source, provider, endpoint, request_params_hash, requested_at, observed_at NULL, response_hash NULL, status, coverage_status, error_class NULL, analysis_cutoff, parser_version, data_mode, capture_time NULL)`
  - `status='failed'` with zero rows is a failure, never an empty history (T3).
  - `capture_time` is required for `RECORDED_PUBLIC`.
- **acquisition_events** `(acquisition_id, transfer_event_id)` — provenance join, PK on the pair.

### Attribution
- **entities** `(id, name, entity_type, jurisdiction NULL, parent_entity_id NULL, data_mode, created_at)`
- **attribution_evidence** `(id, source_type, source_reference, retrieval_date, document_hash NULL, methodology, reviewer NULL, reuse_terms NULL, notes NULL, created_at)`
- **label_assertions** `(id, address_id, entity_id NULL, assertion_type, address_role, evidence_id, review_state, valid_from NULL, valid_to NULL, last_verified_at NULL, label_set_version, attribution_status, data_mode, created_by NULL, created_at)`
  - Conflicting assertions coexist. Nothing is deleted to resolve a conflict.
  - Only `assertion_type='service_control'` with `review_state='accepted'` and a
    validity interval covering the observation time may terminate a trace branch.

### Case work
- **cases** `(id, organization_id, case_reference, title, status, data_mode, created_by, created_at)` — UQ `(organization_id, case_reference)`
- **case_seeds** `(id, case_id, mode, network_id, address_id, transaction_id NULL, transfer_event_id NULL, asset_id NULL, amount_base_units NULL, incident_time NULL, window_start NULL, window_end NULL, created_at)`
  - `mode='incident'` requires an asset. `mode='address_discovery'` forbids amount.
- **trace_runs** `(id, case_id, case_seed_id, status, engine_version, label_set_version, analysis_cutoff, budgets JSONB, input_hash, coverage_status, data_mode, started_at NULL, finished_at NULL, cancelled_reason NULL)`
- **trace_states** `(id, trace_run_id, parent_state_id NULL, network_id, address_id, asset_id, arrival_event_id NULL, hop_depth, branch_path, status, boundary_reason NULL, created_at)`
- **findings** `(id, trace_run_id, trace_state_id NULL, finding_type, attribution_status, coverage_status, case_flow_linkage, boundary_reason NULL, entity_id NULL, address_id NULL, observed_amount_base_units NULL, case_amount_basis, evidence JSONB, created_at)`
  - `case_amount_basis` defaults to `allocation_unknown` (PRD §5).
- **watches** `(id, case_id, network_id, address_id, asset_id, is_active, cursor NULL, data_mode, analysis_start NULL, overlap_seconds, checkpoint_time NULL, checkpoint_updated_at NULL, created_by NULL, created_at)` — D029.
  - `checkpoint_time` is a block-time frontier advanced only by a complete, error-free poll. `cursor` is unused (a provider fingerprint is not a durable resume point).
- **watch_poll_runs** `(id, watch_id, status, coverage_status, data_mode, provider, started_at, completed_at NULL, window_start, window_end, checkpoint_before NULL, checkpoint_after NULL, pages_fetched, provider_requests NULL, events_observed, new_alerts, duplicate_events, error_class NULL, error_message NULL, summary JSONB)` — one row per poll, written whether it succeeded or not (T3).
- **alerts** `(id, watch_id, rule_key, rule_version, dedupe_key, event_reference, data_mode, state, execution_status, confirmation_state, block_time NULL, first_observed_at, first_poll_run_id NULL, evidence JSONB, acknowledged_at NULL, created_at)` — UQ `(watch_id, dedupe_key)`, `dedupe_key = <rule_key>:<event_reference>` (D005, D029).
  - `state` is `active | retracted`; a retracted alert is kept, never deleted (T7).
- **exports** `(id, case_id, bundle_version, manifest_hash, created_by, created_at)` — phase 10.
- **audit_events** `(id, organization_id NULL, actor_user_id NULL, action, object_type, object_id NULL, request_id, occurred_at, metadata JSONB)`

## API contract

Every response is wrapped:

```json
{
  "data": { },
  "meta": {
    "data_mode": "SYNTHETIC",
    "request_id": "01J…",
    "engine_version": "0.1.0",
    "label_set_version": "0",
    "analysis_cutoff": "2026-09-19T00:00:00Z"
  }
}
```

Errors: `{"error": {"code": "...", "message": "...", "details": {}}}` with codes
`unauthenticated`, `forbidden`, `not_found`, `validation_error`, `conflict`,
`budget_exceeded`, `unsupported`.

| Method | Path | Phase | Notes |
|---|---|---|---|
| GET | `/healthz` | 01 | liveness, unauthenticated |
| GET | `/readyz` | 01 | DB + Redis reachability |
| GET | `/api/v1/meta` | 01 | data mode, versions, capabilities |
| POST | `/api/v1/auth/login` | 01 | sets signed session cookie |
| POST | `/api/v1/auth/logout` | 01 | |
| GET | `/api/v1/auth/me` | 01 | |
| GET | `/api/v1/networks` | 02 | supported networks + assets |
| POST | `/api/v1/cases` | 02 | org-scoped |
| GET | `/api/v1/cases` | 02 | org-scoped list |
| GET | `/api/v1/cases/{id}` | 02 | 404 (not 403) across orgs |
| POST | `/api/v1/cases/{id}/seeds` | 02 | validates address, asset, mode |
| GET | `/api/v1/addresses/validate` | 02 | network-scoped canonicalization |
| POST | `/api/v1/traces` | 07 | returns job id |
| GET | `/api/v1/traces/{id}` | 07 | status + partial findings |
| POST | `/api/v1/exports` | 10 | |
| POST | `/api/v1/cases/{id}/watches` | 4 (D029) | exact verified token contract; mode must match the case |
| GET | `/api/v1/cases/{id}/watches` | 4 (D029) | org-scoped via the case; 404 across orgs |
| GET | `/api/v1/cases/{id}/watches/{watch_id}` | 4 (D029) | |
| GET | `/api/v1/cases/{id}/watches/{watch_id}/alerts` | 4 (D029) | amounts as strings |
| GET | `/api/v1/cases/{id}/watches/{watch_id}/polls` | 4 (D029) | poll-run audit; polling itself is CLI-only |

Cross-organization reads return `404`, not `403`, so that case existence is not
disclosed. The authorization dependency resolves the case from
`(session user → membership → organization)` on every request.
