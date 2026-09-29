"""Cross-chain linker for Circle CCTP V2 transfers.

Coordinates:
1. Source-chain deposit and message logs.
2. Circle Iris API attestation resolution.
3. Destination-chain receive and mint execution logs.
4. Produces immutable, verified CrossChainLink records.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from app.models.cross_chain import (
    AmountReconciliationResult,
    CrossChainLink,
    CrossChainLinkageStatus,
)
from app.services.cctp.binary import reconcile_cctp_amounts
from app.services.cctp.client import CircleApiMatchResult
from app.services.cctp.destination import DestinationExecutionRecord
from app.services.cctp.provenance import get_usdc_contract
from app.services.cctp.source import CctpSourceMessage, extract_cctp_source_messages


@dataclass(frozen=True)
class LinkerResult:
    link: CrossChainLink
    destination_seed_address: str | None = None


class CctpLinker:
    """Coordinates cross-chain attribution between Ethereum and Base via Circle CCTP V2."""

    def extract_source_messages(
        self,
        receipt: dict[str, Any],
        network_key: str = "ethereum",
        chain_id: int = 1,
    ) -> list[CctpSourceMessage]:
        return extract_cctp_source_messages(receipt, network_key=network_key, chain_id=chain_id)

    def build_link(
        self,
        *,
        source_message: CctpSourceMessage | None,
        api_message: CircleApiMatchResult | dict[str, Any] | None,
        destination_execution: DestinationExecutionRecord | dict[str, Any] | None,
        source_block_time: dt.datetime | None = None,
        destination_block_time: dt.datetime | None = None,
        source_finality: str | None = None,
        destination_receipt_finality: str | None = None,
    ) -> CrossChainLink:
        """Build and reconcile a CrossChainLink from components."""
        # 1. Normalize source parameters
        if source_message is not None:
            src_net = source_message.source_network
            src_chain = source_message.source_chain_id
            src_dom = source_message.source_domain
            src_tx = source_message.source_tx_hash
            src_burn_ref = source_message.source_burn_event_reference
            src_msg_ref = source_message.source_message_event_reference
            src_block = source_message.source_block_number
            burn_token = source_message.burn_token
            depositor = source_message.depositor
            mint_recipient = source_message.mint_recipient
            burn_amount = source_message.amount_base_units
            max_fee = source_message.max_fee_base_units
            fee_exec = source_message.decoded_burn.fee_executed_base_units
            msg_bytes_hex = "0x" + source_message.raw_message_bytes.hex()
            msg_hash = source_message.message_hash
            header_version = source_message.decoded_message.header_version
            burn_version = source_message.decoded_burn.burn_message_version
            dst_dom = source_message.destination_domain
            # On-chain MessageSent has 0-nonce; Iris API populates eventNonce
            msg_nonce = source_message.decoded_message.nonce_hex
        else:
            # Synthetic / test fallback
            src_net = "ethereum"
            src_chain = 1
            src_dom = 0
            src_tx = "0x" + "00" * 32
            src_burn_ref = "eip155:1:0x00:0"
            src_msg_ref = "eip155:1:0x00:1"
            src_block = 0
            burn_token = get_usdc_contract("ethereum")
            depositor = ""
            mint_recipient = ""
            burn_amount = 0
            max_fee = 0
            fee_exec = 0
            msg_bytes_hex = "0x"
            msg_hash = "0x"
            header_version = 1
            burn_version = 1
            dst_dom = 6
            msg_nonce = "0x" + "00" * 32

        # 2. Normalize API match
        att_status = "UNKNOWN"
        att_bytes: str | None = None
        api_nonce: str | None = None
        if isinstance(api_message, CircleApiMatchResult):
            att_status = api_message.status
            att_bytes = api_message.attestation_bytes
            api_nonce = api_message.event_nonce
            if api_nonce and not msg_nonce.replace("0x", "").strip("0"):
                msg_nonce = api_nonce
        elif isinstance(api_message, dict):
            status_val = api_message.get("status", "unknown").lower()
            att_bytes = api_message.get("attestation")
            api_nonce = api_message.get("eventNonce")
            if status_val == "complete" and att_bytes:
                att_status = "API_REPORTED_COMPLETE"
            elif "pending" in status_val:
                att_status = "PENDING"
            else:
                att_status = status_val.upper()
            if api_nonce and not msg_nonce.replace("0x", "").strip("0"):
                msg_nonce = str(api_nonce)

        att_length_bytes: int | None = None
        sig_blob_count: int | None = None
        if att_bytes:
            clean_att = (
                att_bytes[2:]
                if att_bytes.startswith(("0x", "0X"))
                else att_bytes
            )
            try:
                raw_att = bytes.fromhex(clean_att)
                att_length_bytes = len(raw_att)
                sig_blob_count = (
                    att_length_bytes // 65
                    if att_length_bytes % 65 == 0
                    else (att_length_bytes // 65)
                )
            except ValueError:
                pass

        # 3. Normalize destination execution
        dst_net = "base"
        dst_chain = 8453
        dst_tx: str | None = None
        dst_rec_ref: str | None = None
        dst_mint_ref: str | None = None
        dst_block: int | None = None
        dst_exec_status: str | None = None
        cctp_finality_exec: int | None = None
        obs_mint_amt: int | None = None
        obs_usdc_amt: int | None = None

        if isinstance(destination_execution, DestinationExecutionRecord):
            dst_net = destination_execution.destination_network
            dst_chain = destination_execution.destination_chain_id
            dst_dom = destination_execution.destination_domain
            dst_tx = destination_execution.destination_tx_hash
            dst_rec_ref = destination_execution.destination_receive_event_reference
            dst_mint_ref = destination_execution.destination_mint_event_reference
            dst_block = destination_execution.destination_block_number
            dst_exec_status = (
                "success"
                if destination_execution.destination_receipt_status == "0x1"
                else "reverted"
            )
            cctp_finality_exec = destination_execution.finality_threshold_executed
            obs_mint_amt = destination_execution.mint_and_withdraw_amount
            obs_usdc_amt = destination_execution.usdc_transfer_amount
            if destination_execution.mint_recipient:
                if not mint_recipient:
                    mint_recipient = destination_execution.mint_recipient
        elif isinstance(destination_execution, dict):
            dst_tx = destination_execution.get("tx_hash")
            st = destination_execution.get("receipt_status", "0x1")
            dst_exec_status = "success" if str(st) in ("0x1", "1", 1) else "reverted"
            dst_rec_ref = destination_execution.get("receive_event_reference")
            dst_mint_ref = destination_execution.get("mint_event_reference")
            dst_block = destination_execution.get("block_number")
            cctp_finality_exec = destination_execution.get("finality_threshold_executed")
            obs_mint_amt = destination_execution.get("mint_and_withdraw_amount")
            obs_usdc_amt = destination_execution.get("usdc_transfer_amount")

        # 4. Reconcile amounts
        amt_rec = reconcile_cctp_amounts(
            burn_amount=burn_amount,
            max_fee=max_fee,
            fee_executed=fee_exec,
            observed_mint_amount=obs_mint_amt,
            observed_recipient_usdc=obs_usdc_amt,
        )

        # 5. Determine overall linkage status
        if att_status == "AMBIGUOUS":
            link_status = CrossChainLinkageStatus.AMBIGUOUS
        elif dst_exec_status == "reverted":
            link_status = CrossChainLinkageStatus.FAILED
        elif amt_rec == AmountReconciliationResult.MISMATCH:
            link_status = CrossChainLinkageStatus.FAILED
        elif (
            dst_tx
            and dst_rec_ref
            and dst_exec_status == "success"
            and att_status == "API_REPORTED_COMPLETE"
        ):
            link_status = CrossChainLinkageStatus.COMPLETE
        elif dst_tx and dst_exec_status == "success":
            link_status = CrossChainLinkageStatus.DESTINATION_RECEIVED
        elif att_status == "API_REPORTED_COMPLETE":
            link_status = CrossChainLinkageStatus.INCOMPLETE
        elif att_status == "PENDING":
            link_status = CrossChainLinkageStatus.INCOMPLETE
        elif source_message is not None:
            link_status = CrossChainLinkageStatus.MESSAGE_IDENTIFIED
        else:
            link_status = CrossChainLinkageStatus.INCOMPLETE

        evidence_refs: list[str] = [src_burn_ref, src_msg_ref]
        if dst_rec_ref:
            evidence_refs.append(dst_rec_ref)
        if dst_mint_ref:
            evidence_refs.append(dst_mint_ref)

        limitations: list[str] = [
            (
                "Cross-chain continuation is protocol-specific to Circle CCTP V2 "
                "(Ethereum Mainnet -> Base Mainnet USDC)."
            ),
            (
                "Attestation status is reported by Circle Iris API metadata; independent "
                "on-chain ECDSA signature verification is not executed locally."
            ),
        ]
        if amt_rec == AmountReconciliationResult.UNKNOWN:
            limitations.append(
                "Destination minted amount not yet reconciled with source burn amount."
            )

        return CrossChainLink(
            protocol_family="circle_cctp",
            protocol_generation=2,
            message_header_version=header_version,
            burn_message_version=burn_version,
            linkage_status=link_status,
            source_network=src_net,
            source_chain_id=src_chain,
            source_domain=src_dom,
            source_tx_hash=src_tx,
            source_burn_event_reference=src_burn_ref,
            source_message_event_reference=src_msg_ref,
            source_block_number=src_block,
            source_block_time=source_block_time,
            source_finality=source_finality,
            source_event_nonce=None,
            message_nonce=msg_nonce,
            api_event_nonce=api_nonce,
            message_hash=msg_hash,
            message_bytes=msg_bytes_hex,
            attestation_status=att_status,
            attestation_bytes=att_bytes,
            attestation_length_bytes=att_length_bytes,
            signature_blob_size_bytes=65,
            signature_blob_count=sig_blob_count,
            attestation_source="circle_iris_api",
            attestation_signature_verified=False,
            burn_token=burn_token,
            mint_token=get_usdc_contract(dst_net),
            depositor=depositor,
            mint_recipient=mint_recipient,
            source_burn_amount_base_units=burn_amount,
            max_fee_base_units=max_fee,
            fee_executed_base_units=fee_exec,
            observed_mint_and_withdraw_amount_base_units=obs_mint_amt,
            observed_recipient_usdc_amount_base_units=obs_usdc_amt,
            amount_reconciliation=amt_rec,
            destination_network=dst_net,
            destination_chain_id=dst_chain,
            destination_domain=dst_dom,
            destination_tx_hash=dst_tx,
            destination_receive_event_reference=dst_rec_ref,
            destination_mint_event_reference=dst_mint_ref,
            destination_block_number=dst_block,
            destination_block_time=destination_block_time,
            destination_receipt_finality=destination_receipt_finality,
            cctp_finality_threshold_executed=cctp_finality_exec,
            destination_execution_status=dst_exec_status,
            evidence_references=tuple(evidence_refs),
            limitations=tuple(limitations),
        )
