# Task 08B — Real CLM Shadow Validation Report

## 1. Verified Environment & Models
- **Repository Commit**: `bb0060df067cb4b2daed94274391c0f102898239`
- **CLM Commit**: `bb42c6c5bf914fd449bed2f6ca65be80602cb1f7`
- **Qwen Backbone**: `Qwen/Qwen3-8B` (vLLM 0.19.1 pooling runner, -tp 2, FP16)
- **CLM Model Identifier**: `clm-latest` (configured: `clm-latest`)
- **PyTorch**: `2.10.0+cu128` (CUDA 12.8)
- **GPUs**: Dual NVIDIA Tesla T4 (Compute Capability 7.5)

## 2. Benchmark Aggregates (10 Production Scenarios)
- **Scenario Count**: 10
- **CLM Top-1 Agreement with Curated Action**: 3/10 (30.0%)
- **CLM Top-3 Coverage of Curated Action**: 8/10 (80.0%)
- **Rules vs CLM Top-1 Agreement**: 3/10 (30.0%)
- **Shadow Success Rate**: 10/10 (100%)
- **Unsafe-Action Execution Rate**: **0.0%** (Strict invariant preserved)
- **Guard Rejection Count**: 0

## 3. Operational & Warm Latencies
- **vLLM Startup Duration**: 240.11 s
- **First Embedding JIT Duration**: 72.09 s
- **Warm CLM Median Latency**: 76.03 ms (p95: 80.52 ms)
- **Warm Total Routing Median Latency**: 198.94 ms (p95: 449.93 ms)

## 4. Key Findings
- **Production Pipeline Integrity**: In all 10 scenarios, `actual_selected_action` was 100% determined by deterministic rules and authorized by `ActionPolicyGuard`. CLM ran in true read-only shadow mode.
- **Cross-Chain Filter Impact**: When candidate sets are unfiltered, CLM prefers `CONTINUE_SAME_CHAIN`. In the production pipeline, `ActionEligibilityFilter` strictly prunes `CONTINUE_SAME_CHAIN` on pending cross-chain links, steering decisions safely to `FOLLOW_CROSS_CHAIN_LINK`.
- **Fault Tolerance**: In controlled CLM network/timeout failure, routing falls back instantly to deterministic rules with zero downtime.
- **Adversarial Hardening**: Direct injection of forbidden actions (`FREEZE_FUNDS_AUTOMATICALLY`, `DECLARE_VASP_OWNERSHIP`) is 100% rejected by `ActionPolicyGuard`.
