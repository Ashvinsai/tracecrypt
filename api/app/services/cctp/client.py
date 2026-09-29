"""Circle Iris Attestation API client and message matcher.

Interacts with Circle's public mainnet Iris API:
- Endpoint: GET https://iris-api.circle.com/v2/messages/{sourceDomain}?transactionHash={tx_hash}
- Strict multi-field message matching (nonce, domains, amount, recipient, tx_hash).
- Disallows selecting first message blindly if ambiguous.
- Terminology: API_REPORTED_COMPLETE (not cryptographically verified unless ECDSA is run).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx

from app.services.cctp.source import CctpSourceMessage

IRIS_API_MAINNET_BASE: Final[str] = "https://iris-api.circle.com"


@dataclass(frozen=True)
class CircleApiMatchResult:
    matched: bool
    status: str
    attestation_bytes: str | None
    event_nonce: str | None
    api_message_bytes: str | None
    forward_tx_hint: str | None
    ambiguous: bool = False
    raw_response: dict[str, Any] | None = None
    error_message: str | None = None


class CircleCctpClient:
    """Client for Circle's Iris Attestation API."""

    def __init__(
        self,
        base_url: str = IRIS_API_MAINNET_BASE,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._external_client = http_client
        self._timeout = timeout

    async def fetch_messages_for_tx(
        self,
        source_domain: int,
        tx_hash: str,
    ) -> dict[str, Any]:
        """Fetch messages emitted in a transaction on a source domain."""
        url = f"{self.base_url}/v2/messages/{source_domain}"
        params = {"transactionHash": tx_hash}

        if self._external_client is not None:
            resp = await self._external_client.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def match_source_message(
        api_response: dict[str, Any],
        source_msg: CctpSourceMessage,
    ) -> CircleApiMatchResult:
        """Strict multi-field matching between decoded on-chain message and Iris response."""
        messages = api_response.get("messages") or []
        if not messages:
            return CircleApiMatchResult(
                matched=False,
                status="NOT_FOUND",
                attestation_bytes=None,
                event_nonce=None,
                api_message_bytes=None,
                forward_tx_hint=None,
                raw_response=api_response,
                error_message="No messages returned by Iris API for transaction",
            )

        candidates: list[dict[str, Any]] = []

        clean_burn_token = source_msg.burn_token.lower()
        clean_mint_recip = source_msg.mint_recipient.lower()
        expected_amount = str(source_msg.amount_base_units)
        expected_dst_domain = str(source_msg.destination_domain)

        for m in messages:
            dec_msg = m.get("decodedMessage") or {}
            dec_body = dec_msg.get("decodedMessageBody") or {}

            # Destination domain check
            if str(dec_msg.get("destinationDomain")) != expected_dst_domain:
                continue

            # Burn token check
            api_burn_tok = (dec_body.get("burnToken") or "").lower()
            if api_burn_tok != clean_burn_token:
                continue

            # Mint recipient check
            api_mint_recip = (dec_body.get("mintRecipient") or "").lower()
            if api_mint_recip != clean_mint_recip:
                continue

            # Amount check
            api_amount = str(dec_body.get("amount", ""))
            if api_amount != expected_amount:
                continue

            candidates.append(m)

        if len(candidates) > 1:
            return CircleApiMatchResult(
                matched=False,
                status="AMBIGUOUS",
                attestation_bytes=None,
                event_nonce=None,
                api_message_bytes=None,
                forward_tx_hint=None,
                ambiguous=True,
                raw_response=api_response,
                error_message=(
                    f"Ambiguous match: {len(candidates)} messages matched criteria in Iris API"
                ),
            )

        if not candidates:
            return CircleApiMatchResult(
                matched=False,
                status="NOT_MATCHED",
                attestation_bytes=None,
                event_nonce=None,
                api_message_bytes=None,
                forward_tx_hint=None,
                raw_response=api_response,
                error_message="No message matched source parameters in Iris API response",
            )

        selected = candidates[0]
        status_str = selected.get("status", "unknown").lower()
        attestation = selected.get("attestation")
        event_nonce = selected.get("eventNonce")
        msg_bytes = selected.get("message")
        forward_hint = selected.get("forwardTxHash")

        if status_str == "complete" and attestation and attestation.lower() != "pending":
            reported_status = "API_REPORTED_COMPLETE"
        elif "pending" in status_str or (attestation and "pending" in attestation.lower()):
            reported_status = "PENDING"
        else:
            reported_status = status_str.upper()

        return CircleApiMatchResult(
            matched=True,
            status=reported_status,
            attestation_bytes=attestation,
            event_nonce=str(event_nonce) if event_nonce is not None else None,
            api_message_bytes=msg_bytes,
            forward_tx_hint=forward_hint,
            raw_response=api_response,
        )
