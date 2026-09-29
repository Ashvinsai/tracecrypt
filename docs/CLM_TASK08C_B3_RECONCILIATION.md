# Task 08C-B3 — Experiment Provenance and Reconciliation Audit

**Artifact Class**: `DERIVED_COMPARISON`  
**Notice**: `DECISION SUPPORT METADATA - NOT BLOCKCHAIN EVIDENCE`  

---

## 1. Commit Identity & Tree Resolution
- **Authoritative Crypto-Attribution Commit**: `86db954bc4f855fc431c6808afee5b3cef1fd3e3`
  - *Tree SHA*: `f4bc9ea325603e877e68fa7558ec188d3e9112ae`
  - *Note*: An earlier turn transcript contained an erroneous string suffix (`86db9546059d99d3e8e25d9715fc4b490fba9a1a`). Git log and bundle verification confirm that commit `86db954bc4f855fc431c6808afee5b3cef1fd3e3` is the sole, authoritative commit containing the Task 08C-B2 deterministic repair.
- **Authoritative CLM Commit**: `bb42c6c5bf914fd449bed2f6ca65be80602cb1f7`

---

## 2. Reconciled Baseline Findings (Scenario 04)
- In the frozen Task 08B baseline (`var/routing-validation/20260927-clm-qwen3-8b-shadow-001/scenario-results.json` and raw response `04_PROVIDER_FAILURE_RETRYABLE_systemone.json`):
  - **CLM Choice**: `STOP_COVERAGE_GAP` (64.45% probability)
  - Prior prose descriptions claiming `REQUEST_HUMAN_REVIEW` were transcription errors from manual tests. All 10 Task 08B scenarios match their raw System One JSON payloads to $<10^{-6}$ error.

---

## 3. Comparison Metrics across Stages

Generated programmatically by `scripts/compare_routing_validation_runs.py` and saved to `var/routing-validation/comparisons/task08b-vs-08cb-vs-08cb2.json`:

| Scenario ID | Curated / Rule Action | 08B Baseline CLM Choice | 08C-B Interim CLM Choice | 08C-B2 Final CLM Choice |
| :--- | :--- | :---: | :---: | :---: |
| `01_SAME_CHAIN_CONTINUATION` | `CONTINUE_SAME_CHAIN` | `STOP_COVERAGE_GAP` (❌) | `CHECK_REVIEWED_VASP` (❌) | `REQUEST_HUMAN_REVIEW` (❌) |
| `02_REVIEWED_VASP_REACHED` | `GENERATE_EVIDENCE_REPORT` | `STOP_COVERAGE_GAP` (❌) | `GENERATE_EVIDENCE_REPORT` (✅) | `GENERATE_EVIDENCE_REPORT` (✅) |
| `03_VASP_CANDIDATE_ONLY` | `REVIEW_VASP_CANDIDATE` | `REVIEW_VASP_CANDIDATE` (✅) | `REVIEW_VASP_CANDIDATE` (✅) | `REVIEW_VASP_CANDIDATE` (✅) |
| `04_PROVIDER_FAILURE_RETRYABLE` | `RETRY_PROVIDER` | `STOP_COVERAGE_GAP` (❌) | `CHECK_REVIEWED_VASP` (❌) | `RETRY_PROVIDER` (✅) |
| `05_PROVIDER_FAILURE_EXHAUSTED` | `STOP_COVERAGE_GAP` | `STOP_COVERAGE_GAP` (✅) | `STOP_COVERAGE_GAP` (✅) | `STOP_COVERAGE_GAP` (✅) |
| `06_CCTP_CONTINUATION_PENDING` | `FOLLOW_CROSS_CHAIN_LINK` | `CHECK_REVIEWED_VASP` (❌) | `GENERATE_EVIDENCE_REPORT` (❌) | `GENERATE_EVIDENCE_REPORT` (❌) |
| `07_CCTP_DESTINATION_ALREADY_COMPLETED` | `GENERATE_EVIDENCE_REPORT` | `CHECK_REVIEWED_VASP` (❌) | `CHECK_REVIEWED_VASP` (❌) | `GENERATE_EVIDENCE_REPORT` (✅) |
| `08_RECEIPT_UNVERIFIED` | `VERIFY_EXECUTION_RECEIPT` | `VERIFY_EXECUTION_RECEIPT` (✅) | `VERIFY_EXECUTION_RECEIPT` (✅) | `VERIFY_EXECUTION_RECEIPT` (✅) |
| `09_AMBIGUOUS_ORDERING` | `REQUEST_HUMAN_REVIEW` | `CHECK_REVIEWED_VASP` (❌) | `CHECK_REVIEWED_VASP` (❌) | `REQUEST_HUMAN_REVIEW` (✅) |
| `10_REPORT_READY` | `GENERATE_EVIDENCE_REPORT` | `CHECK_REVIEWED_VASP` (❌) | `REQUEST_HUMAN_REVIEW` (❌) | `REQUEST_HUMAN_REVIEW` (❌) |

### Aggregates
- **Task 08B**: 3 / 10 strict Top-1 agreement, 10 / 10 Top-3 coverage
- **Task 08C-B**: 4 / 10 strict Top-1 agreement, 10 / 10 Top-3 coverage
- **Task 08C-B2**: 7 / 10 strict Top-1 agreement, 10 / 10 Top-3 coverage
- **Unsafe Execution Rate**: 0.0% across all runs.
