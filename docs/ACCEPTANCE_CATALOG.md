# Acceptance catalog

A specification, not evidence. A row is `pass` only when the named test exists
and has been observed to pass. Every `pass` below was verified by
`uv run pytest -q` in `api/` on 2026-09-20: **209 passed, 1 deselected (C06, live-only), 0 failed**.

Rows without a test say so. Nothing here is marked from intent.

## Day-one correctness tests (`docs/FIVE_STAGE_PLAN.md`)

The plan's twelve items, mapped to real tests.

| # | Day-one requirement | Test | State |
|---|---|---|---|
| 1 | An outgoing event before the investigated receipt cannot continue its path | `test_tracer.py::test_earlier_outgoing_transfer_cannot_continue_the_path` | pass |
| 2 | A later receipt at an already-encountered address is not discarded by a global visited set | `test_tracer.py::test_later_receipt_at_a_seen_address_is_not_discarded` | pass |
| 3 | Separate transfer events in one transaction retain separate identities | `test_event_identity.py::test_multiple_events_one_transaction` | pass |
| 4 | Network and asset contract are part of identity; a ticker is insufficient | `test_identity.py::test_same_string_two_networks`, `::test_symbol_is_not_asset_identity` | pass |
| 5 | Integer base units survive serialization exactly; large amounts serialize as strings | `test_amounts.py::test_uint256_roundtrip`, `::test_amount_serializes_as_string` | pass |
| 6 | Approvals and failed transfers do not become successful fund-flow edges | `test_execution_status.py::test_failed_excluded_from_confirmed`, `::test_approval_excluded_from_confirmed`, `test_tracer.py::test_approvals_failures_removals_and_zero_value_do_not_extend_a_path` | pass |
| 7 | Pagination is consumed and duplicates removed without merging distinct events | `test_acquisition.py::test_pagination_does_not_duplicate_events`, `test_tracer.py::test_pagination_is_consumed_without_duplicating_events`, `test_tron_adapter.py::test_pagination_keeps_parameters_stable_and_carries_the_fingerprint` | pass |
| 8 | Mixed balances do not turn a later outgoing amount into victim value; reconverging paths do not duplicate value | `test_tracer.py::test_mixed_balance_does_not_become_victim_value`, `::test_reconverging_branches_are_both_preserved_and_not_summed`, `::test_shared_suffix_after_reconvergence_is_not_walked_twice` | pass |
| 9 | Unhandled bridge, mixer, and custody boundaries gain no invented continuation edges | `test_tracer.py::test_unknown_onward_activity_creates_no_invented_edge` | pass |
| 10 | A shared energy-rental sponsor alone does not merge unrelated wallets or identify an exchange | `test_resource_evidence.py::test_shared_sponsor_does_not_merge_unrelated_wallets`, `::test_sponsor_label_does_not_transfer_to_the_receiver`, `::test_shared_sponsor_alone_cannot_promote_a_candidate`, `::test_high_fanout_sponsor_is_flagged_as_a_shared_service` | pass |
| 11 | Missing history or provider failure returns partial/unknown, not a false successful empty result | `test_acquisition.py::test_failure_is_not_empty_history`, `test_tracer.py::test_provider_failure_is_a_boundary_not_an_empty_result`, `test_tron_adapter.py::test_provider_errors_are_classified_not_swallowed` | pass |
| 12 | Current delegation state does not establish historical delegation timing | `test_resource_evidence.py::test_current_state_does_not_establish_when_a_delegation_began`, `::test_lock_expiry_is_not_a_delegation_start`, `::test_empty_current_state_is_not_an_absence_of_history` | pass |

## A — Data correctness

| ID | Acceptance criterion | Test | State |
|---|---|---|---|
| A01 | Two transfer events in one transaction both persist and are retrievable | `test_event_identity.py::test_multiple_events_one_transaction` | pass |
| A02 | The same `(network, event_reference)` cannot be stored twice | `test_event_identity.py::test_event_reference_unique` | pass |
| A03 | No constraint exists that would let a tx hash collapse distinct events | `test_event_identity.py::test_tx_hash_is_not_event_identity` | pass |
| A04 | The same address string on two networks is two distinct rows | `test_identity.py::test_same_string_two_networks` | pass |
| A05 | `(network, canonical_address)` is unique | `test_identity.py::test_address_identity_unique` | pass |
| A06 | Original supplied input survives canonicalization | `test_identity.py::test_original_input_preserved` | pass |
| A07 | A `uint256`-scale amount round-trips exactly through the database | `test_amounts.py::test_uint256_roundtrip` | pass |
| A08 | Amounts serialize to JSON as strings, never numbers | `test_amounts.py::test_amount_serializes_as_string` | pass |
| A09 | Exact decimal display at 6 and 18 decimals, no float error | `test_amounts.py::test_display_conversion_exact` (7 cases) | pass |
| A10 | Two assets sharing a symbol are distinct by contract | `test_identity.py::test_symbol_is_not_asset_identity` | pass |
| A11 | Block inclusion history survives a reorg; the orphan is not deleted | `test_reorg.py::test_inclusion_history_preserved` | pass |
| A12 | A failed transaction's events persist but are excluded from confirmed transfers | `test_execution_status.py::test_failed_excluded_from_confirmed` | pass |
| A13 | Approval events persist but are excluded from confirmed transfers | `test_execution_status.py::test_approval_excluded_from_confirmed` | pass |
| A14 | A provider failure yields `status=failed`, never an empty successful history | `test_acquisition.py::test_failure_is_not_empty_history` | pass |
| A15 | An event with no supplied index is stored `ordering_ambiguous=true`, never guessed | `test_event_identity.py::test_no_invented_event_index` | pass |
| A16 | The fixture loader refuses to write under `data_mode=LIVE` | `test_data_mode.py::test_fixture_loader_refuses_live` | pass |
| A17 | The fixture adapter refuses to serve a process declaring `LIVE` | `test_data_mode.py::test_fixture_adapter_refuses_live_mode` | pass |
| A18 | Zero-value events are stored and flagged, and carry no case value | `test_execution_status.py::test_zero_value_flagged` | pass |
| A19 | A reorg-removed event is not reported as a settled transfer | `test_execution_status.py::test_removed_event_is_not_settled` | pass |
| A20 | A float amount is rejected at the column boundary, not truncated | `test_amounts.py::test_float_amount_rejected_at_the_database_boundary` | pass |
| A21 | Stored timestamps return timezone-aware UTC on every dialect | `test_time.py::test_block_time_returns_aware_utc`, `::test_non_utc_input_is_normalized` | pass |
| A22 | A naive datetime is rejected rather than stored ambiguously | `test_time.py::test_naive_datetime_is_rejected` | pass |
| A23 | Chronological comparison survives a storage round-trip | `test_time.py::test_chronological_comparison_survives_storage` | pass |

## B — Skeleton, auth, authorization

| ID | Acceptance criterion | Test | State |
|---|---|---|---|
| B01 | `/healthz` responds without authentication | `test_health.py::test_healthz_open` | pass |
| B02 | An unauthenticated request to a case route is rejected `401` | `test_authz.py::test_unauthenticated_rejected` | pass |
| B03 | A foreign organization's case returns `404`, not `403` | `test_authz.py::test_cross_org_case_is_404` | pass |
| B04 | A user cannot create a seed on a foreign case | `test_authz.py::test_cross_org_seed_rejected` | pass |
| B05 | Session cookie is `HttpOnly`, `SameSite=Lax`, and signed | `test_auth.py::test_session_cookie_flags` | pass |
| B06 | A wrong password does not reveal whether the account exists | `test_auth.py::test_login_failure_is_uniform` | pass |
| B07 | Every response carries `data_mode` and a request ID | `test_envelope.py::test_meta_envelope` | pass |
| B08 | A placeholder secret refuses to boot outside dev | `test_settings.py::test_placeholder_secret_rejected_outside_dev` | pass |
| B09 | Passwords are Argon2id hashes | `test_auth.py::test_password_hash_is_argon2id` | pass |
| B10 | Unimplemented capabilities are not advertised as available | `test_envelope.py::test_capabilities_do_not_overclaim` | pass |
| B11 | A provider key does not appear in a settings repr | `test_settings.py::test_api_key_is_not_repr_printed` | pass |
| B12 | Case listing is organization-scoped | `test_authz.py::test_case_list_is_org_scoped` | pass |

