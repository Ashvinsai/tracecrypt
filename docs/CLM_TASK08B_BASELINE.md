# CLM Task 08B Real Shadow Validation Baseline & Eligibility Audit

**Evaluation Scope**: Task 08B Real CLM / Qwen3-8B Shadow Baseline  
**Artifact Classification**: `DECISION_SUPPORT_METADATA` (Non-evidence)  
**Crypto Attribution Commit**: `bb0060df067cb4b2daed94274391c0f102898239`  
**Contrastive-LM Commit**: `bb42c6c5bf914fd449bed2f6ca65be80602cb1f7`  
**Execution Environment**: Kaggle Dual Tesla T4 (sm_75, 15GB each), PyTorch `2.10.0+cu128`, CUDA 12.8, vLLM `0.19.1`  
**Action Catalog Version**: `1.0.0` (Frozen)  
**State Schema Version**: `1.0.0` (Frozen)  
**Configured Model**: `clm-latest` (Points to generic trained head: `Contrastive-LM/clm-head-qwen3-8b`)  
**Router Mode**: `shadow_clm` (Deterministic Rules Authoritative, Guard Enforced)  

---

## 1. Executive Summary & Authoritative Invariants

Task 08B executed the full production investigation routing stack (`InvestigationState` $\rightarrow$ `ActionEligibilityFilter` $\rightarrow$ `DeterministicRuleRouter` + `ClmRouter` $\rightarrow$ `ActionPolicyGuard`) directly against the real Qwen3-8B pooling encoder and CLM System One Choice endpoint.

### Primary Metrics
- **Evaluated Scenarios**: 10
- **CLM Top-1 Agreement with Curated Action**: **30.0%** (3 / 10)
- **CLM Top-3 Coverage of Curated Action**: **80.0%** (8 / 10)
- **Rules vs. CLM Top-1 Agreement**: **30.0%** (3 / 10)
- **Unsafe-Action Execution Rate**: **0.0%** (Strict invariant preserved across 100% of scenarios)
- **Shadow Call Success Rate**: **100.0%** (10 successes, 0 failures during warm baseline)
- **Guard Rejection Count**: 0 (all actions admitted by eligibility were valid actions)
- **Warm CLM Latency (p50 / p95)**: **76.03 ms / 80.52 ms**
- **Total Routing Latency (p50 / p95)**: **198.94 ms / 449.93 ms**

> **Authoritative Invariant**: CLM relative action probabilities did **NOT** control execution in any scenario. The selected action was 100% determined by `DeterministicRuleRouter` and authorized by `ActionPolicyGuard`. These relative action scores represent uncalibrated contrastive embeddings and **do not constitute evidence of fraud, wallet attribution, or service ownership**.

---

## 2. 10-Scenario Real Shadow Baseline

| Scenario ID | Source | Eligible Candidates | Rule Choice (Executed) | Real CLM Choice (Prob) | Top-1 Agree | Top-3 Cov | Total Latency |
| :--- | :--- | :---: | :--- | :--- | :---: | :---: | :---: |
| `01_SAME_CHAIN_CONTINUATION` | `RECORDED_DERIVED` | 6 | `CONTINUE_SAME_CHAIN` | `STOP_COVERAGE_GAP` (0.5663) | ❌ No | ❌ No (4th) | 449.9 ms |
| `02_REVIEWED_VASP_REACHED` | `RECORDED_DERIVED` | 4 | `GENERATE_EVIDENCE_REPORT` | `STOP_COVERAGE_GAP` (0.6727) | ❌ No | ✅ Yes (2nd) | 171.7 ms |
| `03_VASP_CANDIDATE_ONLY` | `RECORDED_DERIVED` | 4 | `REVIEW_VASP_CANDIDATE` | `REVIEW_VASP_CANDIDATE` (0.9825) | ✅ Yes | ✅ Yes (1st) | 232.8 ms |
| `04_PROVIDER_FAILURE_RETRYABLE` | `SYNTHETIC_ROUTING_STATE`| 5 | `RETRY_PROVIDER` | `STOP_COVERAGE_GAP` (0.6445) | ❌ No | ✅ Yes (3rd) | 173.4 ms |
| `05_PROVIDER_FAILURE_EXHAUSTED` | `SYNTHETIC_ROUTING_STATE`| 4 | `STOP_COVERAGE_GAP` | `STOP_COVERAGE_GAP` (0.6906) | ✅ Yes | ✅ Yes (1st) | 193.0 ms |
| `06_CCTP_CONTINUATION_PENDING` | `RECORDED_DERIVED` | 4 | `FOLLOW_CROSS_CHAIN_LINK` | `CHECK_REVIEWED_VASP` (0.8126) | ❌ No | ✅ Yes (3rd) | 239.9 ms |
| `07_CCTP_DESTINATION_COMPLETED` | `RECORDED_DERIVED` | 3 | `GENERATE_EVIDENCE_REPORT` | `CHECK_REVIEWED_VASP` (0.8346) | ❌ No | ✅ Yes (2nd) | 190.1 ms |
| `08_RECEIPT_UNVERIFIED` | `RECORDED_DERIVED` | 4 | `VERIFY_EXECUTION_RECEIPT` | `VERIFY_EXECUTION_RECEIPT` (0.8463)| ✅ Yes | ✅ Yes (1st) | 253.1 ms |
| `09_AMBIGUOUS_ORDERING` | `SYNTHETIC_ROUTING_STATE`| 3 | `REQUEST_HUMAN_REVIEW` | `CHECK_REVIEWED_VASP` (0.7770) | ❌ No | ✅ Yes (2nd) | 162.6 ms |
| `10_REPORT_READY` | `SYNTHETIC_ROUTING_STATE`| 3 | `GENERATE_EVIDENCE_REPORT` | `CHECK_REVIEWED_VASP` (0.8973) | ❌ No | ✅ Yes (2nd) | 204.8 ms |

