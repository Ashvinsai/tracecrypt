"""Official Contrastive-LM (CLM) HTTP Client for System-1 action ranking (Task 08).

Uses official CLM endpoints:
- Production routing: POST /v1/systemone with exactly one Choice question.
- Benchmark scaling:  POST /v1/rank.

Enforces strict client-side validation:
- Validates Choice answer and candidate criteria set.
- Rejects unknown action IDs.
- Rejects NaN, Inf, negative, and out-of-range probabilities.
- Rejects duplicate action keys.
- Records relative_action_probabilities (never fraud/ownership/VASP probability).
- Strictly read-only decision support.
- Zero local GPU or CUDA dependencies.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from typing import Any

import httpx

from app.models.investigation_routing import (
    InvestigationAction,
    InvestigationState,
    RankedAction,
    RoutingResult,
)
from app.services.routing.actions import (
    get_canonical_action,
    sort_actions_canonical,
)
from app.services.routing.state import (
    SYSTEMONE_INSTRUCTIONS,
    serialize_investigation_state,
)


class ClmRoutingError(RuntimeError):
    """Raised when CLM endpoint is unreachable, times out, or returns invalid response."""


class ClmRouter:
    """HTTP client routing candidate actions via official CLM endpoints."""

    ROUTER_NAME = "clm_router"

    def __init__(
        self,
        clm_url: str,
        timeout_seconds: float = 2.0,
        model_identifier: str = "qwen3-8b",
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.clm_url = clm_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.model_identifier = model_identifier
        self.api_key = api_key
        self._client = http_client

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def rank_actions(
        self,
        state: InvestigationState,
        candidate_actions: Sequence[InvestigationAction | str],
    ) -> RoutingResult:
        """Call official CLM /v1/systemone endpoint with a Choice question."""
        start_time = time.perf_counter()

        sorted_keys = sort_actions_canonical(candidate_actions)
        expected_set = set(sorted_keys)

        # Build criteria mapping in canonical catalog order
        criteria: dict[str, str] = {}
        for key in sorted_keys:
            act = get_canonical_action(key)
            criteria[key] = (
                act.description
                if act
                else f"Candidate action {key}"
            )

        serialized_state = serialize_investigation_state(state)
        endpoint = f"{self.clm_url}/v1/systemone"

        payload = {
            "state": serialized_state,
            "model": self.model_identifier,
            "questions": {
                "next_action": {
                    "type": "choice",
                    "instructions": SYSTEMONE_INSTRUCTIONS,
                    "criteria": criteria,
                }
            },
        }

        headers = self._build_headers()

        try:
            if self._client is not None:
                response = await self._client.post(
                    endpoint, json=payload, headers=headers, timeout=self.timeout_seconds
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        endpoint, json=payload, headers=headers, timeout=self.timeout_seconds
                    )

            if response.status_code != 200:
                raise ClmRoutingError(
                    f"CLM server returned HTTP {response.status_code}: {response.text[:200]}"
                )

            data: Any = response.json()
        except httpx.TimeoutException as exc:
            raise ClmRoutingError(
                f"CLM request timed out after {self.timeout_seconds}s"
            ) from exc
        except httpx.ConnectError as exc:
            raise ClmRoutingError(
                f"Connection refused to CLM server at {self.clm_url}"
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise ClmRoutingError(f"CLM request/response failure: {exc}") from exc

        # Response structure validation
        if not isinstance(data, dict):
            raise ClmRoutingError("CLM response must be a JSON object.")

        response_model = data.get("model")

        # Answer retrieval: answers["next_action"] or top-level answer
        answers = data.get("answers")
        if isinstance(answers, dict) and "next_action" in answers:
            answer = answers["next_action"]
        elif "answer" in data:
            answer = data["answer"]
        elif "choice" in data:
            answer = data
        else:
            raise ClmRoutingError(
                "CLM response missing required 'next_action' answer."
            )

        if not isinstance(answer, dict):
            raise ClmRoutingError("CLM answer must be a JSON object.")

        chosen_choice = answer.get("choice")
        if not isinstance(chosen_choice, str):
            raise ClmRoutingError("CLM answer missing valid 'choice' string.")

        if chosen_choice not in expected_set:
            raise ClmRoutingError(
                f"CLM chosen action '{chosen_choice}' not in supplied candidate criteria."
            )

        # Validate confidence if present
        raw_conf = answer.get("confidence")
        if raw_conf is not None:
            if (
                not isinstance(raw_conf, (int, float))
                or isinstance(raw_conf, bool)
                or not math.isfinite(float(raw_conf))
            ):
                raise ClmRoutingError(f"CLM returned non-finite confidence: {raw_conf!r}")

        # Validate probabilities mapping
        raw_probs = answer.get("probabilities")
        if not isinstance(raw_probs, dict):
            raise ClmRoutingError("CLM answer missing required 'probabilities' mapping.")

        relative_action_probabilities: dict[str, float] = {}
        ranked_actions: list[RankedAction] = []

        for action_name, raw_p in raw_probs.items():
            if not isinstance(action_name, str):
                raise ClmRoutingError("Probability key must be a string.")

            if action_name not in expected_set:
                raise ClmRoutingError(
                    f"CLM returned unknown action '{action_name}' in probabilities."
                )

            if not isinstance(raw_p, (int, float)) or isinstance(raw_p, bool):
                raise ClmRoutingError(
                    f"CLM returned non-numeric probability for '{action_name}': {raw_p!r}"
                )

            prob = float(raw_p)
            if not math.isfinite(prob) or prob < 0.0 or prob > 1.0:
                raise ClmRoutingError(
                    f"CLM returned out-of-range probability for '{action_name}': {prob}"
                )

            relative_action_probabilities[action_name] = prob
            ranked_actions.append(
                RankedAction(
                    action=action_name,
                    score=prob,
                    reason=f"relative_action_probability={prob:.4f}",
                )
            )

        # Ensure chosen action is represented in ranked actions
        if chosen_choice not in relative_action_probabilities:
            raise ClmRoutingError(
                f"Chosen choice '{chosen_choice}' missing from probabilities mapping."
            )

        # Sort descending by probability, with chosen_choice prioritized on tie
        ranked_actions.sort(
            key=lambda a: (-a.score, 0 if a.action == chosen_choice else 1, a.action)
        )

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 3)

        return RoutingResult(
            router_name=self.ROUTER_NAME,
            ranked_actions=tuple(ranked_actions),
            latency_ms=latency_ms,
            configured_model=self.model_identifier,
            response_model=response_model,
            relative_action_probabilities=relative_action_probabilities,
            chosen_action=chosen_choice,
        )

    async def rank_candidates_scaling(
        self,
        state: InvestigationState,
        candidate_actions: Sequence[str],
    ) -> RoutingResult:
        """Call official CLM /v1/rank endpoint for scaling benchmarks."""
        start_time = time.perf_counter()
        serialized_state = serialize_investigation_state(state)
        endpoint = f"{self.clm_url}/v1/rank"

        payload = {
            "state": serialized_state,
            "candidates": list(candidate_actions),
            "model": self.model_identifier,
        }

        headers = self._build_headers()

        try:
            if self._client is not None:
                response = await self._client.post(
                    endpoint, json=payload, headers=headers, timeout=self.timeout_seconds
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        endpoint, json=payload, headers=headers, timeout=self.timeout_seconds
                    )

            if response.status_code != 200:
                raise ClmRoutingError(
                    f"CLM /v1/rank returned HTTP {response.status_code}: {response.text[:200]}"
                )

            data: Any = response.json()
        except (httpx.RequestError, ValueError) as exc:
            raise ClmRoutingError(f"CLM /v1/rank failure: {exc}") from exc

        if not isinstance(data, dict) or "ranked" not in data:
            raise ClmRoutingError("CLM /v1/rank missing 'ranked' array.")

        raw_ranked = data["ranked"]
        ranked_actions = [
            RankedAction(action=item["candidate"], score=float(item.get("score", 0.0)))
            for item in raw_ranked
        ]
        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 3)

        return RoutingResult(
            router_name=f"{self.ROUTER_NAME}_scaling",
            ranked_actions=tuple(ranked_actions),
            latency_ms=latency_ms,
            configured_model=self.model_identifier,
            response_model=data.get("model"),
        )