## C — Adapter contract

| ID | Acceptance criterion | Test | State |
|---|---|---|---|
| C01 | Walking every page yields each event exactly once | `test_acquisition.py::test_pagination_does_not_duplicate_events` | pass (fixture) |
| C03 | A contract that is not the configured asset is not traced as that asset | `test_data_mode.py::test_spoofed_token_contract_is_distinct_asset` | pass |
| C04 | A provider error raises a classified error, not an empty list | `test_acquisition.py::test_failure_is_not_empty_history` | pass |
| C05 | The analysis cutoff bounds the retrieved range | `test_acquisition.py::test_analysis_cutoff_bounds_the_range` | pass |
| C02 | Cursor parameters stay consistent across live pages | `test_tron_adapter.py::test_pagination_keeps_parameters_stable_and_carries_the_fingerprint` | pass |
| C07 | The history endpoint supplies no event index, so enrichment provides it | `test_tron_adapter.py::test_multiple_transfers_in_one_transaction_get_distinct_indices` | pass |
| C08 | Without enrichment the position is unknown, never index 0 | `test_tron_adapter.py::test_missing_enrichment_yields_ambiguity_not_a_guessed_index` | pass |
| C09 | Execution status is `unknown` from history alone, never assumed successful | `test_tron_adapter.py::test_execution_status_is_unknown_from_history_alone` | pass |
| C10 | The API key travels as a header, never in a URL | `test_tron_adapter.py::test_api_key_is_sent_as_a_header_not_a_query_parameter` | pass |
| C06 | Live contract tests are opt-in and skip without a key | — | **not written — no API key available** |

## D — Tracing engine

| ID | Acceptance criterion | Test | State |
|---|---|---|---|
| D01 | A receipt later than an outgoing transfer cannot explain that transfer | `test_tracer.py::test_earlier_outgoing_transfer_cannot_continue_the_path` | pass |
| D02 | Fan-out produces separate retained branches | `test_tracer.py::test_reconverging_branches_are_both_preserved_and_not_summed` | pass |
| D03 | A reconverging branch does not double-count and drops neither path | `test_tracer.py::test_reconverging_branches_are_both_preserved_and_not_summed`, `::test_shared_suffix_after_reconvergence_is_not_walked_twice` | pass |
| D04 | A cycle terminates without repeating an event | `test_tracer.py::test_a_cycle_terminates_without_repeating_an_event` | pass |
| D05 | The trace stops at the first accepted `service_control` boundary per branch | `test_tracer.py::test_trace_stops_at_the_first_accepted_service_boundary` | pass |
| D06 | A `deposit_candidate` does not terminate a branch as verified | `test_tracer.py::test_a_candidate_does_not_terminate_a_branch` | pass |
| D07 | Budget exhaustion emits a boundary finding, not a silent stop | `test_tracer.py::test_hop_limit_emits_a_boundary_not_a_silent_stop` | pass |
| D08 | Same-block ordering without receipt evidence is flagged ambiguous | `test_tracer.py::test_same_block_without_ordering_is_recorded_as_unresolved` | pass |
| D09 | An unreviewed label does not terminate a branch | `test_tracer.py::test_an_unreviewed_label_does_not_terminate_a_branch` | pass |
| D10 | An expired label does not terminate a branch | `test_tracer.py::test_an_expired_label_does_not_terminate_a_branch` | pass |
| D11 | A merged branch is not reported as a dead end | `test_tracer.py::test_a_merged_branch_is_not_reported_as_a_dead_end` | pass |
| D12 | The live adapter refuses to run under synthetic settings | `test_tracer.py::test_live_adapter_refuses_to_run_under_synthetic_settings` | pass |

## G — Stage 1 vertical slice

| ID | Acceptance criterion | Test | State |
|---|---|---|---|
| G01 | A seed event traces to the sourced service anchor, with its provenance | `test_trace_endpoint.py::test_trace_reaches_the_sourced_service_anchor` | pass |
| G02 | Amounts cross the API as exact strings and display exactly | `test_trace_endpoint.py::test_amounts_are_strings_and_exact` | pass |
| G03 | A candidate is reported without terminating the trace | `test_trace_endpoint.py::test_candidate_is_reported_without_terminating_the_trace` | pass |
| G04 | Every branch ending defaults to `allocation_unknown` | `test_trace_endpoint.py::test_every_ending_defaults_to_allocation_unknown` | pass |
| G05 | A spoofed contract traces a different asset | `test_trace_endpoint.py::test_spoofed_contract_traces_a_different_asset` | pass |
| G06 | Address-only mode asserts no case linkage | `test_trace_endpoint.py::test_address_only_mode_asserts_no_case_linkage` | pass |
| G07 | An unknown seed event is rejected, not silently ignored | `test_trace_endpoint.py::test_unknown_seed_event_is_rejected_not_silently_ignored` | pass |
| G08 | Tracing requires authentication | `test_trace_endpoint.py::test_trace_requires_authentication` | pass |
| G09 | The evidence report states its data mode and claims no probability | `test_trace_endpoint.py::test_evidence_report_renders_and_states_its_mode` | pass |
| G10 | Hostile text from a data file renders inert in the report (F02) | `test_trace_endpoint.py::test_report_escapes_hostile_label_text` | pass |

## H — Stage 2 label acquisition and resource evidence

| ID | Acceptance criterion | Test | State |
|---|---|---|---|
| H01 | A reserve disclosure cannot establish a deposit address | `test_anchor_import.py::test_a_reserve_file_cannot_establish_a_deposit_address` | pass |
| H02 | An aggregator copy is a lead and never a verified anchor | `test_anchor_import.py::test_an_aggregator_row_is_a_lead_and_never_verified` | pass |
| H03 | Two aggregators repeating one source count as one source | `test_anchor_import.py::test_two_aggregators_repeating_one_source_are_one_source` | pass |
| H04 | A signed verification supports the role it states | `test_anchor_import.py::test_a_signed_verification_supports_the_role_it_states` | pass |
| H05 | An authorized observation is evaluation material, not an anchor | `test_anchor_import.py::test_an_authorized_observation_is_evaluation_material_not_an_anchor` | pass |
| H06 | A row on another network, or on none, is rejected rather than assumed | `test_anchor_import.py::test_a_row_on_another_network_is_rejected_not_assumed` | pass |
| H07 | Missing provenance refuses the whole document before writing | `test_anchor_import.py::test_provenance_is_required_before_anything_is_imported` (3 cases), `::test_aggregator_rows_require_reuse_terms` | pass |
| H08 | The three label sets are written to three separate files | `test_anchor_import.py::test_the_three_sets_are_written_to_three_separate_files` | pass |
| H09 | An imported row is unreviewed and cannot terminate a trace | `test_anchor_import.py::test_the_verified_file_is_loadable_by_the_tracer_registry` | pass |
| H10 | The source file and its hash are preserved beside the rows | `test_anchor_import.py::test_a_reserve_row_becomes_a_verified_anchor_with_its_hash` | pass |
| H11 | Delegation parsers invent no field the endpoint does not return | `test_resource_evidence.py::test_account_index_yields_addresses_and_nothing_else`, `::test_delegated_resource_v2_splits_the_two_resources`, `::test_zero_balance_rows_do_not_become_delegations` | pass |
| H12 | A historical delegation claim needs a transaction and a block time | `test_resource_evidence.py::test_historical_operation_requires_a_transaction_and_a_block_time`, `::test_historical_operation_establishes_a_dated_claim` | pass |
| H13 | A behavioural candidate lands in the candidate set, whatever document carried it | `test_anchor_import.py::test_a_behavioural_candidate_lands_in_the_candidate_set` | pass |
| H14 | The review queue hands a reviewer the source behind each row | `test_candidate_review.py::test_the_queue_hands_a_reviewer_the_source_behind_each_row`, `::test_queue_filters_by_state_so_reviewed_rows_leave_it` | pass |
| H15 | A decision needs a named reviewer and a rationale | `test_candidate_review.py::test_accepting_needs_a_reviewer_and_a_rationale` | pass |
| H16 | Accepting without naming the row's own source is refused | `test_candidate_review.py::test_accepting_without_opening_the_source_is_refused` | pass |
| H17 | A source file that changed since import cannot be accepted | `test_candidate_review.py::test_a_changed_source_file_blocks_acceptance` | pass |
| H18 | Acceptance is what lets an anchor terminate a trace | `test_candidate_review.py::test_accepting_an_anchor_is_what_lets_it_terminate_a_trace` | pass |
| H19 | A behavioural candidate cannot become an anchor by review | `test_candidate_review.py::test_a_behavioural_candidate_cannot_become_an_anchor_by_review`, `::test_accepting_a_candidate_does_not_let_it_terminate_a_trace` | pass |
| H20 | Promoting a lead needs evidence independent of the pattern | `test_candidate_review.py::test_promoting_a_lead_needs_evidence_independent_of_the_pattern` | pass |
| H21 | A competing claim must be acknowledged and is preserved, not deleted | `test_candidate_review.py::test_a_competing_claim_must_be_acknowledged_and_is_never_deleted` | pass |
| H22 | A decision changes one row and no other | `test_candidate_review.py::test_a_decision_changes_one_row_and_no_other` | pass |
| H23 | A rejected row keeps its place and its source | `test_candidate_review.py::test_rejecting_keeps_the_row_and_its_source` | pass |
| H24 | Every decision appends to the review log with the state it moved from | `test_candidate_review.py::test_every_decision_is_appended_to_the_log` | pass |
| H25 | Each action maps to exactly one review state | `test_candidate_review.py::test_each_action_maps_to_one_review_state` (4 cases) | pass |
| H26 | A decision on an unknown address is refused, not invented | `test_candidate_review.py::test_an_unknown_address_is_refused_not_invented` | pass |
| H27 | A dry run changes nothing on disk | `test_candidate_review.py::test_nothing_is_written_without_write` | pass |