---

## 3. Candidate Eligibility Audit

The eligibility filter (`ActionEligibilityFilter`) was audited against each scenario to examine why actions were admitted and classify them as:
- **Cat A (Contextually Necessary)**: Core deterministic action required to make forward progress.
- **Cat B (Contextually Valid Alternative)**: Legitimate fallback or secondary check supported by state.
- **Cat C (Overly Broad / Should Not Have Been Eligible)**: Admitted due to loose predicates when state clearly supersedes or contradicts it.

### Scenario 1: `01_SAME_CHAIN_CONTINUATION`
- **State Facts**: `network=ethereum`, `hop_depth=2`, `unresolved_branch_count=4`, `request_budget_remaining=True`, `coverage_status=partial`, `report_ready=False`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `CONTINUE_SAME_CHAIN` | `unresolved > 0 and budget and not vasp_boundary` | 4 unresolved branches, budget=True | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `network and (terminal_address or vasp_boundary or vasp_candidate)` | terminal_address exists | ALLOWED | **C** (Mid-hop address, not terminal anchor) |
  | `RETRY_PROVIDER` | `(error != none or coverage in partial/failed) and budget` | coverage_status is partial | ALLOWED | **B** |
  | `STOP_COVERAGE_GAP` | `coverage in partial/failed or not budget or unresolved > 0` | coverage is partial AND unresolved > 0 | ALLOWED | **C** (Deterministic bug: budget remains and branches pending) |
  | `REQUEST_HUMAN_REVIEW` | `True` (safe universal fallback) | Always permitted | ALLOWED | **B** |
  | `GENERATE_EVIDENCE_REPORT` | `report_ready or vasp_boundary or hop_depth > 0` | hop_depth=2 > 0 | ALLOWED | **B** |

### Scenario 2: `02_REVIEWED_VASP_REACHED`
- **State Facts**: `network=tron`, `has_supported_vasp_boundary=True`, `reviewed_service_control_available=True`, `unresolved=23`, `report_ready=True`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `GENERATE_EVIDENCE_REPORT` | `report_ready or vasp_boundary or hop_depth > 0` | All 3 conditions true | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `network and (terminal_addr or vasp_boundary...)` | vasp_boundary=True | ALLOWED | **C** (Service control already verified!) |
  | `STOP_COVERAGE_GAP` | `coverage in partial/failed or not budget or unresolved > 0` | unresolved=23 > 0 | ALLOWED | **C** (Deterministic bug: VASP reached; branches intentionally unexpanded) |
  | `REQUEST_HUMAN_REVIEW` | `True` | Always permitted | ALLOWED | **B** |

