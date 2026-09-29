"""Source-event decoding for Circle CCTP V2 on Ethereum Mainnet.

Decodes:
- MessageSent(bytes) on MessageTransmitterV2
- DepositForBurn(address,uint256,address,bytes32,uint32,bytes32,bytes32,uint256,uint32,bytes)
  on TokenMessengerV2 or TokenMessengerWithFees
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.services.cctp.binary import (
    DecodedBurnMessageV2,
    DecodedMessageV2,
    decode_burn_message_v2,
    decode_message_v2,
    keccak256,
)
from app.services.cctp.provenance import get_cctp_contract

DEPOSIT_FOR_BURN_V2_SIG: Final[str] = (
    "DepositForBurn(address,uint256,address,bytes32,uint32,bytes32,bytes32,uint256,uint32,bytes)"
)
DEPOSIT_FOR_BURN_V2_TOPIC: Final[str] = (
    "0x0c8c1cbdc5190613ebd485511d4e2812cfa45eecb79d845893331fedad5130a5"
)

MESSAGE_SENT_SIG: Final[str] = "MessageSent(bytes)"
MESSAGE_SENT_TOPIC: Final[str] = (
    "0x8c5261668696ce22758910d05bab8f186d6eb247ceac2af2e82c7dc17669b036"
)


@dataclass(frozen=True)
class CctpSourceMessage:
    source_network: str
    source_chain_id: int
    source_domain: int
    source_tx_hash: str
    source_burn_event_reference: str
    source_message_event_reference: str
    source_block_number: int
    burn_token: str
    depositor: str
    mint_recipient: str
    destination_domain: int
    destination_token_messenger: str
    destination_caller: str
    amount_base_units: int
    max_fee_base_units: int
    min_finality_threshold: int
    raw_message_bytes: bytes
    message_hash: str
    decoded_message: DecodedMessageV2
    decoded_burn: DecodedBurnMessageV2

    @property
    def source_burn_amount_base_units(self) -> int:
        return self.amount_base_units


def _parse_int(val: Any) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return int(val, 16) if val.startswith(("0x", "0X")) else int(val)
    raise ValueError(f"Cannot parse int from {val!r}")


def extract_cctp_source_messages(
    receipt: dict[str, Any],
    network_key: str = "ethereum",
    chain_id: int = 1,
) -> list[CctpSourceMessage]:
    """Extract and reconcile CCTP V2 source messages from a transaction receipt."""
    status = receipt.get("status")
    if status is not None and str(status) not in ("0x1", "1", 1):
        # Transaction failed / reverted
        return []

    tx_hash = receipt.get("transactionHash") or ""
    block_number = _parse_int(receipt.get("blockNumber", 0))

    expected_mt = get_cctp_contract(network_key, "MessageTransmitterV2")
    expected_tm = get_cctp_contract(network_key, "TokenMessengerV2")
    expected_tm_fees = get_cctp_contract(network_key, "TokenMessengerWithFees")
    valid_tm_addresses = {expected_tm, expected_tm_fees}

    logs = receipt.get("logs") or []

    # Collect MessageSent logs
    message_sent_logs: list[dict[str, Any]] = []
    # Collect DepositForBurn logs
    deposit_logs: list[dict[str, Any]] = []

    for log in logs:
        addr = (log.get("address") or "").lower()
        topics = log.get("topics") or []
        if not topics:
            continue
        topic0 = topics[0].lower()

        if addr == expected_mt and topic0 == MESSAGE_SENT_TOPIC.lower():
            message_sent_logs.append(log)
        elif addr in valid_tm_addresses and topic0 == DEPOSIT_FOR_BURN_V2_TOPIC.lower():
            deposit_logs.append(log)

    if not message_sent_logs or not deposit_logs:
        return []

    # Pair them in ascending order of logIndex
    results: list[CctpSourceMessage] = []
    # A single tx may have N transfers; pair ith message_sent with ith deposit
    for ms_log, dfb_log in zip(message_sent_logs, deposit_logs, strict=False):
        ms_index = _parse_int(ms_log.get("logIndex", 0))
        dfb_index = _parse_int(dfb_log.get("logIndex", 0))

        # Decode MessageSent payload: ABI dynamic bytes encoding
        # data has offset (word0), length (word1), then raw bytes
        ms_data_hex = ms_log.get("data", "0x")
        if ms_data_hex.startswith(("0x", "0X")):
            ms_data_hex = ms_data_hex[2:]
        ms_data_bytes = bytes.fromhex(ms_data_hex)
        if len(ms_data_bytes) < 64:
            continue
        msg_length = int.from_bytes(ms_data_bytes[32:64], "big")
        raw_message = ms_data_bytes[64 : 64 + msg_length]
        if len(raw_message) < 148:
            continue

        decoded_msg = decode_message_v2(raw_message)
        decoded_burn = decode_burn_message_v2(decoded_msg.message_body)
        msg_hash = "0x" + keccak256(raw_message).hex()

        # Decode DepositForBurn topics and data
        dfb_topics = dfb_log.get("topics") or []
        if len(dfb_topics) < 4:
            continue
        burn_token_topic = "0x" + dfb_topics[1][-40:]
        depositor_topic = "0x" + dfb_topics[2][-40:]
        min_finality = int(dfb_topics[3], 16)

        dfb_data_hex = dfb_log.get("data", "0x")
        if dfb_data_hex.startswith(("0x", "0X")):
            dfb_data_hex = dfb_data_hex[2:]
        dfb_data_bytes = bytes.fromhex(dfb_data_hex)
        if len(dfb_data_bytes) < 192:  # at least 6 32-byte words
            continue

        amount = int.from_bytes(dfb_data_bytes[0:32], "big")
        mint_recipient = "0x" + dfb_data_bytes[32:64][-20:].hex()
        dst_domain = int.from_bytes(dfb_data_bytes[64:96], "big")
        dst_tm = "0x" + dfb_data_bytes[96:128][-20:].hex()
        dst_caller = "0x" + dfb_data_bytes[128:160].hex()
        max_fee = int.from_bytes(dfb_data_bytes[160:192], "big")

        caip2 = f"eip155:{chain_id}"
        source_burn_ref = f"{caip2}:{tx_hash}:{dfb_index}"
        source_msg_ref = f"{caip2}:{tx_hash}:{ms_index}"

        results.append(
            CctpSourceMessage(
                source_network=network_key,
                source_chain_id=chain_id,
                source_domain=decoded_msg.source_domain,
                source_tx_hash=tx_hash,
                source_burn_event_reference=source_burn_ref,
                source_message_event_reference=source_msg_ref,
                source_block_number=block_number,
                burn_token=burn_token_topic.lower(),
                depositor=depositor_topic.lower(),
                mint_recipient=mint_recipient.lower(),
                destination_domain=dst_domain,
                destination_token_messenger=dst_tm.lower(),
                destination_caller=dst_caller.lower(),
                amount_base_units=amount,
                max_fee_base_units=max_fee,
                min_finality_threshold=min_finality,
                raw_message_bytes=raw_message,
                message_hash=msg_hash,
                decoded_message=decoded_msg,
                decoded_burn=decoded_burn,
            )
        )

    return results