Not written: candidate collection from live history (`collect_candidates`),
feature extraction, and the method comparison report. Those need chain access.

## I — Reviewed registry wiring, receipts, and live validation

| ID | Acceptance criterion | Test | State |
|---|---|---|---|
| I01 | An unreviewed claim attributes no service through `POST /trace` | `test_reviewed_registry_wiring.py::test_an_unreviewed_claim_does_not_become_a_supported_service` | pass |
| I02 | Accepting a claim changes what the same request returns, with provenance | `::test_accepting_the_claim_changes_what_the_same_request_returns` | pass |
| I03 | A withdrawn claim is not used by a new trace | `::test_a_claim_withdrawn_by_review_is_not_used_by_a_new_trace` | pass |
| I04 | An expired claim is not used although accepted | `::test_an_expired_claim_is_not_used_although_it_is_accepted` | pass |
| I05 | A saved report keeps the evidence it used after the CSV changes | `::test_a_saved_report_keeps_the_evidence_it_used` | pass |
| I06 | A candidate, a conflicted claim and a wrong-network claim cannot terminate | `::test_a_deposit_candidate_cannot_become_a_supported_terminal`, `::test_a_conflicted_claim_does_not_terminate_a_branch`, `::test_a_claim_on_another_network_is_not_used` | pass |
| I07 | The API and the CLI read the same registry | `::test_the_api_and_the_cli_read_the_same_registry` | pass |
| I08 | Live mode refuses an empty reviewed set and the synthetic set | `::test_live_mode_refuses_an_empty_reviewed_set_rather_than_falling_back`, `::test_live_mode_cannot_be_configured_to_read_the_synthetic_set` | pass |
| I09 | `independent_review.csv` is never read by the tracer | `::test_the_review_sets_are_never_read_from_independent_review` | pass |
| I10 | A solidified receipt gives execution and finality; a head receipt gives execution only | `test_execution_verification.py::test_a_solidified_receipt_gives_execution_and_finality`, `::test_an_unsolidified_transaction_is_executed_but_not_final` | pass |
| I11 | An unrecognised or missing receipt result is never read as success | `::test_an_unrecognised_receipt_result_is_never_read_as_success`, `::test_a_receipt_without_a_result_field_stays_unknown`, `::test_no_receipt_anywhere_is_unknown_not_absent` | pass |
| I12 | HTTP 200 carrying only `Error` is a provider error | `::test_an_error_body_with_http_200_is_an_error` | pass |
| I13 | Verification asks once per transaction and never upgrades a failure | `::test_verification_asks_once_per_transaction`, `::test_a_provider_failure_leaves_the_event_unknown_and_says_so` | pass |
| I14 | Reconciliation refuses a near miss and an absent event detail | `::test_reconciliation_refuses_a_near_miss` (3 cases), `::test_reconciliation_without_event_detail_is_not_a_match` | pass |
| I15 | A live run without LIVE mode or a key fails rather than skipping | `test_live_validation.py::test_a_live_run_without_a_key_fails_it_does_not_skip`, `::test_a_live_run_in_synthetic_mode_is_refused` | pass |
| I16 | A provider failure fails the validation and records the partial bundle | `::test_a_provider_failure_fails_the_validation` | pass |
| I17 | The bundle holds every artefact with its hash | `::test_the_bundle_holds_every_artefact_and_its_hash` | pass |
| I18 | The bundle never contains the API key | `::test_the_bundle_never_contains_the_api_key` | pass |
| I19 | The live trace reaches the accepted anchor with its provenance | `::test_the_live_trace_reaches_the_accepted_anchor_with_its_provenance` | pass |
| I20 | Receipts are saved and keep execution separate from finality | `::test_receipts_are_saved_and_separate_execution_from_finality` | pass |
| I21 | A recorded bundle replays through the same pipeline, visibly recorded | `::test_a_recorded_bundle_replays_through_the_same_pipeline` | pass |
| I22 | A replay miss is an error, never an empty history | `::test_a_replay_miss_is_an_error_not_an_empty_history` | pass |
| I23 | A replay cannot claim to be live | `::test_a_replay_cannot_claim_to_be_live` | pass |
| C06 | TronGrid still answers the documented shape, with a non-empty page | `::test_c06_trongrid_answers_the_documented_shape` | **not re-run since strengthening: deselected by default; needs `pytest -m live` plus `CFA_LIVE_TESTS=1`** |
| I24 | An empty page is a valid acquisition in general | `::test_an_empty_page_is_a_valid_acquisition_in_general` | pass |
| I25 | C06's own example refuses an empty page | `::test_the_c06_example_rejects_an_empty_page`, `::test_the_c06_example_accepts_a_page_with_events` | pass |
| J01 | Both the selection hash and the archive hash are recorded, neither replacing the other | `test_original_provenance.py::test_both_hashes_are_recorded_and_neither_replaces_the_other` | pass |
| J02 | The archive is preserved in place, not copied into `sources/` | `::test_the_archive_is_not_copied_into_sources` | pass |
| J03 | Partial or missing linkage is refused at import | `::test_a_partial_linkage_is_refused`, `::test_a_missing_archive_refuses_the_import` | pass |
| J04 | A claim with no upstream document still imports | `::test_a_claim_without_any_upstream_document_still_imports` | pass |
| J05 | Re-import updates provenance without duplicating the row | `::test_re_importing_with_provenance_updates_the_row_without_duplicating_it` | pass |
| J06 | Re-import never changes a review decision | `::test_updating_provenance_never_changes_a_review_decision` | pass |
| J07 | Acceptance verifies the archive as well as the selection | `::test_acceptance_verifies_the_archive_too` | pass |
| J08 | A missing, changed, or unlinked archive prevents acceptance | `::test_a_missing_archive_prevents_acceptance`, `::test_a_changed_archive_prevents_acceptance`, `::test_a_row_whose_linkage_was_hand_edited_to_be_partial_cannot_be_accepted` | pass |
| J09 | The linkage reaches the label evidence a report saves | `::test_the_linkage_reaches_the_label_evidence` | pass |

