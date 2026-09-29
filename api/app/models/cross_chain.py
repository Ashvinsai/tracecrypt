"""Cross-chain linkage models and evidence representations (Task 07).

Defines first-class cross-chain transition structures:
- Protocol family and generation vs message header version vs burn message version.
- Discrete nonce concepts (source event nonce, message nonce, api event nonce).
- Explicit uint256 integer amount and fee accounting.
- Separation of on-chain consensus receipt finality from protocol finality threshold.
- Explicit evidence references and limitations.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from app.core.amounts import serialize


class CrossChainLinkageStatus(StrEnum):
    """Monotonic evidence-backed linkage status."""

    SOURCE_OBSERVED = "SOURCE_OBSERVED"
    MESSAGE_IDENTIFIED = "MESSAGE_IDENTIFIED"
    ATTESTATION_REPORTED = "ATTESTATION_REPORTED"
    DESTINATION_RECEIVED = "DESTINATION_RECEIVED"
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class AmountReconciliationResult(StrEnum):
    """Protocol fee and minted value reconciliation outcome."""

    MATCHES_PROTOCOL_EXPECTATION = "MATCHES_PROTOCOL_EXPECTATION"
    MISMATCH = "MISMATCH"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class CrossChainLink:
    """Explicit cross-chain link representing an attested protocol boundary transition.

    Never masquerades as a same-chain NormalizedTransfer: network transition
    from source to destination is explicit and distinct.
    """

    # Protocol identity & versions
    protocol_family: str = "circle_cctp"
    protocol_generation: int = 2
    message_header_version: int = 1
    burn_message_version: int = 1

    linkage_status: CrossChainLinkageStatus

    # Source chain (e.g. Ethereum Mainnet, chain 1, CCTP domain 0)
    source_network: str
    source_chain_id: int
    source_domain: int
    source_tx_hash: str
    source_burn_event_reference: str
    source_message_event_reference: str
    source_block_number: int
    source_block_time: dt.datetime | None = None
    source_finality: str | None = None

    # Protocol message identifiers
    source_event_nonce: int | None = None
    message_nonce: str = ""
    api_event_nonce: str | int | None = None
    message_hash: str = ""
    message_bytes: str = ""

    # Protocol attestation
    attestation_status: str = "UNKNOWN"
    attestation_bytes: str | None = None
    attestation_length_bytes: int | None = None
    signature_blob_size_bytes: int = 65
    signature_blob_count: int | None = None
    attestation_source: str = "circle_iris_api"
    attestation_signature_verified: bool = False

    # Tokens and participants
    burn_token: str = ""
    mint_token: str = ""
    depositor: str = ""
    mint_recipient: str = ""

    # Value & fee accounting (exact uint256 integers in base units, never floats)
    source_burn_amount_base_units: int = 0
    max_fee_base_units: int = 0
    fee_executed_base_units: int = 0
    observed_mint_and_withdraw_amount_base_units: int | None = None
    observed_recipient_usdc_amount_base_units: int | None = None
    amount_reconciliation: AmountReconciliationResult = AmountReconciliationResult.UNKNOWN

    # Destination chain (e.g. Base Mainnet, chain 8453, CCTP domain 6)
    destination_network: str = "base"
    destination_chain_id: int = 8453
    destination_domain: int = 6
    destination_tx_hash: str | None = None
    destination_receive_event_reference: str | None = None
    destination_mint_event_reference: str | None = None
    destination_block_number: int | None = None
    destination_block_time: dt.datetime | None = None
    destination_receipt_finality: str | None = None
    cctp_finality_threshold_executed: int | None = None
    destination_execution_status: str | None = None

    # Provenance and caveats
    evidence_references: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """Serialize cross-chain link with exact string amounts and ISO datetimes."""
        data = asdict(self)
        data["source_burn_amount_base_units"] = serialize(self.source_burn_amount_base_units)
        data["max_fee_base_units"] = serialize(self.max_fee_base_units)
        data["fee_executed_base_units"] = serialize(self.fee_executed_base_units)
        data["observed_mint_and_withdraw_amount_base_units"] = (
            serialize(self.observed_mint_and_withdraw_amount_base_units)
            if self.observed_mint_and_withdraw_amount_base_units is not None
            else None
        )
        data["observed_recipient_usdc_amount_base_units"] = (
            serialize(self.observed_recipient_usdc_amount_base_units)
            if self.observed_recipient_usdc_amount_base_units is not None
            else None
        )
        data["source_block_time"] = (
            self.source_block_time.isoformat() if self.source_block_time else None
        )
        data["destination_block_time"] = (
            self.destination_block_time.isoformat() if self.destination_block_time else None
        )
        data["evidence_references"] = list(self.evidence_references)
        data["limitations"] = list(self.limitations)
        return data