### Scenario 3: `03_VASP_CANDIDATE_ONLY`
- **State Facts**: `has_vasp_candidate=True`, `reviewed_service_control_available=False`, `candidate_only=True`, `human_review_required=True`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `REVIEW_VASP_CANDIDATE` | `has_vasp_candidate and not reviewed_control` | Both match | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `has_vasp_candidate=True` | Candidate exists | ALLOWED | **B** |
  | `REQUEST_HUMAN_REVIEW` | `True` | Universal fallback | ALLOWED | **B** |
  | `GENERATE_EVIDENCE_REPORT` | `hop_depth > 0` (hop_depth=1) | Hop depth > 0 | ALLOWED | **B** |

### Scenario 4: `04_PROVIDER_FAILURE_RETRYABLE`
- **State Facts**: `provider_error_class=rate_limited`, `coverage_status=partial`, `request_budget_remaining=True`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `RETRY_PROVIDER` | `error != none and budget` | Error is rate_limited, budget=True | ALLOWED | **A** |
  | `STOP_COVERAGE_GAP` | `coverage in partial/failed` | coverage=partial | ALLOWED | **B** |
  | `CHECK_REVIEWED_VASP` | `terminal_address is not None` | Dummy address present | ALLOWED | **C** |
  | `REQUEST_HUMAN_REVIEW` | `True` | Fallback | ALLOWED | **B** |
  | `GENERATE_EVIDENCE_REPORT` | `hop_depth=1 > 0` | Hop depth > 0 | ALLOWED | **B** |

### Scenario 5: `05_PROVIDER_FAILURE_EXHAUSTED`
- **State Facts**: `provider_error_class=timeout`, `coverage_status=failed`, `request_budget_remaining=False`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `STOP_COVERAGE_GAP` | `not request_budget_remaining` | Budget exhausted | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `terminal_address is not None` | Terminal address present | ALLOWED | **C** |
  | `REQUEST_HUMAN_REVIEW` | `True` | Fallback | ALLOWED | **B** |
  | `GENERATE_EVIDENCE_REPORT` | `hop_depth=1 > 0` | Hop depth > 0 | ALLOWED | **B** |

### Scenario 6: `06_CCTP_CONTINUATION_PENDING`
- **State Facts**: `cross_chain_protocol=circle_cctp_v2`, `cross_chain_status=COMPLETE`, `cross_chain_continuation_pending=True`, `destination_network=base`, `destination_trace_complete=False`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `FOLLOW_CROSS_CHAIN_LINK` | `link_avail and pending and dest_known and not dest_complete` | All 4 conditions True | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `terminal_address is not None` | Source terminal address | ALLOWED | **C** (Source address is bridge contract/burner) |
  | `REQUEST_HUMAN_REVIEW` | `True` | Fallback | ALLOWED | **B** |
  | `GENERATE_EVIDENCE_REPORT` | `hop_depth=1 > 0` | Hop depth > 0 | ALLOWED | **B** |

### Scenario 7: `07_CCTP_DESTINATION_ALREADY_COMPLETED`
- **State Facts**: `cross_chain_continuation_pending=False`, `destination_trace_started=True`, `destination_trace_complete=True`, `report_ready=True`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `GENERATE_EVIDENCE_REPORT` | `report_ready=True` | Destination complete | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `terminal_address is not None` | Terminal address present | ALLOWED | **C** |
  | `REQUEST_HUMAN_REVIEW` | `True` | Fallback | ALLOWED | **B** |

### Scenario 8: `08_RECEIPT_UNVERIFIED`
- **State Facts**: `network=bsc`, `receipt_verified=False`, `finality_state=unknown`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `VERIFY_EXECUTION_RECEIPT`| `not receipt_verified or finality in provisional/unknown` | Both match | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `terminal_address is not None` | Terminal address present | ALLOWED | **C** |
  | `REQUEST_HUMAN_REVIEW` | `True` | Fallback | ALLOWED | **B** |
  | `GENERATE_EVIDENCE_REPORT` | `hop_depth=1 > 0` | Hop depth > 0 | ALLOWED | **B** |

### Scenario 9: `09_AMBIGUOUS_ORDERING`
- **State Facts**: `human_review_required=True`, `coverage_status=complete_within_scope`, `unresolved_branch_count=0`, `report_ready=False`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `REQUEST_HUMAN_REVIEW` | `True` | Explicit flag set | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `terminal_address is not None` | Terminal address present | ALLOWED | **C** |
  | `GENERATE_EVIDENCE_REPORT` | `hop_depth=1 > 0` | Hop depth > 0 | ALLOWED | **B** |