No live run has been executed. C06 and the Stage 1 live gate both remain open.

## E — Inference and amounts (stage 3) · F — Security (stage 4/5)

Beyond F02 above, no tests written. See `docs/FIVE_STAGE_PLAN.md` stages 3 and 5,
and `docs/THREAT_MODEL.md` for the controls these will cover.

## Stage 3A — service-outcome layer and strong-inference policy v1

All tests in `api/tests/test_service_outcome.py`. No live run; SYNTHETIC
fixtures are used for the strong_inference positive/negative pair and the
behavior-only confounder cases as noted per-row below.

| # | Behavior | Test(s) | Result |
|---|---|---|---|
| A | Direct seed transfer AND chronological path both reach an accepted, in-date anchor without assigning ownership of an intermediary | `test_service_outcome.py::test_A_direct_seed_transfer_reaches_accepted_label_without_intermediary_ownership` | pass |
| B | A supported branch and a blocked/unknown sibling branch stay independently visible; partial acquisition elsewhere doesn't erase either | `::test_B_sibling_branches_stay_independent` | pass |
| C | Unreviewed/expired/conflicted/wrong-network labels cannot produce `supported_destination`; a dated reserve-proof claim never becomes a continuous-control/customer-deposit claim | `::test_C_unreviewed_expired_conflicted_wrong_network_block_supported_destination` | pass |
| D | Repeated forwarding + shared sponsor/funder alone cannot produce `strong_inference`, cannot promote a candidate (no file writes), and repeated copies of one upstream source do not satisfy independence | `::test_D_shared_upstream_source_alone_is_not_independent_evidence`, `::test_D_no_file_writes_from_repeated_pattern_alone` | pass |
| E | Current-state delegation is not backdated; `history_only` verification and `ordering_ambiguous=true` block `supported_destination` for the specific claimed path | `::test_E_history_only_verification_blocks_supported_destination`, `::test_E_ordering_ambiguous_blocks_supported_destination`, `::test_E_current_state_delegation_not_backdated_by_policy` | pass |
| F | A SYNTHETIC positive case with eligible independent + corroborating evidence reaches `strong_inference`; removing the required independent source drops it back; neither branch writes any review file | `::test_F_synthetic_positive_and_negative_pair` (**SYNTHETIC fixtures**), `::test_F_policy_never_writes_review_files` (**SYNTHETIC fixtures**) | pass |
| G | SYNTHETIC frequent-customer, self-custody, and energy-rental confounder cases (behavior-only) are not labeled `strong_inference` from behavior alone | `::test_G_behavior_only_confounders_never_reach_strong_inference` (**SYNTHETIC fixtures — correctness fixtures only, not real evaluation data, no precision/accuracy claim made**) | pass |
| H | Repeated runs produce byte-identical JSON; every evidence reference resolves to real supplied input; JSON and HTML conclusions agree | `::test_H_repeated_runs_produce_byte_identical_json`, `::test_H_evidence_references_resolve_to_real_input`, `::test_H_json_and_html_agree` | pass |
| I | Not calling the outcome layer leaves `evidence_comparison.py`'s output byte-identical (regression check) | `::test_I_not_calling_outcome_layer_leaves_comparison_output_unchanged` | pass |
| J | Protected files (`verified_anchors.csv`, `deposit_candidates.csv`, `review_log.csv`, `independent_review.csv` if present, `evaluation_wallets.csv`) and historical `var/collect-behavioral-evidence/*` run bundles are byte-unchanged after exercising this layer | `::test_J_protected_files_and_var_bundles_untouched` | pass |
| — | Neither new module references the confounder-only evaluation-wallets data | `::test_evaluation_wallets_not_referenced_by_strong_inference_policy`, `::test_evaluation_wallets_not_referenced_by_service_outcome` | pass |

Real-data demonstration: `scripts/build_service_outcome.py --candidate
TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq` produces `supported_destination` for the
claim "OKX is this path's terminal receiving service", citing the real
`verified_anchors.csv`/`deposit_candidates.csv` rows, with the candidate's own
`review_state`/`address_role` explicitly noted as untouched. Verified by
diffing `data/deposit_candidates.csv` and `data/review_log.csv` sha256 hashes
before and after the run (unchanged).

## Stage 3B — evaluation-corpus workflow and model-readiness report

No ML training anywhere in this increment. Zero real evaluation wallets on
file; SYNTHETIC fixtures used only where noted.

| # | Behavior | Test(s) | Result |
|---|---|---|---|
| A | Dry-run validates; explicit `--write` actually appends | `test_ingest_evaluation_wallet.py::test_dry_run_validates_and_writes_nothing`, `::test_explicit_write_actually_appends` | pass |
| B | Missing provenance refused, by validation and by the CLI | `test_evaluation_wallets.py::test_validate_rejects_unsourced_wallet`, `test_ingest_evaluation_wallet.py::test_missing_source_reference_is_refused` | pass |
| C | Behavioral pattern alone cannot create/imply an evaluation category | `test_feature_dataset.py::test_evaluation_wallets_never_imports_attribution_or_inference_modules` (no code path derives a category from `behavioral_features.py` output) | pass |
| D | Writing an evaluation record never modifies protected files (byte-for-byte) | `test_ingest_evaluation_wallet.py::test_ingestion_never_touches_protected_data_files`, `::test_preserves_pre_existing_rows_byte_for_byte_on_append` | pass |
| E | A wallet with multiple windows never splits across train/eval | `test_feature_dataset.py::test_split_by_wallet_keeps_the_same_wallet_together` (Stage 2, kept passing) | pass |
| F | Time split never trains on a future window while evaluating an earlier window of the SAME wallet | `test_feature_dataset.py::test_assert_no_within_wallet_time_leakage_catches_future_train_window`, `::test_assert_no_within_wallet_time_leakage_passes_for_clean_split` | pass |
| G | Raw addresses absent from model-facing rows; pseudonymous ids stable/reproducible | `test_feature_dataset.py::test_model_facing_row_never_contains_raw_address_or_banned_fragments`, `::test_wallet_id_is_deterministic_and_pseudonymous` | pass |
| H | Missing features stay explicitly missing, never a "suspicious" value | `test_feature_dataset.py::test_missing_features_stay_missing_not_zero`, `::test_high_volume_fanout_control_wallet_is_not_flagged_suspicious` | pass |
| I | `service_outcome`/`strong_inference_policy` never accepted as model features or evaluation truth | `test_feature_dataset.py::test_service_outcome_never_imports_evaluation_wallets`, `::test_strong_inference_policy_never_imports_evaluation_wallets`, `::test_evaluation_dataset_never_imports_service_outcome_or_strong_inference` | pass |
| J | Two documents citing the same upstream source collapse to one source | `test_evaluation_wallets.py::test_dedupe_by_upstream_source_collapses_shared_origin`, `::test_dedupe_by_upstream_source_treats_blank_ids_as_unmatched` | pass |
| K | Readiness report deterministic; zero/tiny real corpus reports `NOT_READY_FOR_REAL_EVALUATION` without a fabricated model metric | `test_evaluation_readiness.py::test_readiness_report_is_byte_identical_for_identical_inputs`, `::test_zero_real_wallets_reports_not_ready_without_fabricated_metric` | pass |
| L | Full SYNTHETIC pipeline run (ingest → materialize → readiness) tagged SYNTHETIC and excluded from real-evaluation coverage counts | `test_evaluation_readiness.py::test_full_synthetic_pipeline_is_visibly_tagged_and_excluded_from_real_counts`, `test_evaluation_dataset.py::test_accepted_wallet_with_saved_bundle_materializes_one_row` | pass |
| — | Duplicate re-materialization does not create duplicate model rows | `test_evaluation_dataset.py::test_re_materializing_the_same_saved_run_does_not_duplicate_rows`, `test_feature_dataset.py::test_dedupe_rows_drops_duplicate_materializations` | pass |
| — | Missing evidence is skipped, never fetched live | `test_evaluation_dataset.py::test_missing_evidence_is_skipped_not_fetched_live` | pass |
| — | Changing `feature_definition_version` changes dataset snapshot identity | `test_feature_dataset.py::test_changing_feature_definition_version_changes_dedupe_key`, `test_evaluation_dataset.py::test_snapshot_hash_changes_with_feature_definition_version` | pass |
| — | Backward-compatible CSV schema growth | `test_evaluation_wallets.py::test_load_fills_defaults_for_a_pre_stage_3b_row_missing_new_columns` | pass |
| — | A duplicate (network, address, category) ingestion is refused, not silently double-appended | `test_ingest_evaluation_wallet.py::test_duplicate_network_address_category_is_refused_not_double_appended` | pass |

