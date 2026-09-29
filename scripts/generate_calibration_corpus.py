"""Calibration corpus generator for Task 08C-C2.

Generates 40 realistic, semantically consistent InvestigationState scenarios
split 20/20 into DEVELOPMENT and HELD-OUT sets by scenario family.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add api directory to sys.path
API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from typing import Any

from app.models.investigation_routing import InvestigationActionKey, ServiceLookupStatus


def build_corpus() -> dict[str, list[dict[str, Any]]]:
    dev_set: list[dict[str, Any]] = []
    held_out_set: list[dict[str, Any]] = []

    # Helper base
    def base(net="ethereum", asset="USDT"):
        return {
            "network": net,
            "asset_symbol": asset,
            "asset_contract": None,
            "terminal_address": None,
            "hop_depth": 1,
            "branch_count": 2,
            "unresolved_branch_count": 0,
            "has_supported_vasp_boundary": False,
            "has_vasp_candidate": False,
            "has_bridge_boundary": False,
            "reviewed_service_control_available": False,
            "receipt_verified": True,
            "finality_state": "confirmed",
            "request_budget_remaining": True,
            "provider_error_class": "none",
            "coverage_status": "complete_within_scope",
            "cross_chain_link_available": False,
            "cross_chain_continuation_pending": False,
            "cross_chain_protocol": None,
            "cross_chain_status": None,
            "destination_network": None,
            "destination_network_known": False,
            "destination_execution_verified": False,
            "destination_trace_started": False,
            "destination_trace_complete": False,
            "candidate_only": False,
            "no_attribution_evidence": True,
            "human_review_required": False,
            "report_ready": False,
            "service_lookup_status": ServiceLookupStatus.no_match.value,
        }

    # =========================================================================
    # FAMILY 1: Same-Chain Continuation (Active Frontier)
    # Dev: Ethereum USDT, Tron USDT (hop 2-3)
    # Held-out: BSC USDT, Base USDC, Ethereum USDC (hop 1-4)
    # =========================================================================
    dev_set.append({
        "scenario_id": "DEV_01_SAME_CHAIN_ETH_USDT",
        "family": "SAME_CHAIN_CONTINUATION",
        "state": {
            **base("ethereum", "USDT"),
            "hop_depth": 2,
            "branch_count": 8,
            "unresolved_branch_count": 3,
            "coverage_status": "partial",
        },
        "preferred_action": InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
        "acceptable_actions": [InvestigationActionKey.CONTINUE_SAME_CHAIN.value],
        "justification": "Active unresolved branches remain on Ethereum with budget available.",
    })
    dev_set.append({
        "scenario_id": "DEV_02_SAME_CHAIN_TRON_USDT",
        "family": "SAME_CHAIN_CONTINUATION",
        "state": {
            **base("tron", "USDT"),
            "hop_depth": 3,
            "branch_count": 12,
            "unresolved_branch_count": 2,
            "coverage_status": "partial",
        },
        "preferred_action": InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
        "acceptable_actions": [InvestigationActionKey.CONTINUE_SAME_CHAIN.value],
        "justification": "Active unresolved branches remain on TRON with budget available.",
    })

    held_out_set.append({
        "scenario_id": "HELD_01_SAME_CHAIN_BSC_USDT",
        "family": "SAME_CHAIN_CONTINUATION",
        "state": {
            **base("bsc", "USDT"),
            "hop_depth": 1,
            "branch_count": 4,
            "unresolved_branch_count": 1,
            "coverage_status": "partial",
        },
        "preferred_action": InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
        "acceptable_actions": [InvestigationActionKey.CONTINUE_SAME_CHAIN.value],
        "justification": "Active unresolved branch on BSC with healthy budget.",
    })
    held_out_set.append({
        "scenario_id": "HELD_02_SAME_CHAIN_BASE_USDC",
        "family": "SAME_CHAIN_CONTINUATION",
        "state": {
            **base("base", "USDC"),
            "hop_depth": 4,
            "branch_count": 16,
            "unresolved_branch_count": 5,
            "coverage_status": "partial",
        },
        "preferred_action": InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
        "acceptable_actions": [InvestigationActionKey.CONTINUE_SAME_CHAIN.value],
        "justification": "Deep multi-branch continuation on Base.",
    })
    held_out_set.append({
        "scenario_id": "HELD_03_SAME_CHAIN_ETH_USDC",
        "family": "SAME_CHAIN_CONTINUATION",
        "state": {
            **base("ethereum", "USDC"),
            "hop_depth": 2,
            "branch_count": 6,
            "unresolved_branch_count": 2,
            "coverage_status": "partial",
        },
        "preferred_action": InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
        "acceptable_actions": [InvestigationActionKey.CONTINUE_SAME_CHAIN.value],
        "justification": "EVM USDC active frontier exploration.",
    })

    # =========================================================================
    # FAMILY 2: Cross-Chain Continuation (CCTP / Relay Verified, Destination Pending)
    # Dev: Ethereum -> Base (hop 1, hop 2)
    # Held-out: Base -> Ethereum, Ethereum -> Arbitrum (synthetic), Polygon -> Ethereum
    # =========================================================================
    dev_set.append({
        "scenario_id": "DEV_03_CCTP_ETH_TO_BASE_PENDING",
        "family": "CROSS_CHAIN_CONTINUATION",
        "state": {
            **base("ethereum", "USDC"),
            "cross_chain_link_available": True,
            "cross_chain_continuation_pending": True,
            "cross_chain_protocol": "circle_cctp_v2",
            "cross_chain_status": "COMPLETE",
            "destination_network": "base",
            "destination_network_known": True,
            "destination_execution_verified": True,
            "destination_trace_started": False,
            "destination_trace_complete": False,
        },
        "preferred_action": InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
        "acceptable_actions": [InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value],
        "justification": "CCTP hop verified on Ethereum, destination Base trace pending.",
    })
    dev_set.append({
        "scenario_id": "DEV_04_CCTP_ETH_TO_BASE_STARTED_NOT_DONE",
        "family": "CROSS_CHAIN_CONTINUATION",
        "state": {
            **base("ethereum", "USDC"),
            "cross_chain_link_available": True,
            "cross_chain_continuation_pending": True,
            "cross_chain_protocol": "circle_cctp_v2",
            "cross_chain_status": "COMPLETE",
            "destination_network": "base",
            "destination_network_known": True,
            "destination_execution_verified": True,
            "destination_trace_started": True,
            "destination_trace_complete": False,
        },
        "preferred_action": InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
        "acceptable_actions": [InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value],
        "justification": "Destination trace started but incomplete on Base.",
    })

    held_out_set.append({
        "scenario_id": "HELD_04_CCTP_BASE_TO_ETH_PENDING",
        "family": "CROSS_CHAIN_CONTINUATION",
        "state": {
            **base("base", "USDC"),
            "cross_chain_link_available": True,
            "cross_chain_continuation_pending": True,
            "cross_chain_protocol": "circle_cctp_v2",
            "cross_chain_status": "COMPLETE",
            "destination_network": "ethereum",
            "destination_network_known": True,
            "destination_execution_verified": True,
            "destination_trace_started": False,
            "destination_trace_complete": False,
        },
        "preferred_action": InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
        "acceptable_actions": [InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value],
        "justification": "Reverse CCTP link from Base to Ethereum pending continuation.",
    })
    held_out_set.append({
        "scenario_id": "HELD_05_CCTP_ETH_TO_ARB_PENDING",
        "family": "CROSS_CHAIN_CONTINUATION",
        "state": {
            **base("ethereum", "USDC"),
            "cross_chain_link_available": True,
            "cross_chain_continuation_pending": True,
            "cross_chain_protocol": "circle_cctp_v2",
            "cross_chain_status": "COMPLETE",
            "destination_network": "arbitrum",
            "destination_network_known": True,
            "destination_execution_verified": True,
            "destination_trace_started": False,
            "destination_trace_complete": False,
        },
        "preferred_action": InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
        "acceptable_actions": [InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value],
        "justification": "CCTP hop from Ethereum to Arbitrum destination.",
    })

    # =========================================================================
    # FAMILY 3: VASP Candidate Review (Unreviewed Candidate Anchor)
    # Dev: TRON USDT candidate, Ethereum USDT candidate
    # Held-out: BSC USDT candidate, Base USDC candidate
    # =========================================================================
    dev_set.append({
        "scenario_id": "DEV_05_VASP_CANDIDATE_TRON",
        "family": "VASP_CANDIDATE_REVIEW",
        "state": {
            **base("tron", "USDT"),
            "has_vasp_candidate": True,
            "candidate_only": True,
            "human_review_required": True,
            "service_lookup_status": ServiceLookupStatus.no_match.value,
        },
        "preferred_action": InvestigationActionKey.REVIEW_VASP_CANDIDATE.value,
        "acceptable_actions": [InvestigationActionKey.REVIEW_VASP_CANDIDATE.value],
        "justification": "Unreviewed TRON deposit candidate requires candidate review.",
    })
    dev_set.append({
        "scenario_id": "DEV_06_VASP_CANDIDATE_ETH",
        "family": "VASP_CANDIDATE_REVIEW",
        "state": {
            **base("ethereum", "USDT"),
            "has_vasp_candidate": True,
            "candidate_only": True,
            "human_review_required": True,
            "service_lookup_status": ServiceLookupStatus.no_match.value,
        },
        "preferred_action": InvestigationActionKey.REVIEW_VASP_CANDIDATE.value,
        "acceptable_actions": [InvestigationActionKey.REVIEW_VASP_CANDIDATE.value],
        "justification": "Unreviewed Ethereum deposit candidate requires candidate review.",
    })

    held_out_set.append({
        "scenario_id": "HELD_06_VASP_CANDIDATE_BSC",
        "family": "VASP_CANDIDATE_REVIEW",
        "state": {
            **base("bsc", "USDT"),
            "has_vasp_candidate": True,
            "candidate_only": True,
            "human_review_required": True,
            "service_lookup_status": ServiceLookupStatus.no_match.value,
        },
        "preferred_action": InvestigationActionKey.REVIEW_VASP_CANDIDATE.value,
        "acceptable_actions": [InvestigationActionKey.REVIEW_VASP_CANDIDATE.value],
        "justification": "BSC deposit candidate requires analyst review.",
    })
    held_out_set.append({
        "scenario_id": "HELD_07_VASP_CANDIDATE_BASE",
        "family": "VASP_CANDIDATE_REVIEW",
        "state": {
            **base("base", "USDC"),
            "has_vasp_candidate": True,
            "candidate_only": True,
            "human_review_required": True,
            "service_lookup_status": ServiceLookupStatus.no_match.value,
        },
        "preferred_action": InvestigationActionKey.REVIEW_VASP_CANDIDATE.value,
        "acceptable_actions": [InvestigationActionKey.REVIEW_VASP_CANDIDATE.value],
        "justification": "Base USDC deposit candidate requires review.",
    })

    # =========================================================================
    # FAMILY 4: Reviewed VASP / Report Ready / Completed Investigation
    # Dev: TRON OKX boundary, Ethereum Binance boundary
    # Held-out: Base Coinbase boundary, CCTP destination completed, Multi-hop report ready
    # =========================================================================
    dev_set.append({
        "scenario_id": "DEV_07_REVIEWED_VASP_TRON",
        "family": "REPORT_READY_VASP",
        "state": {
            **base("tron", "USDT"),
            "has_supported_vasp_boundary": True,
            "reviewed_service_control_available": True,
            "report_ready": True,
            "no_attribution_evidence": False,
            "service_lookup_status": ServiceLookupStatus.match_found.value,
        },
        "preferred_action": InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
        "acceptable_actions": [
            InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        ],
        "justification": "Terminal verified service boundary reached on TRON.",
    })
    dev_set.append({
        "scenario_id": "DEV_08_REVIEWED_VASP_ETH",
        "family": "REPORT_READY_VASP",
        "state": {
            **base("ethereum", "USDC"),
            "has_supported_vasp_boundary": True,
            "reviewed_service_control_available": True,
            "report_ready": True,
            "no_attribution_evidence": False,
            "service_lookup_status": ServiceLookupStatus.match_found.value,
        },
        "preferred_action": InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
        "acceptable_actions": [
            InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        ],
        "justification": "Terminal verified service boundary reached on Ethereum.",
    })

    held_out_set.append({
        "scenario_id": "HELD_08_REVIEWED_VASP_BASE",
        "family": "REPORT_READY_VASP",
        "state": {
            **base("base", "USDC"),
            "has_supported_vasp_boundary": True,
            "reviewed_service_control_available": True,
            "report_ready": True,
            "no_attribution_evidence": False,
            "service_lookup_status": ServiceLookupStatus.match_found.value,
        },
        "preferred_action": InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
        "acceptable_actions": [
            InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        ],
        "justification": "Terminal verified service boundary reached on Base.",
    })
    held_out_set.append({
        "scenario_id": "HELD_09_CCTP_DESTINATION_FINISHED",
        "family": "REPORT_READY_VASP",
        "state": {
            **base("ethereum", "USDC"),
            "cross_chain_link_available": True,
            "cross_chain_continuation_pending": False,
            "cross_chain_protocol": "circle_cctp_v2",
            "cross_chain_status": "COMPLETE",
            "destination_network": "base",
            "destination_network_known": True,
            "destination_execution_verified": True,
            "destination_trace_started": True,
            "destination_trace_complete": True,
            "report_ready": True,
        },
        "preferred_action": InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
        "acceptable_actions": [
            InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        ],
        "justification": "Full CCTP destination trace finished; report generation ready.",
    })
    held_out_set.append({
        "scenario_id": "HELD_10_TERMINAL_REPORT_MULTI_HOP",
        "family": "REPORT_READY_VASP",
        "state": {
            **base("tron", "USDT"),
            "hop_depth": 5,
            "branch_count": 10,
            "unresolved_branch_count": 0,
            "has_supported_vasp_boundary": True,
            "reviewed_service_control_available": True,
            "report_ready": True,
            "service_lookup_status": ServiceLookupStatus.match_found.value,
        },
        "preferred_action": InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
        "acceptable_actions": [
            InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        ],
        "justification": "All branches closed at verified VASP boundary after 5 hops.",
    })

    # =========================================================================
    # FAMILY 5: Provider Retry (Transient Rate-limit / Timeout with Budget)
    # Dev: Rate-limited TRON, Timeout Ethereum
    # Held-out: Provider error BSC, Rate-limited Base
    # =========================================================================
    dev_set.append({
        "scenario_id": "DEV_09_RETRY_RATE_LIMIT_TRON",
        "family": "PROVIDER_RETRY",
        "state": {
            **base("tron", "USDT"),
            "provider_error_class": "rate_limited",
            "coverage_status": "partial",
            "request_budget_remaining": True,
        },
        "preferred_action": InvestigationActionKey.RETRY_PROVIDER.value,
        "acceptable_actions": [InvestigationActionKey.RETRY_PROVIDER.value],
        "justification": "Rate limited with budget remaining on TRON.",
    })
    dev_set.append({
        "scenario_id": "DEV_10_RETRY_TIMEOUT_ETH",
        "family": "PROVIDER_RETRY",
        "state": {
            **base("ethereum", "USDT"),
            "provider_error_class": "timeout",
            "coverage_status": "partial",
            "request_budget_remaining": True,
        },
        "preferred_action": InvestigationActionKey.RETRY_PROVIDER.value,
        "acceptable_actions": [InvestigationActionKey.RETRY_PROVIDER.value],
        "justification": "Gateway timeout with budget remaining on Ethereum.",
    })

    held_out_set.append({
        "scenario_id": "HELD_11_RETRY_PROVIDER_ERROR_BSC",
        "family": "PROVIDER_RETRY",
        "state": {
            **base("bsc", "USDT"),
            "provider_error_class": "provider_error",
            "coverage_status": "partial",
            "request_budget_remaining": True,
        },
        "preferred_action": InvestigationActionKey.RETRY_PROVIDER.value,
        "acceptable_actions": [InvestigationActionKey.RETRY_PROVIDER.value],
        "justification": "Retryable upstream provider error on BSC.",
    })
    held_out_set.append({
        "scenario_id": "HELD_12_RETRY_RATE_LIMIT_BASE",
        "family": "PROVIDER_RETRY",
        "state": {
            **base("base", "USDC"),
            "provider_error_class": "rate_limited",
            "coverage_status": "partial",
            "request_budget_remaining": True,
        },
        "preferred_action": InvestigationActionKey.RETRY_PROVIDER.value,
        "acceptable_actions": [InvestigationActionKey.RETRY_PROVIDER.value],
        "justification": "Rate limit with remaining budget on Base.",
    })

    # =========================================================================
    # FAMILY 6: Coverage Stop (Budget Exhausted / Failed Coverage)
    # Dev: Budget exhausted partial, Failed coverage timeout
    # Held-out: Budget exhausted multi-branch, Fatal provider failure
    # =========================================================================
    dev_set.append({
        "scenario_id": "DEV_11_STOP_BUDGET_EXHAUSTED",
        "family": "COVERAGE_STOP",
        "state": {
            **base("ethereum", "USDT"),
            "request_budget_remaining": False,
            "coverage_status": "partial",
            "unresolved_branch_count": 3,
        },
        "preferred_action": InvestigationActionKey.STOP_COVERAGE_GAP.value,
        "acceptable_actions": [InvestigationActionKey.STOP_COVERAGE_GAP.value],
        "justification": "Request budget exhausted during partial trace on Ethereum.",
    })
    dev_set.append({
        "scenario_id": "DEV_12_STOP_FAILED_COVERAGE",
        "family": "COVERAGE_STOP",
        "state": {
            **base("tron", "USDT"),
            "request_budget_remaining": False,
            "coverage_status": "failed",
            "provider_error_class": "timeout",
        },
        "preferred_action": InvestigationActionKey.STOP_COVERAGE_GAP.value,
        "acceptable_actions": [InvestigationActionKey.STOP_COVERAGE_GAP.value],
        "justification": "Explicitly failed coverage with exhausted budget.",
    })

    held_out_set.append({
        "scenario_id": "HELD_13_STOP_EXHAUSTED_BSC",
        "family": "COVERAGE_STOP",
        "state": {
            **base("bsc", "USDT"),
            "request_budget_remaining": False,
            "coverage_status": "partial",
            "unresolved_branch_count": 4,
        },
        "preferred_action": InvestigationActionKey.STOP_COVERAGE_GAP.value,
        "acceptable_actions": [InvestigationActionKey.STOP_COVERAGE_GAP.value],
        "justification": "Budget exhausted on BSC with unresolved branches.",
    })
    held_out_set.append({
        "scenario_id": "HELD_14_STOP_FATAL_FAILURE_BASE",
        "family": "COVERAGE_STOP",
        "state": {
            **base("base", "USDC"),
            "request_budget_remaining": False,
            "coverage_status": "failed",
            "provider_error_class": "provider_error",
        },
        "preferred_action": InvestigationActionKey.STOP_COVERAGE_GAP.value,
        "acceptable_actions": [InvestigationActionKey.STOP_COVERAGE_GAP.value],
        "justification": "Fatal provider failure with exhausted budget on Base.",
    })

    # =========================================================================
    # FAMILY 7: Receipt Verification (Unverified Execution / Finality Unknown)
    # Dev: BSC unverified seed, Ethereum unverified hop
    # Held-out: TRON unverified transfer, Base unconfirmed receipt
    # =========================================================================
    dev_set.append({
        "scenario_id": "DEV_13_RECEIPT_UNVERIFIED_BSC",
        "family": "RECEIPT_VERIFICATION",
        "state": {
            **base("bsc", "USDT"),
            "receipt_verified": False,
            "finality_state": "unknown",
            "service_lookup_status": ServiceLookupStatus.not_checked.value,
        },
        "preferred_action": InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value,
        "acceptable_actions": [InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value],
        "justification": "Initial transfer receipt not yet verified on BSC.",
    })
    dev_set.append({
        "scenario_id": "DEV_14_RECEIPT_UNVERIFIED_ETH",
        "family": "RECEIPT_VERIFICATION",
        "state": {
            **base("ethereum", "USDC"),
            "receipt_verified": False,
            "finality_state": "pending",
            "service_lookup_status": ServiceLookupStatus.not_checked.value,
        },
        "preferred_action": InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value,
        "acceptable_actions": [InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value],
        "justification": "Pending transfer receipt on Ethereum requires verification.",
    })

    held_out_set.append({
        "scenario_id": "HELD_15_RECEIPT_UNVERIFIED_TRON",
        "family": "RECEIPT_VERIFICATION",
        "state": {
            **base("tron", "USDT"),
            "receipt_verified": False,
            "finality_state": "unknown",
            "service_lookup_status": ServiceLookupStatus.not_checked.value,
        },
        "preferred_action": InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value,
        "acceptable_actions": [InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value],
        "justification": "Unverified transaction execution receipt on TRON.",
    })
    held_out_set.append({
        "scenario_id": "HELD_16_RECEIPT_UNCONFIRMED_BASE",
        "family": "RECEIPT_VERIFICATION",
        "state": {
            **base("base", "USDC"),
            "receipt_verified": False,
            "finality_state": "unconfirmed",
            "service_lookup_status": ServiceLookupStatus.not_checked.value,
        },
        "preferred_action": InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value,
        "acceptable_actions": [InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value],
        "justification": "Unconfirmed block receipt on Base requires execution verification.",
    })

    # =========================================================================
    # FAMILY 8: Human Review (Ambiguous Ordering / Anomaly Review)
    # Dev: Ambiguous ordering Ethereum, Multi-candidate conflict TRON
    # Held-out: Ambiguous ordering BSC, Human review flag set Base
    # =========================================================================
    dev_set.append({
        "scenario_id": "DEV_15_HUMAN_REVIEW_ORDERING_ETH",
        "family": "HUMAN_REVIEW",
        "state": {
            **base("ethereum", "USDT"),
            "human_review_required": True,
            "coverage_status": "complete_within_scope",
            "unresolved_branch_count": 0,
            "report_ready": False,
        },
        "preferred_action": InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        "acceptable_actions": [InvestigationActionKey.REQUEST_HUMAN_REVIEW.value],
        "justification": "Ambiguous event ordering requires investigator review on Ethereum.",
    })
    dev_set.append({
        "scenario_id": "DEV_16_HUMAN_REVIEW_CONFLICT_TRON",
        "family": "HUMAN_REVIEW",
        "state": {
            **base("tron", "USDT"),
            "human_review_required": True,
            "has_vasp_candidate": False,
            "unresolved_branch_count": 0,
            "report_ready": False,
        },
        "preferred_action": InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        "acceptable_actions": [InvestigationActionKey.REQUEST_HUMAN_REVIEW.value],
        "justification": "Complex attribution anomaly flagged for human review.",
    })

    held_out_set.append({
        "scenario_id": "HELD_17_HUMAN_REVIEW_ORDERING_BSC",
        "family": "HUMAN_REVIEW",
        "state": {
            **base("bsc", "USDT"),
            "human_review_required": True,
            "coverage_status": "complete_within_scope",
            "unresolved_branch_count": 0,
            "report_ready": False,
        },
        "preferred_action": InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        "acceptable_actions": [InvestigationActionKey.REQUEST_HUMAN_REVIEW.value],
        "justification": "Ambiguous deposit timeline on BSC requires human review.",
    })
    held_out_set.append({
        "scenario_id": "HELD_18_HUMAN_REVIEW_ANOMALY_BASE",
        "family": "HUMAN_REVIEW",
        "state": {
            **base("base", "USDC"),
            "human_review_required": True,
            "unresolved_branch_count": 0,
            "report_ready": False,
        },
        "preferred_action": InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        "acceptable_actions": [InvestigationActionKey.REQUEST_HUMAN_REVIEW.value],
        "justification": "Flagged behavioral anomaly requires human analyst review.",
    })

    # =========================================================================
    # FAMILY 9: Additional Continuation & Reporting variants to reach exactly 20/20
    # =========================================================================
    # Dev: 4 more scenarios (Same-chain, cross-chain, report ready, provider retry)
    dev_set.append({
        "scenario_id": "DEV_17_SAME_CHAIN_TRON_DEEP",
        "family": "SAME_CHAIN_CONTINUATION",
        "state": {
            **base("tron", "USDT"),
            "hop_depth": 4,
            "branch_count": 15,
            "unresolved_branch_count": 3,
            "coverage_status": "partial",
        },
        "preferred_action": InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
        "acceptable_actions": [InvestigationActionKey.CONTINUE_SAME_CHAIN.value],
        "justification": "Deep TRON hopping continuation.",
    })
    dev_set.append({
        "scenario_id": "DEV_18_CROSS_CHAIN_CCTP_PARALLEL",
        "family": "CROSS_CHAIN_CONTINUATION",
        "state": {
            **base("ethereum", "USDC"),
            "cross_chain_link_available": True,
            "cross_chain_continuation_pending": True,
            "cross_chain_protocol": "circle_cctp_v2",
            "cross_chain_status": "COMPLETE",
            "destination_network": "base",
            "destination_network_known": True,
            "destination_execution_verified": True,
            "destination_trace_started": False,
            "destination_trace_complete": False,
            "branch_count": 3,
            "unresolved_branch_count": 0,
        },
        "preferred_action": InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
        "acceptable_actions": [InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value],
        "justification": "Closed source branches; verified cross-chain continuation pending.",
    })
    dev_set.append({
        "scenario_id": "DEV_19_REPORT_READY_CLEAN_CLOSE",
        "family": "REPORT_READY_VASP",
        "state": {
            **base("ethereum", "USDT"),
            "hop_depth": 2,
            "branch_count": 1,
            "unresolved_branch_count": 0,
            "has_supported_vasp_boundary": True,
            "reviewed_service_control_available": True,
            "report_ready": True,
            "service_lookup_status": ServiceLookupStatus.match_found.value,
        },
        "preferred_action": InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
        "acceptable_actions": [
            InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        ],
        "justification": "Clean 1-branch closure into verified service on Ethereum.",
    })
    dev_set.append({
        "scenario_id": "DEV_20_PROVIDER_RETRY_TRANSIENT_503",
        "family": "PROVIDER_RETRY",
        "state": {
            **base("ethereum", "USDC"),
            "provider_error_class": "provider_error",
            "coverage_status": "partial",
            "request_budget_remaining": True,
        },
        "preferred_action": InvestigationActionKey.RETRY_PROVIDER.value,
        "acceptable_actions": [InvestigationActionKey.RETRY_PROVIDER.value],
        "justification": "Transient provider error with ample budget remaining.",
    })

    # Held-out: 2 more scenarios to reach exactly 20
    held_out_set.append({
        "scenario_id": "HELD_19_SAME_CHAIN_BASE_FRESH",
        "family": "SAME_CHAIN_CONTINUATION",
        "state": {
            **base("base", "USDC"),
            "hop_depth": 1,
            "branch_count": 2,
            "unresolved_branch_count": 1,
            "coverage_status": "partial",
        },
        "preferred_action": InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
        "acceptable_actions": [InvestigationActionKey.CONTINUE_SAME_CHAIN.value],
        "justification": "Fresh 1-hop continuation on Base.",
    })
    held_out_set.append({
        "scenario_id": "HELD_20_REPORT_READY_BSC_VASP",
        "family": "REPORT_READY_VASP",
        "state": {
            **base("bsc", "USDT"),
            "hop_depth": 2,
            "branch_count": 3,
            "unresolved_branch_count": 0,
            "has_supported_vasp_boundary": True,
            "reviewed_service_control_available": True,
            "report_ready": True,
            "service_lookup_status": ServiceLookupStatus.match_found.value,
        },
        "preferred_action": InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
        "acceptable_actions": [
            InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        ],
        "justification": "Verified VASP reached on BSC.",
    })

    return {
        "development_set": dev_set,
        "held_out_set": held_out_set,
    }


if __name__ == "__main__":
    corpus = build_corpus()
    out_dir = Path("/home/ash/Work/crypto-attribution/var/routing-calibration")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "routing_calibration_corpus_40.json"
    out_file.write_text(json.dumps(corpus, indent=2), encoding="utf-8")
    print(f"Generated {len(corpus['development_set'])} dev and {len(corpus['held_out_set'])} held-out scenarios -> {out_file}")
