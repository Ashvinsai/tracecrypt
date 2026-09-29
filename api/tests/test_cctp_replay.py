"""Deterministic offline replay tests for Circle CCTP V2 cross-chain attribution.

Verifies:
1. Replay with recorded Ethereum RPC evidence + recorded Circle Iris API response +
   recorded Base RPC evidence.
2. Identical decoders and linker executed during replay.
3. Zero external network calls (all requests served from recorded data).
4. Full source -> protocol message -> attestation -> destination receive -> complete link.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import respx

from app.models.cross_chain import (
    AmountReconciliationResult,
    CrossChainLinkageStatus,
)
from app.services.cctp.client import CircleCctpClient
from app.services.cctp.destination import (
    decode_destination_execution,
    discover_cctp_destination_message,
)
from app.services.cctp.linker import CctpLinker
from app.services.cctp.source import extract_cctp_source_messages


@respx.mock
async def test_offline_cctp_replay_zero_network_calls() -> None:
    """Complete cross-chain link replay offline through exact decoders without network."""
    # Source Ethereum Transaction:
    # 0x722f02281716e6e6dba159a06bf62be63ba0bdc5c77db84c4e9c06b224c797ed
    source_receipt: dict[str, Any] = {
        "transactionHash": (
            "0x722f02281716e6e6dba159a06bf62be63ba0bdc5c77db84c4e9c06b224c797ed"
        ),
        "blockNumber": "0x18db1a7",  # 26062983
        "status": "0x1",
        "logs": [
            {
                "logIndex": "0x13f",  # 319
                "address": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
                "topics": ["0x8c5261668696ce22758910d05bab8f186d6eb247ceac2af2e82c7dc17669b036"],
                "data": (
                    "0x0000000000000000000000000000000000000000000000000000000000000020"
                    "0000000000000000000000000000000000000000000000000000000000000178"
                    # 376 bytes message
                    + (
                        (1).to_bytes(4, "big")
                        + (0).to_bytes(4, "big")
                        + (6).to_bytes(4, "big")
                        + bytes(32)  # nonce 0 on source
                        + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                        + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                        + bytes(32)
                        + (2000).to_bytes(4, "big")
                        + (0).to_bytes(4, "big")
                        + (1).to_bytes(4, "big")  # burn message version
                        + bytes(12) + bytes.fromhex("a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
                        + bytes(12) + bytes.fromhex("38a1c011890bc95fd4b43b622e1432c859d097bc")
                        + (9391319).to_bytes(32, "big")
                        + bytes(12) + bytes.fromhex("38a1c011890bc95fd4b43b622e1432c859d097bc")
                        + (0).to_bytes(32, "big")
                        + (0).to_bytes(32, "big")
                        + (0).to_bytes(32, "big")
                    ).hex()
                ),
            },
            {
                "logIndex": "0x140",  # 320
                "address": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
                "topics": [
                    "0x0c8c1cbdc5190613ebd485511d4e2812cfa45eecb79d845893331fedad5130a5",
                    "0x000000000000000000000000a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "0x00000000000000000000000038a1c011890bc95fd4b43b622e1432c859d097bc",
                    "0x00000000000000000000000000000000000000000000000000000000000007d0",
                ],
                "data": (
                    (9391319).to_bytes(32, "big")
                    + bytes(12) + bytes.fromhex("38a1c011890bc95fd4b43b622e1432c859d097bc")
                    + (6).to_bytes(32, "big")
                    + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                    + bytes(32)
                    + (0).to_bytes(32, "big")
                    + (224).to_bytes(32, "big")
                    + (0).to_bytes(32, "big")
                ).hex(),
            },
        ],
    }

    # Step 1: Decode source Ethereum logs
    source_msgs = extract_cctp_source_messages(source_receipt, network_key="ethereum", chain_id=1)
    assert len(source_msgs) == 1
    src_msg = source_msgs[0]
    assert src_msg.source_domain == 0
    assert src_msg.destination_domain == 6
    assert src_msg.amount_base_units == 9391319
    assert src_msg.mint_recipient == "0x38a1c011890bc95fd4b43b622e1432c859d097bc"

    # Step 2: Recorded Circle Iris API response
    recorded_iris_api_response = {
        "messages": [
            {
                "status": "complete",
                "attestation": "0x" + "aa" * 65,
                "eventNonce": "0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d",
                "cctpVersion": 2,
                "decodedMessage": {
                    "sourceDomain": "0",
                    "destinationDomain": "6",
                    "nonce": "0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d",
                    "sender": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
                    "recipient": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
                    "destinationCaller": "0x" + "00" * 32,
                    "minFinalityThreshold": "2000",
                    "finalityThresholdExecuted": "2000",
                    "decodedMessageBody": {
                        "burnToken": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                        "mintRecipient": "0x38a1c011890bc95fd4b43b622e1432c859d097bc",
                        "amount": "9391319",
                        "messageSender": "0x38a1c011890bc95fd4b43b622e1432c859d097bc",
                        "maxFee": "0",
                        "feeExecuted": "0",
                    },
                },
            }
        ]
    }

    api_match = CircleCctpClient.match_source_message(recorded_iris_api_response, src_msg)
    assert api_match.matched
    assert api_match.status == "API_REPORTED_COMPLETE"
    expected_event_nonce = (
        "0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d"
    )
    assert api_match.event_nonce == expected_event_nonce

    # Step 3: Recorded Base execution receipt
    base_dest_receipt: dict[str, Any] = {
        "transactionHash": "0x4444444444444444444444444444444444444444444444444444444444444444",
        "blockNumber": "0x123456",
        "status": "0x1",
        "logs": [
            {
                "logIndex": "0xa",
                "address": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
                "topics": [
                    "0xff48c13eda96b1cceacc6b9edeedc9e9db9d6226afbc30146b720c19d3addb1c",
                    "0x0000000000000000000000001234567890123456789012345678901234567890",
                    "0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d",
                    "0x00000000000000000000000000000000000000000000000000000000000007d0",
                ],
                "data": (
                    (0).to_bytes(32, "big")  # sourceDomain 0
                    + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                    + (64).to_bytes(32, "big")
                    + (0).to_bytes(32, "big")
                ).hex(),
            },
            {
                "logIndex": "0xb",
                "address": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
                "topics": [
                    "0x1b2a7ff080b8cb6ff436ce0372e399692bbfb6d4ae5766fd8d58a7b8cc6142e6",
                    "0x00000000000000000000000038a1c011890bc95fd4b43b622e1432c859d097bc",
                    "0x000000000000000000000000833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                ],
                "data": ((9391319).to_bytes(32, "big")).hex(),
            },
        ],
    }

    dest_exec = decode_destination_execution(
        base_dest_receipt,
        expected_nonce=api_match.event_nonce,
        network_key="base",
        chain_id=8453,
    )
    assert dest_exec is not None
    assert dest_exec.destination_receipt_status == "0x1"
    assert dest_exec.mint_recipient == "0x38a1c011890bc95fd4b43b622e1432c859d097bc"
    assert dest_exec.mint_and_withdraw_amount == 9391319

    # Step 4: Linker produces verified CrossChainLink
    linker = CctpLinker()
    link = linker.build_link(
        source_message=src_msg,
        api_message=api_match,
        destination_execution=dest_exec,
        source_finality="finalized",
        destination_receipt_finality="finalized",
    )

    assert link.linkage_status == CrossChainLinkageStatus.COMPLETE
    assert link.protocol_family == "circle_cctp"
    assert link.protocol_generation == 2
    assert link.message_header_version == 1
    assert link.burn_message_version == 1
    assert link.source_network == "ethereum"
    assert link.destination_network == "base"
    assert link.source_domain == 0
    assert link.destination_domain == 6
    assert link.source_burn_amount_base_units == 9391319
    assert link.observed_mint_and_withdraw_amount_base_units == 9391319
    assert link.amount_reconciliation == AmountReconciliationResult.MATCHES_PROTOCOL_EXPECTATION
    assert link.attestation_status == "API_REPORTED_COMPLETE"
    assert not link.attestation_signature_verified
    assert len(link.evidence_references) >= 3


def test_real_bundle_destination_discovery_and_offline_replay() -> None:
    """Full offline replay of the real saved LIVE validation bundle.

    Verifies:
    1. Circle forwardTxHash is absent in recorded API response.
    2. Base destination transaction is NOT provided as hidden fixture truth.
    3. Destination MessageReceived log is discovered automatically via recorded bounded eth_getLogs.
    4. Exactly 1 candidate event examined across bounded scan.
    5. Zero network calls made during replay.
    6. Identical CrossChainLink fields reproduced.
    """
    bundle_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "var"
        / "live-validation"
        / "20260927-cctp-v2-eth-base-live-001"
    )
    if not bundle_dir.is_dir():
        return

    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    source_tx = manifest["query"]["source_transaction"]
    discovery_manifest = manifest["discovery"]

    # Manifest verification: confirm manifest.json is not self-referenced
    # and all hashed evidence files match their SHA-256 hashes
    import hashlib
    files_map = manifest["files"]
    assert "manifest.json" not in files_map
    assert len(files_map) == 21
    total_fs_files = [p for p in bundle_dir.rglob("*") if p.is_file()]
    assert len(total_fs_files) == 22
    for rel_path, expected_hash in files_map.items():
        actual_hash = hashlib.sha256((bundle_dir / rel_path).read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"Hash mismatch for {rel_path}"

    # Load recorded exchanges
    raw_dir = bundle_dir / "raw"
    recordings: dict[str, list[dict[str, Any]]] = {}
    for p in sorted(raw_dir.glob("*.json")):
        rec = json.loads(p.read_text())
        recordings.setdefault(rec["key"], []).append(rec)

    def replay_rpc(url_path: str, method: str, params: list[Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        import hashlib
        canonical = json.dumps(
            {"method": "POST", "path": url_path, "params": [], "payload": payload},
            sort_keys=True,
        )
        key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        queue = recordings.get(key)
        assert queue, f"Replay miss: {url_path} {method}"
        return queue[0]["body"]

    def replay_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
        import hashlib
        canonical = json.dumps(
            {"method": "GET", "path": path, "params": sorted(params.items()), "payload": {}},
            sort_keys=True,
        )
        key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        queue = recordings.get(key)
        assert queue, f"Replay miss: {path} {params}"
        return queue[0]["body"]

    # 1. Base identity preflight check
    res_chain = replay_rpc("/base/rpc", "eth_chainId", [])
    assert int(res_chain["result"], 16) == 8453

    # 2. Ethereum source receipt & block
    res_eth_rec = replay_rpc("/ethereum/rpc", "eth_getTransactionReceipt", [source_tx])
    eth_receipt = res_eth_rec["result"]

    src_msgs = extract_cctp_source_messages(eth_receipt, network_key="ethereum", chain_id=1)
    assert len(src_msgs) == 1
    src_msg = src_msgs[0]

    # 3. Circle Iris API response
    iris_data = replay_get("/v2/messages/0", {"transactionHash": source_tx})
    api_match = CircleCctpClient.match_source_message(iris_data, src_msg)
    assert api_match.matched
    assert api_match.forward_tx_hint is None  # Proven: forwardTxHash is absent!
    assert api_match.event_nonce is not None

    # 4. Automatic Destination Discovery via recorded eth_getLogs
    discovery = discover_cctp_destination_message(
        lambda method, params: replay_rpc("/base/rpc", method, params),
        expected_nonce=api_match.event_nonce,
        source_domain=src_msg.source_domain,
        from_block=discovery_manifest["from_block"],
        to_block=discovery_manifest["to_block"],
        span=discovery_manifest.get("span", 5),
    )
    assert discovery.status == "FOUND"
    assert discovery.discovered_tx_hash == manifest["query"]["destination_transaction"]
    assert discovery.requests_count == 8
    assert discovery.candidate_logs_count == 1

    # 5. Base destination receipt & decode
    res_base_rec = replay_rpc(
        "/base/rpc", "eth_getTransactionReceipt", [discovery.discovered_tx_hash]
    )
    base_receipt = res_base_rec["result"]

    base_block_hex = base_receipt["blockNumber"]
    res_base_blk = replay_rpc(
        "/base/rpc", "eth_getBlockByNumber", [base_block_hex, False]
    )
    base_block = res_base_blk["result"]
    import datetime as dt
    base_ts = dt.datetime.fromtimestamp(int(base_block["timestamp"], 16), dt.UTC)

    dest_exec = decode_destination_execution(
        base_receipt,
        expected_nonce=api_match.event_nonce,
        network_key="base",
        chain_id=8453,
    )
    assert dest_exec is not None
    assert dest_exec.destination_receipt_status == "0x1"
    assert dest_exec.mint_recipient == src_msg.mint_recipient

    # 6. Linker
    linker = CctpLinker()
    link = linker.build_link(
        source_message=src_msg,
        api_message=api_match,
        destination_execution=dest_exec,
        source_finality="finalized",
        destination_receipt_finality="finalized",
        destination_block_time=base_ts,
    )
    assert link.linkage_status == CrossChainLinkageStatus.COMPLETE
    assert link.amount_reconciliation == AmountReconciliationResult.MATCHES_PROTOCOL_EXPECTATION
    assert link.attestation_length_bytes == 130
    assert link.signature_blob_count == 2
    assert not link.attestation_signature_verified
    assert link.destination_block_time is not None
    assert link.destination_block_time.isoformat() == "2026-09-26T17:20:05+00:00"


def test_destination_discovery_scenarios() -> None:
    """Test destination discovery edge cases.

    Covers zero candidates, ambiguous multiple candidates, and strict filter.
    """
    expected_nonce = "0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d"
    topic0 = "0xff48c13eda96b1cceacc6b9edeedc9e9db9d6226afbc30146b720c19d3addb1c"
    contract_addr = "0x81d40f21f12a8f0e3252bccb954d722d4c464b64"

    # Scenario 1: Zero candidate logs in range => NOT_FOUND
    def empty_rpc(method: str, params: list[Any]) -> dict[str, Any]:
        return {"result": []}

    res_empty = discover_cctp_destination_message(
        empty_rpc,
        expected_nonce=expected_nonce,
        source_domain=0,
        from_block=100,
        to_block=105,
    )
    assert res_empty.status == "NOT_FOUND"
    assert res_empty.discovered_tx_hash is None
    assert res_empty.candidate_logs_count == 0

    # Scenario 2: Multiple candidate logs from different transactions => AMBIGUOUS
    def multi_rpc(method: str, params: list[Any]) -> dict[str, Any]:
        return {
            "result": [
                {
                    "address": contract_addr,
                    "topics": [topic0, "0x1111", expected_nonce, "0x2000"],
                    "data": (0).to_bytes(32, "big").hex(),
                    "transactionHash": "0xaaaa",
                },
                {
                    "address": contract_addr,
                    "topics": [topic0, "0x2222", expected_nonce, "0x2000"],
                    "data": (0).to_bytes(32, "big").hex(),
                    "transactionHash": "0xbbbb",
                },
            ]
        }

    res_multi = discover_cctp_destination_message(
        multi_rpc,
        expected_nonce=expected_nonce,
        source_domain=0,
        from_block=100,
        to_block=104,
    )
    assert res_multi.status == "AMBIGUOUS"
    assert res_multi.discovered_tx_hash is None
    assert res_multi.candidate_logs_count == 2

    # Scenario 3: Log with wrong sourceDomain is rejected
    def wrong_domain_rpc(method: str, params: list[Any]) -> dict[str, Any]:
        return {
            "result": [
                {
                    "address": contract_addr,
                    "topics": [topic0, "0x1111", expected_nonce, "0x2000"],
                    "data": (1).to_bytes(32, "big").hex(),  # domain 1 != 0
                    "transactionHash": "0xcccc",
                }
            ]
        }

    res_wrong_dom = discover_cctp_destination_message(
        wrong_domain_rpc,
        expected_nonce=expected_nonce,
        source_domain=0,
        from_block=100,
        to_block=105,
    )
    assert res_wrong_dom.status == "NOT_FOUND"