Real-data demonstration (superseded 2026-09-21, Stage 3B.1 below):
`data/evaluation_wallets.csv` confirmed header-only (0 real rows) before
and after Stage 3B's own work. The real materialization + readiness
pipeline run against it reported `materialized_window_count_real: 0`,
`independent_source_count_real: 0`, and `status:
NOT_READY_FOR_REAL_EVALUATION`. `data/verified_anchors.csv`,
`data/deposit_candidates.csv`, and `data/review_log.csv` sha256-verified
byte-unchanged before/after; `data/independent_review.csv` does not exist
in this repository.

## Stage 3B.1 — real evaluation-corpus sourcing pass (2026-09-21)

| Item | Check | Test(s) | Result |
|---|---|---|---|
| M | Appending a current-schema row under a stale pre-Stage-3B (9-column) header migrates the header in place, without altering any pre-existing data row's bytes | `test_evaluation_wallets.py::test_append_migrates_a_stale_pre_stage3b_header_in_place`, `::test_append_preserves_old_format_data_rows_when_migrating_header` | pass |

Real-data demonstration: 2 real, `RECORDED_PUBLIC`, `review_state=
unreviewed` records added to `data/evaluation_wallets.csv` via
`scripts/ingest_evaluation_wallet.py --write` (categories `self_custody`
and `other_operational_confounder`; see `docs/PROGRESS.md` for full
sourcing detail and the rejected-candidates list). Re-running the real
materialization + readiness pipeline reports `real_wallet_count: 2`,
`independent_source_count_real: 2`, `materialized_window_count_real: 0`
(both records are `unreviewed`, so `materialize_evaluation_dataset`'s
accepted-only filter excludes them before the missing-evidence check ever
runs), and `status: NOT_READY_FOR_REAL_EVALUATION`. Full suite: 394 passed
/ 1 deselected (392 baseline + the 2 tests above); `ruff check .` and
`mypy app` both clean (56 files). `data/verified_anchors.csv`,
`data/deposit_candidates.csv`, and `data/review_log.csv` sha256-verified
byte-unchanged before/after; `data/independent_review.csv` still does not
exist; `ppt/` untouched.

## Stage 3B.2 — evaluation-wallet review/audit/readiness-correctness workflow (2026-09-21)

New module `api/app/services/evaluation_review.py` + CLI
`scripts/review_evaluation_wallet.py`; readiness fields corrected in
`api/app/reports/evaluation_readiness.py`. All tests below live in
`api/tests/test_evaluation_review.py` unless noted, and were actually run.

| Item | Check | Test(s) | Result |
|---|---|---|---|
| A | Dry-run by default; no file write | `test_dry_run_is_default_and_writes_nothing` | pass |
| B | Named human reviewer + rationale required; automation-like/blank identities refused | `test_invalid_reviewer_identities_are_refused`, `test_valid_reviewer_identities_are_accepted`, `test_review_refuses_blank_reviewer_and_blank_rationale` | pass |
| C | `evidence_inspected` must identify the record's own source; arbitrary text refused | `test_arbitrary_evidence_inspected_text_is_refused`, `test_evidence_inspected_matching_source_reference_is_accepted` | pass |
| D | One review call changes exactly one registry row and appends exactly one audit record | `test_one_review_call_changes_one_row_and_appends_one_log_record` | pass |
| E | Terminal-state re-review refused except the one documented `accepted -> quarantined` transition | `test_rereviewing_terminal_state_is_refused_except_accepted_to_quarantined` | pass |
| F | Review workflow never touches verified_anchors.csv / deposit_candidates.csv / review_log.csv / independent_review.csv (hash-based) | `test_review_workflow_never_touches_protected_files` | pass |
| G | No code path self-promotes a record without an explicit reviewer+rationale+action | `test_no_action_supplied_means_nothing_decided_nothing_written` | pass |
| H | A "corporate treasury" source is never programmatically rewritten into `self_custody`; mismatch is surfaced in the packet | `test_treasury_source_is_not_auto_rewritten_and_mismatch_is_surfaced` | pass |
| I | Accepted SYNTHETIC record with no saved bundle stays `accepted`, materializes 0 rows, explicit reason | `test_accepted_record_with_no_saved_bundle_stays_accepted_but_materializes_nothing` | pass |
| J | Readiness with the 2 real (unreviewed) registry wallets + 0 materialized windows reports `model_dataset_split_feasible=false` | `test_two_unreviewed_registry_wallets_zero_materialized_is_not_split_feasible` | pass |
| K | Readiness with 2 materialized rows from the SAME synthetic wallet reports `model_dataset_split_feasible=false` | `test_two_materialized_rows_same_wallet_is_not_split_feasible` | pass |
| L | Readiness with 2 materialized rows from DISTINCT synthetic wallets reports `model_dataset_split_feasible=true`, no scientific-adequacy claim in text | `test_two_distinct_materialized_wallets_is_split_feasible_with_no_metric_claim` | pass |
| M | JSON and HTML readiness outputs agree on corrected fields | `test_json_and_html_outputs_agree_on_corrected_fields` | pass |
| N | Existing Stage 3B synthetic isolation/leakage tests continue to pass unmodified | full suite re-run | pass (419 passed / 1 deselected) |

Real-data demonstration (no writes): `scripts/review_evaluation_wallet.py`
run with no `--action` against both real Stage 3B.1 records
(`TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT` / `self_custody`,
`TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM` / `other_operational_confounder`);
both packets surfaced their category-semantics note, both remain
`review_state=unreviewed`, `data/evaluation_review_log.csv` was never
created against the real `data/` directory. Full suite: 419 passed / 1
deselected (394 baseline + 25 new); `ruff check .` and `mypy app` both
clean (57 files). `data/verified_anchors.csv`, `data/deposit_candidates.csv`,
`data/review_log.csv`, and `data/evaluation_wallets.csv` sha256-verified
byte-unchanged before/after; `data/independent_review.csv` still does not
exist; `ppt/` untouched.

## Stage 3B.3 — evaluation-wallet capture as a distinct subject_kind (2026-09-21)

Changes in `api/app/services/collect_behavioral_evidence.py` (new
`subject_kind` field + `collect_behavioral_evidence_for_evaluation_wallet`
wrapper), new CLI `scripts/evaluation_readiness_report.py`. Tests A-I live
in `api/tests/test_collect_behavioral_evidence_evaluation_wallet.py`, J in
`api/tests/test_evaluation_readiness_report_cli.py`, K-L already existed
in `api/tests/test_evaluation_readiness.py` (re-verified, unmodified).

