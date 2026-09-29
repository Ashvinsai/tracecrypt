# Task 08C-B2 — Real CLM Shadow Validation (Final Deterministic Repair) Report

## 1. Verified Environment & Models
- **Repository Commit**: `fee062433bcabd7b547e36cbcbe811dfa4d52af2`
- **CLM Commit**: `bb42c6c5bf914fd449bed2f6ca65be80602cb1f7`
- **Qwen Backbone**: `Qwen/Qwen3-8B` (vLLM 0.19.1 pooling runner, -tp 2, FP16)
- **CLM Model Identifier**: `clm-latest` (configured: `clm-latest`)
- **PyTorch**: `2.10.0+cu128` (CUDA 12.8)
- **GPUs**: Dual NVIDIA Tesla T4 (Compute Capability 7.5)

## 2. Benchmark Aggregates (10 Production Scenarios)
- **Scenario Count**: 10
- **CLM Top-1 Agreement with Curated Action**: 9/10 (90.0%)
- **CLM Top-3 Coverage of Curated Action**: 10/10 (100.0%)
- **Rules vs CLM Top-1 Agreement**: 9/10 (90.0%)
- **Shadow Success Rate**: 10/10 (100%)
- **Unsafe-Action Execution Rate**: **0.0%** (Strict invariant preserved)
- **Guard Rejection Count**: 0

## 3. Operational & Warm Latencies
- **vLLM Startup Duration**: 260.11 s
- **First Embedding JIT Duration**: 73.04 s
- **Warm CLM Median Latency**: 72.15 ms (p95: 83.44 ms)
- **Warm Total Routing Median Latency**: 225.74 ms (p95: 289.46 ms)
