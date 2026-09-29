"""Destination-event decoding for Circle CCTP V2 on Base Mainnet.

Decodes:
- MessageReceived(address,uint32,bytes32,bytes32,uint32,bytes) on MessageTransmitterV2
- MintAndWithdraw(address,uint256,address) on TokenMessengerV2
- Standard ERC-20 Transfer(address(0), recipient, amount) on Base USDC
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from app.adapters.evm import TRANSFER_TOPIC
from app.services.cctp.provenance import get_cctp_contract, get_usdc_contract

MESSAGE_RECEIVED_V2_SIG: Final[str] = (
    "MessageReceived(address,uint32,bytes32,bytes32,uint32,bytes)"
)
MESSAGE_RECEIVED_V2_TOPIC: Final[str] = (
    "0xff48c13eda96b1cceacc6b9edeedc9e9db9d6226afbc30146b720c19d3addb1c"
)

MINT_AND_WITHDRAW_V2_SIG: Final[str] = "MintAndWithdraw(address,uint256,address,uint256)"
MINT_AND_WITHDRAW_V2_TOPIC: Final[str] = (
    "0x50c55e915134d457debfa58eb6f4342956f8b0616d51a89a3659360178e1ab63"
)
MINT_AND_WITHDRAW_LEGACY_SIG: Final[str] = "MintAndWithdraw(address,uint256,address)"
MINT_AND_WITHDRAW_LEGACY_TOPIC: Final[str] = (
    "0x1b2a7ff080b8cb6ff436ce0372e399692bbfb6d4ae5766fd8d58a7b8cc6142e6"
)


@dataclass(frozen=True)
class DestinationExecutionRecord:
    destination_network: str
    destination_chain_id: int
    destination_domain: int
    destination_tx_hash: str
    destination_block_number: int
    destination_receipt_status: str
    destination_receive_event_reference: str
    destination_mint_event_reference: str | None
    caller_address: str
    source_domain: int
    nonce_hex: str
    sender_bytes32: str
    finality_threshold_executed: int
    mint_recipient: str
    mint_and_withdraw_amount: int | None
    usdc_transfer_amount: int | None
    execution_error: str | None = None


def _parse_int(val: Any) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return int(val, 16) if val.startswith(("0x", "0X")) else int(val)
    raise ValueError(f"Cannot parse int from {val!r}")


def decode_destination_execution(
    receipt: dict[str, Any],
    *,
    expected_nonce: str,
    network_key: str = "base",
    chain_id: int = 8453,
) -> DestinationExecutionRecord | None:
    """Decode and verify CCTP V2 destination execution from a transaction receipt."""
    tx_hash = receipt.get("transactionHash") or ""
    block_num = _parse_int(receipt.get("blockNumber", 0))
    status_raw = receipt.get("status")
    status_str = "0x1" if str(status_raw) in ("0x1", "1", 1) else "0x0"

    expected_mt = get_cctp_contract(network_key, "MessageTransmitterV2")
    expected_tm = get_cctp_contract(network_key, "TokenMessengerV2")
    expected_usdc = get_usdc_contract(network_key)

    logs = receipt.get("logs") or []
    caip2 = f"eip155:{chain_id}"

    # Normalize expected nonce to 64-hex lower
    clean_expected_nonce = expected_nonce.lower()
    if clean_expected_nonce.startswith("0x"):
        clean_expected_nonce = clean_expected_nonce[2:]
    clean_expected_nonce = clean_expected_nonce.zfill(64)

    # Find matching MessageReceived log
    mr_log: dict[str, Any] | None = None
    for log in logs:
        addr = (log.get("address") or "").lower()
        topics = log.get("topics") or []
        if not topics:
            continue
        if addr == expected_mt and topics[0].lower() == MESSAGE_RECEIVED_V2_TOPIC.lower():
            if len(topics) >= 3:
                topic_nonce = topics[2].lower()
                if topic_nonce.startswith("0x"):
                    topic_nonce = topic_nonce[2:]
                topic_nonce = topic_nonce.zfill(64)
                if topic_nonce == clean_expected_nonce:
                    mr_log = log
                    break

    if mr_log is None:
        return None

    mr_index = _parse_int(mr_log.get("logIndex", 0))
    mr_topics = mr_log.get("topics", [])
    caller = "0x" + mr_topics[1][-40:].lower()
    nonce_hex = "0x" + mr_topics[2][-64:].lower()
    finality_exec = int(mr_topics[3], 16) if len(mr_topics) > 3 else 0

    mr_data_hex = mr_log.get("data", "0x")
    if mr_data_hex.startswith(("0x", "0X")):
        mr_data_hex = mr_data_hex[2:]
    mr_bytes = bytes.fromhex(mr_data_hex)

    src_domain = int.from_bytes(mr_bytes[0:32], "big") if len(mr_bytes) >= 32 else 0
    sender = "0x" + mr_bytes[32:64].hex() if len(mr_bytes) >= 64 else ""

    # Find MintAndWithdraw log if executed successfully
    mw_log: dict[str, Any] | None = None
    mint_amount: int | None = None
    mint_recipient: str = ""

    for log in logs:
        addr = (log.get("address") or "").lower()
        topics = log.get("topics") or []
        if not topics:
            continue
        if addr == expected_tm and topics[0].lower() in (
            MINT_AND_WITHDRAW_V2_TOPIC.lower(),
            MINT_AND_WITHDRAW_LEGACY_TOPIC.lower(),
        ):
            mw_log = log
            if len(topics) >= 2:
                mint_recipient = "0x" + topics[1][-40:].lower()
            mw_data = log.get("data", "0x")
            if mw_data.startswith(("0x", "0X")):
                mw_data = mw_data[2:]
            mw_b = bytes.fromhex(mw_data)
            if len(mw_b) >= 32:
                mint_amount = int.from_bytes(mw_b[0:32], "big")
            break

    # Also check USDC transfer from 0x0
    usdc_transfer_amount: int | None = None
    zero_address_topic = "0x0000000000000000000000000000000000000000000000000000000000000000"
    for log in logs:
        addr = (log.get("address") or "").lower()
        topics = log.get("topics") or []
        if (
            len(topics) >= 3
            and addr == expected_usdc
            and topics[0].lower() == TRANSFER_TOPIC.lower()
        ):
            if topics[1].lower() == zero_address_topic:
                t_data = log.get("data", "0x")
                if t_data.startswith(("0x", "0X")):
                    t_data = t_data[2:]
                t_b = bytes.fromhex(t_data)
                if len(t_b) >= 32:
                    usdc_transfer_amount = int.from_bytes(t_b[0:32], "big")
                    if not mint_recipient:
                        mint_recipient = "0x" + topics[2][-40:].lower()
                break

    mw_ref = f"{caip2}:{tx_hash}:{_parse_int(mw_log.get('logIndex', 0))}" if mw_log else None
    mr_ref = f"{caip2}:{tx_hash}:{mr_index}"

    return DestinationExecutionRecord(
        destination_network=network_key,
        destination_chain_id=chain_id,
        destination_domain=6,
        destination_tx_hash=tx_hash,
        destination_block_number=block_num,
        destination_receipt_status=status_str,
        destination_receive_event_reference=mr_ref,
        destination_mint_event_reference=mw_ref,
        caller_address=caller,
        source_domain=src_domain,
        nonce_hex=nonce_hex,
        sender_bytes32=sender,
        finality_threshold_executed=finality_exec,
        mint_recipient=mint_recipient,
        mint_and_withdraw_amount=mint_amount,
        usdc_transfer_amount=usdc_transfer_amount,
        execution_error=None if status_str == "0x1" else "transaction execution reverted",
    )


@dataclass(frozen=True)
class DestinationDiscoveryResult:
    """Result of bounded destination MessageReceived log discovery on Base."""

    status: str  # "FOUND", "NOT_FOUND", "AMBIGUOUS"
    discovered_tx_hash: str | None
    from_block: int
    to_block: int
    requests_count: int
    candidate_logs_count: int
    matched_log: dict[str, Any] | None = None
    error_message: str | None = None


def discover_cctp_destination_message(
    rpc_caller: Callable[[str, list[Any]], dict[str, Any]],
    *,
    expected_nonce: str,
    source_domain: int = 0,
    target_contract: str | None = None,
    from_block: int = 51826900,
    to_block: int = 51826935,
    span: int = 5,
) -> DestinationDiscoveryResult:
    """Bounded, reproducible discovery of the destination MessageReceived log on Base.

    Queries eth_getLogs in bounded chunks (respecting provider range limits)
    filtered by MessageTransmitterV2 address, MessageReceived topic0, and expected bytes32 nonce.
    Verifies that the decoded sourceDomain matches the source domain.
    """
    contract_addr = (
        target_contract
        if target_contract is not None
        else get_cctp_contract("base", "MessageTransmitterV2")
    ).lower()

    clean_nonce = (
        expected_nonce
        if expected_nonce.startswith(("0x", "0X"))
        else "0x" + expected_nonce
    )

    req_count = 0
    candidate_logs: list[dict[str, Any]] = []

    curr = from_block
    while curr <= to_block:
        chunk_to = min(curr + span - 1, to_block)
        req_count += 1
        params = [
            {
                "address": contract_addr,
                "topics": [MESSAGE_RECEIVED_V2_TOPIC, None, clean_nonce],
                "fromBlock": hex(curr),
                "toBlock": hex(chunk_to),
            }
        ]
        resp = rpc_caller("eth_getLogs", params)
        logs = resp.get("result", [])
        if isinstance(logs, list):
            for log in logs:
                if (log.get("address") or "").lower() != contract_addr:
                    continue
                topics = log.get("topics") or []
                if len(topics) < 3:
                    continue
                if topics[0].lower() != MESSAGE_RECEIVED_V2_TOPIC.lower():
                    continue
                if topics[2].lower() != clean_nonce.lower():
                    continue
                data_hex = log.get("data", "0x")
                if data_hex.startswith(("0x", "0X")):
                    data_hex = data_hex[2:]
                data_bytes = bytes.fromhex(data_hex)
                src_dom = (
                    int.from_bytes(data_bytes[0:32], "big")
                    if len(data_bytes) >= 32
                    else -1
                )
                if src_dom == source_domain:
                    candidate_logs.append(log)
        curr = chunk_to + 1

    if not candidate_logs:
        return DestinationDiscoveryResult(
            status="NOT_FOUND",
            discovered_tx_hash=None,
            from_block=from_block,
            to_block=to_block,
            requests_count=req_count,
            candidate_logs_count=0,
            error_message=(
                f"No matching MessageReceived event found in blocks {from_block}..{to_block}"
            ),
        )

    tx_hashes = {
        log.get("transactionHash")
        for log in candidate_logs
        if log.get("transactionHash")
    }
    if len(tx_hashes) > 1:
        return DestinationDiscoveryResult(
            status="AMBIGUOUS",
            discovered_tx_hash=None,
            from_block=from_block,
            to_block=to_block,
            requests_count=req_count,
            candidate_logs_count=len(candidate_logs),
            error_message=(
                f"Multiple ambiguous destination transactions found: {tx_hashes}"
            ),
        )

    matched = candidate_logs[0]
    return DestinationDiscoveryResult(
        status="FOUND",
        discovered_tx_hash=matched.get("transactionHash"),
        from_block=from_block,
        to_block=to_block,
        requests_count=req_count,
        candidate_logs_count=len(candidate_logs),
        matched_log=matched,
    )