| Item | Check | Test(s) | Result |
|---|---|---|---|
| A | Existing candidate/anchor mode unchanged (default `subject_kind`) | `test_default_subject_kind_is_candidate_or_anchor`, full existing `test_collect_behavioral_evidence.py` suite re-run unmodified | pass |
| B | Accepted evaluation record accepted | `test_accepted_evaluation_wallet_is_accepted` | pass |
| C | Refuses a quarantined evaluation record | `test_refuses_quarantined_evaluation_record` | pass |
| D | Refuses unreviewed/rejected/missing/wrong-network evaluation records | `test_refuses_non_accepted_review_states`, `test_refuses_missing_registry_record`, `test_refuses_wrong_network_record` | pass |
| E | Never writes deposit_candidates.csv/verified_anchors.csv/review_log.csv/evaluation_review_log.csv | `test_evaluation_capture_never_writes_registry_or_review_csvs` | pass |
| F | Bundle-only: `write=True` refused, behavioral_evidence.csv unchanged | `test_write_true_is_refused_for_evaluation_wallet` | pass |
| G | Manifest records `subject_kind=evaluation_wallet` + registry snapshot for audit | `test_manifest_records_subject_kind_and_registry_snapshot` | pass |
| H | Saved bundle readable by `load_preferred_behavioral_run` and `materialize_evaluation_dataset` | `test_saved_bundle_is_readable_by_downstream_loaders` | pass |
| I | Materialized feature names/flat dict never carry review state, service outcome, strong-inference result, or raw address | same test, assertions against `DISALLOWED_FEATURE_NAME_FRAGMENTS` and the raw address string | pass |
| J | Readiness CLI (`scripts/evaluation_readiness_report.py`) actually runs end-to-end offline via a real subprocess call, against both the real registry and a synthetic fixture | `test_readiness_cli_runs_offline_against_real_registry`, `test_readiness_cli_runs_offline_against_synthetic_fixture` | pass |
| K | Accepted registry row with no bundle: `missing_evidence`, split not feasible | pre-existing `test_zero_real_wallets_reports_not_ready_without_fabricated_metric` (re-verified) | pass |
| L | Synthetic saved bundle: materialization/readiness works with no live call | pre-existing `test_full_synthetic_pipeline_is_visibly_tagged_and_excluded_from_real_counts` (re-verified) | pass |

No live TronGrid call was made or attempted anywhere in this pass. Full
suite: 432 passed / 1 deselected; `ruff check .` and `mypy app` both clean.
`data/verified_anchors.csv`, `data/deposit_candidates.csv`,
`data/review_log.csv`, `data/evaluation_wallets.csv`, and
`data/evaluation_review_log.csv` sha256-verified byte-unchanged
before/after; `data/independent_review.csv` still does not exist; `ppt/`
untouched.

## Stage 3B.3 CLI wiring — `--subject-kind`/`--evaluation-registry` (2026-09-21)

Changes in `scripts/collect_behavioral_evidence.py` (new
`--subject-kind`/`--evaluation-registry` flags, dispatch to
`collect_behavioral_evidence_for_evaluation_wallet`, CLI-level `--write`
refusal for evaluation-wallet mode). New tests in
`api/tests/test_collect_behavioral_evidence_cli.py`.

| Item | Check | Test(s) | Result |
|---|---|---|---|
| M | `--help` documents `--subject-kind`/`--evaluation-registry` and both modes | `test_help_documents_subject_kind_and_evaluation_registry` | pass |
| N | Default candidate/anchor CLI behavior (no new flags) unchanged | `test_default_subject_kind_cli_behavior_unchanged` | pass |
| O | Accepted evaluation wallet admitted via CLI; `manifest.json` records `subject_kind: "evaluation_wallet"` | `test_evaluation_wallet_admitted_via_cli` | pass |
| P | Quarantined evaluation wallet refused via CLI with clear message, no bundle written | `test_evaluation_wallet_quarantined_refused_via_cli` | pass |
| Q | `--write` in evaluation-wallet mode refused at the CLI level before any network activity (no respx interceptor active) | `test_evaluation_wallet_write_refused_before_network` | pass |
| R | No protected CSV (`verified_anchors.csv`, `deposit_candidates.csv`, `review_log.csv`, `evaluation_wallets.csv`, `evaluation_review_log.csv`) changed by any scenario above | sha256 hash-comparison assertions embedded in O/P/Q | pass |

No live TronGrid call was made or attempted. Full suite: 437 passed / 1
deselected (432 baseline + 5 new); `ruff check .` and `mypy app` both
clean (57 source files).

## Stage 4 — evidence export bundle (2026-09-22)

New module `api/app/services/evidence_export.py` + `POST /api/v1/traces/export`.
Full design rationale in `docs/DECISIONS.md` D026. All tests below live in
`api/tests/test_evidence_export.py` unless noted, and were actually run.

| Item | Check | Test(s) | Result |
|---|---|---|---|
| A | Bundle contains exactly the seven expected files | `test_bundle_contains_every_expected_file` | pass |
| B | Generated PDF starts with the PDF magic bytes | `test_pdf_file_starts_with_the_pdf_magic_bytes` | pass |
| C | `evidence.json` round-trips the exact source result, unmodified | `test_json_file_round_trips_the_exact_source_result` | pass |
| D | `transfers.csv` includes the seed transfer (hop 0) and each onward hop | `test_transfers_csv_includes_the_seed_transfer_and_each_onward_hop` | pass |
| E | `branch_endings.csv` reports `attribution_status`, not just `endpoint_class` | `test_branch_endings_csv_reports_the_attribution_status` | pass |
| F | `labels.csv` has zero rows when no branch carries a label (never a fabricated row) | `test_labels_csv_is_empty_when_no_branch_carries_a_label` | pass |
| G | `limitations.csv` reports a recorded limitation exactly | `test_limitations_csv_reports_the_recorded_limitation` | pass |
| H | Manifest's `files` field is the project-wide `{filename: sha256}` mapping, matching every hash in the bundle | `test_manifest_files_is_the_project_wide_name_to_sha256_mapping` | pass |
| I | A written bundle interoperates with the existing `operational_status.verify_manifest_hashes` with zero adaptation | `test_manifest_interoperates_with_verify_manifest_hashes` | pass |
| J | Manifest caveat states a hash is not evidence of correctness and the bundle is not a legal instrument | `test_manifest_never_claims_the_hash_proves_correctness` | pass |
| K | Manifest carries export format version, request id, and the trace's own scope fields | `test_manifest_carries_scope_and_format_version` | pass |
| L | `evidence.json` and every CSV file are byte-identical across two builds of the same result (HTML/PDF excluded — see D026 for why) | `test_json_and_csv_files_are_byte_identical_across_two_builds` | pass |
| M | A failed PDF render raises `EvidenceExportError` instead of returning a partial file | `test_pdf_rendering_failure_raises_instead_of_returning_a_partial_file` | pass |
| N | `POST /api/v1/traces/export` returns a zip whose manifest hashes verify against its own contents, and whose `evidence.html`/`evidence.json` agree with the plain `/report` route's content | `test_trace_endpoint.py::test_evidence_export_bundle_matches_the_report_and_verifies_its_own_hashes` | pass |

No live TronGrid call was made. Full suite: 642 passed / 1 deselected (628
baseline measured on this working tree + 14 new); `ruff check .` and
`mypy app` both clean (66 source files).

## Stage 4 — legal-request drafts (2026-09-22)

New module `api/app/services/legal_requests.py` + `api/app/reports/
legal_request.py` + `POST /api/v1/traces/legal-request-draft` (and
`.../report`). Full design rationale in `docs/DECISIONS.md` D027. Tests live
in `api/tests/test_legal_requests.py`, `api/tests/test_legal_request_
report.py`, and `api/tests/test_trace_endpoint.py` as noted.