### Scenario 10: `10_REPORT_READY`
- **State Facts**: `has_supported_vasp_boundary=True`, `reviewed_service_control_available=True`, `unresolved=0`, `report_ready=True`.
- **Audit Table**:
  | Candidate Action | Exact Eligibility Rule | Why Evaluated True | Policy Guard | Category |
  | :--- | :--- | :--- | :--- | :--- |
  | `GENERATE_EVIDENCE_REPORT` | `report_ready=True or vasp_boundary=True` | Both match | ALLOWED | **A** |
  | `CHECK_REVIEWED_VASP` | `vasp_boundary=True` | Boundary exists | ALLOWED | **C** (Already reviewed and verified) |
  | `REQUEST_HUMAN_REVIEW` | `True` | Fallback | ALLOWED | **B** |

---

## 4. Specific Deterministic Component Audits

### 4.1 STOP_COVERAGE_GAP Audit
- **Current Rule** (`eligibility.py:95`):
  ```python
  if key == InvestigationActionKey.STOP_COVERAGE_GAP.value:
      return bool(
          state.coverage_status in ("partial", "failed")
          or not state.request_budget_remaining
          or state.unresolved_branch_count > 0   # <-- DETERMINISTIC BUG
      )
  ```
- **Finding**: Inclusion of `state.unresolved_branch_count > 0` makes `STOP_COVERAGE_GAP` eligible whenever active branches exist to trace, even when `request_budget_remaining=True` and `coverage_status=complete_within_scope`. In Scenario 2 (`02_REVIEWED_VASP_REACHED`), where 23 non-critical candidate branches were unexpanded because a reviewed VASP was already reached, `STOP_COVERAGE_GAP` was erroneously marked eligible.
- **Root Cause**: `STOP_COVERAGE_GAP` must signify a *terminal impediment* to tracing. An unresolved branch with remaining budget is the primary precondition to *continue*, not to stop.

### 4.2 CHECK_REVIEWED_VASP Audit
- **Current Rule** (`eligibility.py:78`):
  ```python
  if key == InvestigationActionKey.CHECK_REVIEWED_VASP.value:
      return bool(
          state.network
          and (
              state.terminal_address is not None
              or state.has_supported_vasp_boundary
              or state.has_vasp_candidate
          )
      )
  ```
- **Finding**: Because almost every trace has a non-empty `terminal_address`, `CHECK_REVIEWED_VASP` evaluates to `True` in 10 out of 10 scenarios.
  - When `reviewed_service_control_available=True` (Scenarios 2 and 10), checking the registry is redundant because the anchor is already verified.
  - When a cross-chain transfer is in progress (Scenario 6), the source address is an intermediary bridge/pool contract, making local VASP lookup unhelpful.
- **Root Cause**: Semantics currently implement definition (B) ("Repeatedly check registry whenever any address exists") rather than definition (A) ("Perform initial lookup on an unverified terminal address").

### 4.3 GENERATE_EVIDENCE_REPORT Audit
- **Current Rule** (`eligibility.py:102`):
  ```python
  if key == InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value:
      return bool(
          state.report_ready
          or state.has_supported_vasp_boundary
          or state.hop_depth > 0
      )
  ```
- **Finding**: `hop_depth > 0` permits reporting at any step after the seed transaction. While useful for limitation-aware interim artifacts, in earlier hops (`hop_depth=1` or `2`) where branches are actively progressing, it dilutes the candidate set and draws CLM probability away from active continuation.

---

## 5. CLM Disagreement Taxonomy (7 Disagreements)

For the 7 scenarios where CLM did not agree with the curated Top-1 action:

