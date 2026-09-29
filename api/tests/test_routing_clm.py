"""Tests for official /v1/systemone ClmRouter HTTP client and response validation (Task 08)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.models.investigation_routing import InvestigationActionKey, InvestigationState
from app.services.routing.clm_client import ClmRouter, ClmRoutingError


def _dummy_state() -> InvestigationState:
    return InvestigationState(
        network="tron",
        asset_symbol="USDT",
        asset_contract=None,
        hop_depth=1,
        branch_count=1,
        unresolved_branch_count=0,
        has_supported_vasp_boundary=False,
        has_vasp_candidate=False,
        has_bridge_boundary=False,
        coverage_status="complete_within_scope",
        provider_error_class="none",
        request_budget_remaining=True,
        receipt_verified=True,
        finality_state="confirmed",
        cross_chain_protocol="none",
        cross_chain_status="NONE",
        cross_chain_link_available=False,
        cross_chain_continuation_pending=False,
        destination_network_known=False,
        destination_network=None,
        destination_execution_verified=False,
        destination_trace_started=False,
        destination_trace_complete=False,
        reviewed_service_control_available=False,
        candidate_only=False,
        no_attribution_evidence=True,
        human_review_required=False,
        report_ready=False,
        terminal_address="TMqg...",
    )


@pytest.mark.asyncio
async def test_clm_systemone_request_wire_format():
    """Client must send official /v1/systemone schema with Choice question and criteria."""
    candidates = [
        InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
        InvestigationActionKey.REVIEW_VASP_CANDIDATE.value,
    ]

    captured_request: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/systemone"
        captured_request.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "model": "qwen3-8b-live-eval",
                "answers": {
                    "next_action": {
                        "type": "choice",
                        "choice": InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
                        "confidence": 0.88,
                        "probabilities": {
                            InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value: 0.88,
                            InvestigationActionKey.REVIEW_VASP_CANDIDATE.value: 0.12,
                        },
                    }
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        router = ClmRouter(
            clm_url="http://mock-clm:8700",
            model_identifier="qwen3-8b",
            http_client=client,
        )
        res = await router.rank_actions(_dummy_state(), candidates)

    assert "state" in captured_request
    assert captured_request["model"] == "qwen3-8b"
    assert "questions" in captured_request
    assert "next_action" in captured_request["questions"]

    q = captured_request["questions"]["next_action"]
    assert q["type"] == "choice"
    assert "criteria" in q
    assert InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value in q["criteria"]
    assert InvestigationActionKey.REVIEW_VASP_CANDIDATE.value in q["criteria"]

    # Result assertions
    assert res.router_name == "clm_router"
    assert res.chosen_action == InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value
    assert res.configured_model == "qwen3-8b"
    assert res.response_model == "qwen3-8b-live-eval"
    assert res.relative_action_probabilities is not None
    assert (
        res.relative_action_probabilities[
            InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value
        ]
        == 0.88
    )


@pytest.mark.asyncio
async def test_clm_rejects_unknown_choice_action():
    """CLM response returning a choice not in candidate set must be rejected."""
    candidates = [InvestigationActionKey.CONTINUE_SAME_CHAIN.value]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "next_action": {
                        "type": "choice",
                        "choice": "UNKNOWN_ACTION_KEY",
                        "probabilities": {"UNKNOWN_ACTION_KEY": 1.0},
                    }
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        router = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
        with pytest.raises(ClmRoutingError, match="not in supplied candidate criteria"):
            await router.rank_actions(_dummy_state(), candidates)


@pytest.mark.asyncio
async def test_clm_rejects_unknown_probability_key():
    """CLM response returning unknown action in probabilities must be rejected."""
    candidates = [InvestigationActionKey.CONTINUE_SAME_CHAIN.value]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "next_action": {
                        "type": "choice",
                        "choice": InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
                        "probabilities": {
                            InvestigationActionKey.CONTINUE_SAME_CHAIN.value: 0.9,
                            "HALLUCINATED_ACTION": 0.1,
                        },
                    }
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        router = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
        with pytest.raises(ClmRoutingError, match="unknown action 'HALLUCINATED_ACTION'"):
            await router.rank_actions(_dummy_state(), candidates)


@pytest.mark.asyncio
async def test_clm_rejects_out_of_range_and_nan_probabilities():
    """CLM response with NaN, negative, or > 1.0 probabilities must be rejected."""
    candidates = [InvestigationActionKey.CONTINUE_SAME_CHAIN.value]

    for bad_prob in [-0.1, 1.5, "NaN"]:
        raw_body = (
            f'{{"answers": {{"next_action": {{"type": "choice", '
            f'"choice": "{candidates[0]}", '
            f'"probabilities": {{"{candidates[0]}": {bad_prob}}}}}}}}}'
        )

        def handler(request: httpx.Request, body=raw_body) -> httpx.Response:
            return httpx.Response(
                200,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            router = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
            with pytest.raises(ClmRoutingError):
                await router.rank_actions(_dummy_state(), candidates)


@pytest.mark.asyncio
async def test_clm_sends_authorization_bearer_header():
    """When api_key is configured, Authorization: Bearer <secret> must be sent."""
    candidates = [InvestigationActionKey.CONTINUE_SAME_CHAIN.value]
    auth_header_received: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth_header_received.append(request.headers.get("Authorization", ""))
        return httpx.Response(
            200,
            json={
                "answers": {
                    "next_action": {
                        "type": "choice",
                        "choice": candidates[0],
                        "probabilities": {candidates[0]: 1.0},
                    }
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        router = ClmRouter(
            clm_url="http://mock-clm:8700",
            api_key="super-secret-key-12345",
            http_client=client,
        )
        await router.rank_actions(_dummy_state(), candidates)

    assert auth_header_received == ["Bearer super-secret-key-12345"]


@pytest.mark.asyncio
async def test_clm_timeout_raises_error():
    """CLM request timeout raises ClmRoutingError."""
    candidates = [InvestigationActionKey.CONTINUE_SAME_CHAIN.value]

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("mock timeout")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        router = ClmRouter(
            clm_url="http://mock-clm:8700", timeout_seconds=0.1, http_client=client
        )
        with pytest.raises(ClmRoutingError, match="timed out"):
            await router.rank_actions(_dummy_state(), candidates)


@pytest.mark.asyncio
async def test_clm_http_500_raises_error():
    """CLM server 500 error raises ClmRoutingError."""
    candidates = [InvestigationActionKey.CONTINUE_SAME_CHAIN.value]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        router = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
        with pytest.raises(ClmRoutingError, match="HTTP 500"):
            await router.rank_actions(_dummy_state(), candidates)


@pytest.mark.asyncio
async def test_clm_malformed_json_raises_error():
    """Malformed non-JSON response raises ClmRoutingError."""
    candidates = [InvestigationActionKey.CONTINUE_SAME_CHAIN.value]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>Bad Gateway</html>",
            headers={"Content-Type": "text/html"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        router = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
        with pytest.raises(ClmRoutingError, match="CLM request/response failure"):
            await router.rank_actions(_dummy_state(), candidates)