| Item | Check | Test(s) | Result |
|---|---|---|---|
| A | information/preservation requests against a pooled hot-wallet-role address are not refused | `test_information_request_against_a_hot_wallet_is_not_refused`, `test_preservation_request_against_a_hot_wallet_is_not_refused` | pass |
| B | asset-restriction against a hot_wallet-role address is refused, with the role named in the reason | `test_asset_restriction_against_a_hot_wallet_is_refused` | pass |
| C | asset-restriction against an unknown-role labeled address is refused | `test_asset_restriction_against_an_unknown_role_is_refused` | pass |
| D | asset-restriction against an unlabeled deposit_candidate lead is refused | `test_asset_restriction_against_an_unlabeled_candidate_is_refused` | pass |
| E | asset-restriction against a confirmed address_role=deposit address is drafted, not refused | `test_asset_restriction_against_a_confirmed_deposit_address_is_drafted` | pass |
| F | A target address the trace never reached raises a caller error, not a refused draft | `test_unreached_address_raises_a_caller_error_not_a_refused_draft` | pass |
| G | Each blank required investigator field (agency/officer/case reference/incident summary) raises | `test_blank_required_investigator_field_raises` (parametrized) | pass |
| H | The draft marker (not legal process / not sent / not signed) is present on both drafted and refused outcomes | `test_draft_marker_is_always_present_even_when_refused` | pass |
| I | A missing legal-authority reference is marked not-provided, never fabricated | `test_checklist_never_fabricates_a_missing_legal_authority_reference` | pass |
| J | A supplied legal-authority reference is recorded exactly and marked provided | `test_checklist_records_a_supplied_legal_authority_reference` | pass |
| K | `items_requested` differs by request kind; asset-restriction text names only the target, not a pooled wallet | `test_items_requested_differs_by_kind_and_asset_restriction_names_the_target_only` | pass |
| L | `exchange_account_identifiers`'s provided flag tracks whether it was actually supplied | `test_exchange_account_identifiers_provided_flag_tracks_whether_it_was_supplied` | pass |
| M | Identifiers include observed transaction hashes and point to the evidence export bundle | `test_identifiers_include_observed_transaction_hashes_and_point_to_the_export_bundle` | pass |
| N | Checklist source names the real, fetched OKX guide, not an invented one | `test_checklist_source_names_the_real_provider_guide` | pass |
| O | `investigation_findings_to_date` is auto-filled from the trace's own facts, not free text | `test_investigation_findings_are_auto_filled_from_the_trace_not_free_text` | pass |
| P | `to_json()` round-trips every top-level field | `test_to_json_round_trips_every_top_level_field` | pass |
| Q | An unrecognised `request_kind` raises | `test_unknown_request_kind_raises` | pass |
| R | HTML render states DRAFT/REFUSED status, the marker text, and the refusal reason when present | `test_legal_request_report.py::test_drafted_page_states_its_status_and_marker`, `::test_refused_page_shows_the_refusal_reason` | pass |
| S | HTML render escapes hostile text in the target entity name and the refusal reason | `test_legal_request_report.py::test_hostile_text_in_target_entity_name_is_escaped`, `::test_hostile_text_in_refusal_reason_is_escaped` | pass |
| T | `POST /api/v1/traces/legal-request-draft` against the SYNTHETIC fixture's `address_role=deposit` service drafts (not refuses) an asset-restriction request | `test_trace_endpoint.py::test_legal_request_draft_against_the_confirmed_deposit_service_is_drafted` | pass |
| U | `.../report` renders a printable HTML page with the same facts | `test_trace_endpoint.py::test_legal_request_draft_report_renders_html` | pass |
| V | A target address outside the trace, a blank investigator field, or an unknown request kind each return 422 | `test_trace_endpoint.py::test_legal_request_draft_requires_a_reached_target_address`, `::test_legal_request_draft_requires_non_blank_investigator_fields`, `::test_legal_request_draft_rejects_an_unknown_request_kind` | pass |

**Real-data note (not a test, a fact checked by hand against the live
registry file)**: both real accepted anchors in `data/verified_anchors.csv`
are `address_role=unknown`, so an asset-restriction draft against either, as
this codebase stands today, is refused by rule B/C above -- the pooled-wallet
rule is exercised by this project's actual real data, not only by a
synthetic fixture built to trigger it.

No live TronGrid call was made. Full suite: 674 passed / 1 deselected (642
baseline measured on this working tree + 32 new); `ruff check .` and
`mypy app` both clean (68 source files).

## Stage 4 — mock complaint queue (2026-09-22)

New module `api/app/services/mock_complaint_adapter.py` + `api/app/routes/
mock_complaints.py` + `fixtures/mock_complaints.json`. Full design rationale
in `docs/DECISIONS.md` D028. Tests live in `api/tests/test_mock_complaint_
adapter.py` and `api/tests/test_mock_complaints_route.py` as noted.

| Item | Check | Test(s) | Result |
|---|---|---|---|
| A | The real fixture loads and every complaint carries `source_channel=MOCK_LOCAL_QUEUE` | `test_the_real_fixture_loads_and_every_complaint_names_the_mock_channel` | pass |
| B | The real fixture links no real NCRP/SAHYOG/cybercrime.gov.in URL | `test_the_real_fixture_never_links_a_real_government_portal` | pass |
| C | A known complaint reference is found; an unknown one returns None (not an exception) | `test_get_mock_complaint_finds_a_known_reference`, `::test_get_mock_complaint_returns_none_for_an_unknown_reference` | pass |
| D | A complaint naming a seed event drafts as `mode=incident` with the event/amount carried through | `test_seed_draft_for_a_complaint_with_a_seed_event_is_incident_mode` | pass |
| E | A complaint with no seed event drafts as `mode=address_discovery` and carries no amount | `test_seed_draft_for_a_complaint_with_no_seed_event_is_address_discovery_mode` | pass |
| F | A seed draft never contains a fabricated `asset_id` | `test_seed_draft_never_invents_an_asset_id` | pass |
| G | A seed draft states plainly that nothing has been submitted | `test_seed_draft_states_that_nothing_has_been_submitted` | pass |
| H | A missing fixture file raises, rather than returning an empty list | `test_missing_fixture_file_raises` | pass |
| I | A file that does not declare `source_channel=MOCK_LOCAL_QUEUE` is refused, not silently loaded | `test_fixture_with_the_wrong_source_channel_is_refused` | pass |
| J | An explicit `fixture_path` overrides the default and loads correctly | `test_a_custom_well_formed_fixture_loads_via_the_explicit_path` | pass |
| K | `GET /api/v1/complaints/mock` requires authentication | `test_mock_complaints_route.py::test_list_requires_authentication` | pass |
| L | The list response names the mock channel and every complaint's `reporter_contact` is marked FICTIONAL | `test_mock_complaints_route.py::test_list_returns_every_fixture_complaint_labeled_mock` | pass |
| M | A single complaint is fetched by reference; an unknown reference is 404 (both the complaint and its seed-draft route) | `test_mock_complaints_route.py::test_get_one_complaint_by_reference`, `::test_get_unknown_complaint_is_404`, `::test_seed_draft_for_unknown_complaint_is_404` | pass |
| N | The seed-draft route returns the shaped draft, never creates anything | `test_mock_complaints_route.py::test_seed_draft_is_never_submitted_and_matches_the_complaint` | pass |
| O | A complaint's own seed-draft output, POSTed to the real `/api/v1/traces` endpoint, reaches the real supported-destination result -- complaint -> seed draft -> trace as one connected path | `test_mock_complaints_route.py::test_seed_draft_from_a_mock_complaint_traces_end_to_end` | pass |

No live TronGrid call was made. No NCRP/SAHYOG endpoint was contacted --
none exists in this codebase. Full suite: 692 passed / 1 deselected (674
baseline measured on this working tree + 18 new); `ruff check .` and
`mypy app` both clean (70 source files).


## Stage 4 — checkpointed new-event monitoring (2026-09-23)

New modules `api/app/services/monitoring.py`, `api/app/routes/watches.py`,
`scripts/poll_watches.py`, plus migration `4c0696953d8d`. Design rationale in
`docs/DECISIONS.md` D029. Every test below lives in `api/tests/test_monitoring.py`
unless noted, runs offline, and was observed passing in the full-suite run recorded
at the end of this section. The Stage 4 gate row, "one supported new event produces
one alert", is M01.