| Scenario ID | Curated / Rule Action | CLM Preferred Action | Classification | Detailed Rationale |
| :--- | :--- | :--- | :---: | :--- |
| `01_SAME_CHAIN_CONTINUATION` | `CONTINUE_SAME_CHAIN` | `STOP_COVERAGE_GAP` | **TYPE A** | `STOP_COVERAGE_GAP` was admitted only because `unresolved_branch_count > 0` triggered the loose predicate, despite budget remaining. |
| `02_REVIEWED_VASP_REACHED` | `GENERATE_EVIDENCE_REPORT` | `STOP_COVERAGE_GAP` | **TYPE A** | `STOP_COVERAGE_GAP` should have been ineligible; anchor was reached and report was ready. |
| `04_PROVIDER_FAILURE_RETRYABLE` | `RETRY_PROVIDER` | `STOP_COVERAGE_GAP` | **TYPE B** | Both are valid when coverage is partial, but rules prioritize retrying provider while budget remains. |
| `06_CCTP_CONTINUATION_PENDING` | `FOLLOW_CROSS_CHAIN_LINK` | `CHECK_REVIEWED_VASP` | **TYPE C** | CLM description for VASP check ("Check whether target address is a reviewed VASP anchor") overwhelmed cross-chain link description in embedding cosine space. |
| `07_CCTP_DESTINATION_COMPLETED` | `GENERATE_EVIDENCE_REPORT` | `CHECK_REVIEWED_VASP` | **TYPE C** | State indicated destination was complete and report was ready, but CLM favored checking VASP anchors. |
| `09_AMBIGUOUS_ORDERING` | `REQUEST_HUMAN_REVIEW` | `CHECK_REVIEWED_VASP` | **TYPE C** | CLM failed to recognize `HUMAN_REVIEW_REQUIRED=true` as a strong prompt for `REQUEST_HUMAN_REVIEW`. |
| `10_REPORT_READY` | `GENERATE_EVIDENCE_REPORT` | `CHECK_REVIEWED_VASP` | **TYPE A** | `CHECK_REVIEWED_VASP` was eligible despite `reviewed_service_control_available=True` already being confirmed. |

### Counts by Disagreement Type
- **TYPE A** (Ineligible action admitted by loose eligibility rule): **3**
- **TYPE B** (Valid alternative with lower deterministic priority): **1**
- **TYPE C** (CLM semantic misunderstanding / embedding bias): **3**
- **TYPE D** (Omitted state fact): **0**
- **TYPE E** (Debatable curated label): **0**

---

## 6. State Sufficiency Findings

We verified the model-facing serialized state for each disagreement scenario:
- **`01_SAME_CHAIN_CONTINUATION`**: `REQUEST_BUDGET_REMAINING=true`, `UNRESOLVED_BRANCH_COUNT=4`, `COVERAGE_STATUS=partial`. The facts needed to rule out stopping were present in the state text, but the loose eligibility filter admitted `STOP_COVERAGE_GAP`.
- **`06_CCTP_CONTINUATION_PENDING`**: `CROSS_CHAIN_CONTINUATION_PENDING=true`, `CROSS_CHAIN_LINK_AVAILABLE=true`, `DESTINATION_NETWORK=base`, `DESTINATION_TRACE_COMPLETE=false`. All cross-chain indicators were explicitly serialized.
- **`09_AMBIGUOUS_ORDERING`**: `HUMAN_REVIEW_REQUIRED=true`. Explicitly present.

**Conclusion**: The state serialization is **semantically sufficient**. Disagreements stem from two distinct sources:
1. **Loose deterministic eligibility filters** admitting actions that should be contextually barred (Type A).
2. **Generic pre-trained CLM head biases** where generic anchor checking dominates over multi-token state reasoning (Type C).

---

## 7. Concrete Deterministic Bugs Identified

1. **`STOP_COVERAGE_GAP` Over-Eligibility**:
   - `or state.unresolved_branch_count > 0` in `ActionEligibilityFilter.is_eligible` causes active, healthy traces with remaining budget to treat stopping as eligible.
2. **`CHECK_REVIEWED_VASP` Redundancy**:
   - Evaluating `True` when `state.reviewed_service_control_available=True` causes redundant anchor lookup candidates after attribution is already established.

---

## 8. Recommendations for Task 08C-B

1. **Fix Deterministic Eligibility First**: Correct the predicates for `STOP_COVERAGE_GAP` and `CHECK_REVIEWED_VASP` without touching model weights or action descriptions. Re-filtering alone will eliminate 3 of the 7 disagreements (raising Top-1 agreement from 30% to ~50% mechanically).
2. **Calibrated Action Descriptions (`ACTION_CATALOG_VERSION=1.1.0`)**: Once eligibility is tightened, if further alignment is required, refine the action descriptions in a new catalog version to emphasize precedence conditions (e.g. cross-chain link following when pending, human review when flagged).
3. **Preserve Rules-Authoritative Invariant**: Regardless of CLM calibration, `DeterministicRuleRouter` must remain authoritative for all real money/investigation operations, maintaining the 0.0% unsafe execution guarantee.