| Item | Check | Test(s) | Result |
|---|---|---|---|
| M01 | One new supported transfer creates exactly one alert, with its exact event reference, a string amount beyond int64/float precision, and the checkpoint advanced to the window end | `test_m01_one_new_event_creates_exactly_one_alert` | pass |
| M02 | Polling the same data twice leaves one alert | `test_m02_polling_the_same_data_twice_does_not_duplicate` | pass |
| M03 | Overlap re-read (E1,E2 then E2,E3): the second window starts `overlap` behind the checkpoint, and there are three alerts in total | `test_m03_replay_overlap_is_safe` | pass |
| M04 | Restart (new engine and session on a file-backed DB) replaying old plus new data alerts only the new event | `test_m04_restart_recovery_does_not_realert` | pass |
| M05 | Two transfers in one transaction are two alerts | `test_m05_two_transfers_in_one_transaction_are_two_alerts` | pass |
| M06 | Failed and reverted transfers do not alert; exclusion reasons recorded | `test_m06_failed_and_reverted_transfers_do_not_alert`; TronGrid path: `test_m15_live_path_verifies_execution_and_measures_wall_clock_lag` (REVERT receipt excluded) | pass |
| M07 | An approval never becomes a transfer alert | `test_m07_an_approval_never_becomes_a_transfer_alert` | pass |
| M08 | Same symbol, wrong contract: no alert; a symbol is refused as a watch asset | `test_m08_same_symbol_wrong_contract_does_not_alert`, `test_a_watch_needs_the_exact_supported_contract_not_a_symbol`, `test_m16_a_symbol_is_not_accepted_as_the_watched_asset` | pass |
| M09 | Provider failure is `provider_failure` / `coverage=failed`, the checkpoint is not advanced, and it is never "0 new events, success" | `test_m09_provider_failure_is_not_an_empty_successful_poll`, `test_live_http_error_is_a_provider_failure` | pass |
| M10 | A repeated event across pages yields one alert; distinct events in one tx stay distinct; a reused reference with different content is reported | `test_m10_pagination_repeats_collapse_but_same_tx_events_stay_distinct`, `test_a_reused_reference_with_different_content_is_reported` | pass |
| M11 | Same-timestamp, same-block events indexed after a poll are caught at the inclusive checkpoint even with zero overlap; an unindexed event keeps `ordering_ambiguous` | `test_m11_same_timestamp_events_at_the_checkpoint_are_not_dropped` | pass |
| M12 | A synthetic source cannot serve a LIVE watch; poll mode must match watch mode; recorded replay is RECORDED_PUBLIC; a SYNTHETIC fixture cannot pose as recorded; the TronGrid adapter refuses SYNTHETIC without a request; a LIVE watch refuses a SYNTHETIC asset | `test_m12_a_synthetic_source_cannot_serve_a_live_watch`, `test_m12_a_poll_mode_must_match_the_watch_mode`, `test_m12_recorded_replay_is_labelled_recorded_public`, `test_m12_a_synthetic_fixture_cannot_pose_as_a_recorded_replay`, `test_m12_the_live_adapter_refuses_a_synthetic_watch`, `test_m12_a_live_watch_rejects_a_synthetic_fixture_asset` | pass |
| M13 | Alert persisted but checkpoint not advanced, across a real restart: no duplicate; the DB rejects a duplicate alert row; a racing insert that the pre-check missed is absorbed by the unique key | `test_m13_alert_persisted_but_checkpoint_not_advanced_does_not_duplicate`, `test_m13_the_database_rejects_a_duplicate_alert`, `test_m13_a_racing_insert_is_absorbed_by_the_unique_key` | pass |
| M14 | Failure after page 1: `partial`, checkpoint unchanged; the next poll re-reads from scope start and alerts E2/E3; a truncated window does not advance the checkpoint | `test_m14_checkpoint_does_not_skip_after_a_mid_window_failure`, `test_a_truncated_window_does_not_advance_the_checkpoint` | pass |
| M15 | Synthetic lag is exact (300 s) and labelled `simulated_clock`; RECORDED_PUBLIC lag is null; LIVE refuses an injected clock; the TronGrid path (history, events, receipts via `respx`) labels lag `live_wall_clock` | `test_m15_synthetic_lag_is_deterministic_and_labelled_simulated`, `test_m12_recorded_replay_is_labelled_recorded_public`, `test_m15_a_live_poll_cannot_use_an_injected_clock`, `test_m15_live_path_verifies_execution_and_measures_wall_clock_lag` | pass |
| M16 | Unauthenticated: 401. A foreign organization gets 404 for the watch list, the watch, its alerts, its polls, and watch creation, including when naming the watch under its own case | `test_m16_routes_require_authentication`, `test_m16_owner_sees_watch_and_alerts`, `test_m16_a_foreign_organization_gets_404_for_watch_and_alerts` | pass |
| R1 | A provisional alert upgrades to confirmed; a later `removed` retracts it (row kept, history appended); a first-seen removed event creates no alert | `test_a_provisional_alert_is_upgraded_when_confirmed`, `test_a_removed_event_retracts_its_alert_without_deleting_it`, `test_a_removed_event_never_seen_before_creates_no_alert` | pass |
| R2 | Zero-value, not-involving-the-address, and before-scope events are excluded with a reason, even when the source ignores the lower bound | `test_other_non_qualifying_events_are_excluded_with_a_reason` (3 cases) | pass |
| R3 | A configured secret in a provider error message is redacted from the stored poll run | `test_a_provider_error_message_never_carries_the_api_key` | pass |
| R4 | The capability row is `partial` and says "not a mempool feed" whether or not a key is configured | `test_capability_row_is_partial_and_never_claims_a_verified_live_feed`; `test_console.py::test_capabilities_are_honest_about_what_is_not_built` (expectation updated from `not_built`) | pass |

**Not verified:** no live TronGrid poll was run (no key configured), so there is no
live observation-lag figure. The TronGrid path above is offline (`respx`). The
migration was checked on SQLite only, not PostgreSQL.

Full suite: 733 passed / 1 deselected (692 baseline measured on this working tree
+ 41 new in `api/tests/test_monitoring.py`); `ruff check .` and `mypy app` both
clean (72 source files).

## Stage 4 — fund-flow graph page (2026-09-23)

Tests in `api/tests/test_fund_flow.py`; all observed passing in the full-suite run
below. Route rows skip, like `test_console.py`, when the saved artifacts are absent.

| Item | Check | Test(s) | Result |
|---|---|---|---|
| G1 | One node per wallet (reconverging wallet has two arrivals); one edge per transfer | `test_one_node_per_wallet_and_one_edge_per_transfer` | pass |
| G2 | Transfers in one transaction, or between the same pair, stay separate edges; a repeated event reference is drawn once | `test_two_transfers_in_one_transaction_are_two_edges`, `test_a_repeated_event_reference_is_drawn_once` | pass |
| G3 | Roles follow recorded endings; a candidate is never drawn or labelled as supported; conflicting endings are shown as a conflict | `test_roles_follow_recorded_endings_and_a_candidate_is_never_supported`, `test_conflicting_endings_are_shown_as_a_conflict` | pass |
| G4 | A reconvergence ending is a wallet, not a boundary; an ending with a stated boundary reason stays unresolved | `test_a_reconvergence_ending_is_not_drawn_as_a_boundary`, `test_a_terminal_unresolved_ending_stays_unresolved` | pass |
| G5 | Amounts stay exact strings (uint256 max), with no amount or total in the stats | `test_amounts_stay_exact_strings_and_nothing_is_summed` | pass |
| G6 | Edges point forward when acyclic; a cycle terminates and is reported; ambiguous ordering is dashed | `test_edges_point_forward_when_the_flow_is_acyclic`, `test_a_cycle_terminates_and_is_reported`, `test_ambiguous_ordering_is_drawn_dashed` | pass |
| G7 | An older result reconstructs only the seed transfer, labelled; a missing non-seed event is reported, not invented | `test_an_older_result_reconstructs_only_the_seed_transfer` | pass |
| G8 | Deterministic SVG; hostile label/note/event text escaped in SVG, page, and embedded JSON | `test_rendering_is_deterministic`, `test_hostile_strings_are_escaped_in_svg_json_and_page` | pass |
| G9 | Page states mode, capture mode, what is not drawn, and allocation_unknown; has no external script; empty or absent results are stated, not drawn empty | `test_page_states_mode_and_what_is_not_drawn`, `test_recorded_preset_notes_its_capture_mode`, `test_no_transfers_and_no_trace_are_stated_not_drawn_empty` | pass |
| G10 | `/graph` draws the synthetic and recorded presets; unknown preset is 404; JSON route; nav and Path-card links; not registered in prod | `test_graph_route_draws_the_saved_synthetic_preset`, `test_graph_route_draws_the_recorded_okx_preset`, `test_graph_route_unknown_preset_is_404`, `test_graph_json_route`, `test_nav_links_the_fund_flow_page`, `test_console_path_card_links_to_the_graph`, `test_graph_route_is_not_registered_in_prod` | pass |

Full suite: 757 passed / 1 deselected (733 + 24); `ruff check .` and `mypy app`
clean (73 source files). No live provider call.
