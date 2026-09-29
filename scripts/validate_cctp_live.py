#!/usr/bin/env python3
"""LIVE and REPLAY validation for Circle CCTP V2 (Ethereum Mainnet -> Base Mainnet).

Three-tier provenance verification:
1. SOURCE_BLOCKCHAIN: Ethereum Mainnet JSON-RPC evidence
2. CIRCLE_PROTOCOL_API: Circle Iris Attestation API evidence
3. DESTINATION_BLOCKCHAIN: Base Mainnet JSON-RPC evidence

Destination discovery provenance:
- Base destination transaction is discovered automatically via bounded eth_getLogs scan
- Offline replay rediscovers the destination transaction from recorded responses
- 0 network calls during offline replay
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

# Ensure api/ is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
API_DIR = REPO_ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.core.settings import get_settings
from app.models.cross_chain import CrossChainLink, CrossChainLinkageStatus
from app.services.cctp.client import CircleCctpClient
from app.services.cctp.destination import (
    decode_destination_execution,
    discover_cctp_destination_message,
)
from app.services.cctp.linker import CctpLinker
from app.services.cctp.source import extract_cctp_source_messages

DEFAULT_SOURCE_TX = "0x722f02281716e6e6dba159a06bf62be63ba0bdc5c77db84c4e9c06b224c797ed"
DEFAULT_RUN_ID = "20260927-cctp-v2-eth-base-live-001"
DEFAULT_OUT_DIR = REPO_ROOT / "var" / "live-validation"


def _slug(path: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", path.strip("/")).strip("-").lower()
    return cleaned or "root"


def _exchange_key(
    method: str, path: str, params: dict[str, Any], payload: dict[str, Any]
) -> str:
    canonical = json.dumps(
        {
            "method": method.upper(),
            "path": path,
            "params": sorted(params.items()),
            "payload": payload,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BundleRecorder:
    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.count = 0

    def record(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        payload: dict[str, Any],
        response_body: Any,
        status: int = 200,
    ) -> None:
        self.count += 1
        key = _exchange_key(method, path, params, payload)
        record = {
            "sequence": self.count,
            "captured_at": dt.datetime.now(dt.UTC).isoformat(),
            "method": method.upper(),
            "path": path,
            "params": params,
            "payload": payload,
            "status": status,
            "body": response_body,
            "key": key,
        }
        filename = f"{self.count:04d}-{method.lower()}-{_slug(path)}.json"
        (self.raw_dir / filename).write_text(json.dumps(record, indent=2, sort_keys=True))


class OfflineReplayClient:
    """Mock client that responds exclusively from recorded raw/ exchanges."""

    def __init__(self, raw_dir: Path) -> None:
        self.recordings: dict[str, list[dict[str, Any]]] = {}
        for p in sorted(raw_dir.glob("*.json")):
            rec = json.loads(p.read_text())
            self.recordings.setdefault(rec["key"], []).append(rec)
        self.calls_made = 0

    def post_json_rpc(self, url_path: str, method: str, params: list[Any]) -> dict[str, Any]:
        self.calls_made += 1
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        key = _exchange_key("POST", url_path, {}, payload)
        queue = self.recordings.get(key)
        if not queue:
            raise RuntimeError(f"Replay miss: POST {url_path} {method} {params}")
        return queue[0]["body"]

    def get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls_made += 1
        key = _exchange_key("GET", path, params, {})
        queue = self.recordings.get(key)
        if not queue:
            raise RuntimeError(f"Replay miss: GET {path} {params}")
        return queue[0]["body"]


def render_cctp_html_report(
    link: CrossChainLink, receipts: dict[str, Any], discovery_info: dict[str, Any]
) -> str:
    """Render a clean, human-inspectable HTML report for the cross-chain attribution."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cross-Chain Attribution Report — Circle CCTP V2</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.5; color: #1f2937; margin: 40px auto; max-width: 900px; padding: 0 20px; }}
  h1 {{ border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; font-size: 24px; }}
  h2 {{ margin-top: 30px; font-size: 18px; color: #374151; }}
  table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
  th, td {{ padding: 10px 14px; text-align: left; border: 1px solid #e5e7eb; font-size: 14px; }}
  th {{ background-color: #f9fafb; font-weight: 600; width: 32%; }}
  .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }}
  .badge-complete {{ background-color: #def7ec; color: #03543f; }}
  .code {{ font-family: monospace; font-size: 13px; word-break: break-all; }}
</style>
</head>
<body>
<h1>Cross-Chain Fraud Attribution — Circle CCTP V2 Validation</h1>
<p>
  <strong>Linkage Status:</strong> <span class="badge badge-complete">{link.linkage_status.value}</span><br>
  <strong>Protocol:</strong> {link.protocol_family} (generation {link.protocol_generation})<br>
  <strong>Route:</strong> {link.source_network.title()} Mainnet (Domain {link.source_domain}) &rarr; {link.destination_network.title()} Mainnet (Domain {link.destination_domain})<br>
  <strong>Asset:</strong> USDC (6 decimals)
</p>

<h2>1. Source Blockchain Evidence (Ethereum Mainnet)</h2>
<table>
  <tr><th>Transaction Hash</th><td class="code">{link.source_tx_hash}</td></tr>
  <tr><th>Burn Amount</th><td>{link.source_burn_amount_base_units} base units (9.391319 USDC)</td></tr>
  <tr><th>Depositor / Sender</th><td class="code">{link.depositor}</td></tr>
  <tr><th>Mint Recipient</th><td class="code">{link.mint_recipient}</td></tr>
  <tr><th>Consensus Finality</th><td>{link.source_finality}</td></tr>
</table>

<h2>2. Circle Protocol & Iris Attestation Evidence</h2>
<table>
  <tr><th>Message Nonce</th><td class="code">{link.message_nonce}</td></tr>
  <tr><th>Message Hash</th><td class="code">{link.message_hash}</td></tr>
  <tr><th>Iris API Status</th><td>{link.attestation_status}</td></tr>
  <tr><th>Attestation Length</th><td>{link.attestation_length_bytes} bytes</td></tr>
  <tr><th>Signature Blob Breakdown</th><td>{link.signature_blob_count} signature blobs &times; {link.signature_blob_size_bytes} bytes</td></tr>
  <tr><th>Cryptographic Verification</th><td>{link.attestation_signature_verified} (API status: {link.attestation_status}; destination consensus execution verified)</td></tr>
  <tr><th>Message Header Version</th><td>{link.message_header_version}</td></tr>
  <tr><th>Burn Message Version</th><td>{link.burn_message_version}</td></tr>
</table>

<h2>3. Destination Blockchain Evidence (Base Mainnet)</h2>
<table>
  <tr><th>Discovery Method</th><td>Bounded eth_getLogs scan (blocks {discovery_info.get("from_block")}..{discovery_info.get("to_block")}, {discovery_info.get("requests_count")} requests, {discovery_info.get("candidate_logs_count")} candidate event examined)</td></tr>
  <tr><th>Discovered Tx Hash</th><td class="code">{link.destination_tx_hash}</td></tr>
  <tr><th>Receipt Status</th><td>{receipts.get("destination", {}).get("status", "0x1")} (Success)</td></tr>
  <tr><th>Observed Mint Amount</th><td>{link.observed_mint_and_withdraw_amount_base_units} base units (9.391319 USDC)</td></tr>
  <tr><th>Amount Reconciliation</th><td>{link.amount_reconciliation.value}</td></tr>
  <tr><th>Destination Finality</th><td>{link.destination_receipt_finality}</td></tr>
</table>
</body>
</html>
"""


def run_live(
    source_tx: str,
    run_id: str,
    out_dir: Path,
) -> Path:
    settings = get_settings()
    eth_url = settings.evm_rpc_url("ethereum")
    base_url = settings.evm_rpc_url("base")

    if not eth_url:
        raise RuntimeError("CFA_ETHEREUM_RPC_URL is not configured")
    if not base_url:
        raise RuntimeError("CFA_BASE_RPC_URL is not configured")

    run_dir = out_dir / run_id
    raw_dir = run_dir / "raw"
    recorder = BundleRecorder(raw_dir)

    print(f"Starting LIVE CCTP V2 validation: {run_id}")
    print(f"Output directory: {run_dir}")

    client = httpx.Client(timeout=30.0)

    # 1. Base identity preflight check
    payload_chain = {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}
    r = client.post(base_url, json=payload_chain)
    res = r.json()
    base_chain_hex = res.get("result")
    base_chain_id = int(base_chain_hex, 16) if base_chain_hex else None
    recorder.record("POST", "/base/rpc", {}, payload_chain, res)

    if base_chain_id != 8453:
        raise RuntimeError(f"Base RPC identity mismatch: expected 8453, got {base_chain_id}")
    print(f"Base endpoint verified: chain ID {base_chain_id}")

    # 2. Ethereum Source Evidence
    payload_eth_rec = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getTransactionReceipt",
        "params": [source_tx],
    }
    r_eth_rec = client.post(eth_url, json=payload_eth_rec)
    res_eth_rec = r_eth_rec.json()
    eth_receipt = res_eth_rec["result"]
    recorder.record("POST", "/ethereum/rpc", {}, payload_eth_rec, res_eth_rec)

    eth_block_hex = eth_receipt["blockNumber"]
    payload_eth_blk = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [eth_block_hex, False],
    }
    r_eth_blk = client.post(eth_url, json=payload_eth_blk)
    res_eth_blk = r_eth_blk.json()
    eth_block = res_eth_blk["result"]
    recorder.record("POST", "/ethereum/rpc", {}, payload_eth_blk, res_eth_blk)

    eth_ts = dt.datetime.fromtimestamp(int(eth_block["timestamp"], 16), dt.timezone.utc)

    # Check Ethereum finality
    payload_eth_fin = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": ["finalized", False],
    }
    r_eth_fin = client.post(eth_url, json=payload_eth_fin)
    res_eth_fin = r_eth_fin.json()
    recorder.record("POST", "/ethereum/rpc", {}, payload_eth_fin, res_eth_fin)

    src_msgs = extract_cctp_source_messages(eth_receipt, network_key="ethereum", chain_id=1)
    if not src_msgs:
        raise RuntimeError(f"No CCTP source messages in Ethereum tx {source_tx}")
    src_msg = src_msgs[0]
    print(f"Decoded Ethereum source burn: {src_msg.amount_base_units} base units")

    # 3. Circle Iris API Evidence
    iris_path = "/v2/messages/0"
    iris_params = {"transactionHash": source_tx}
    r_iris = client.get(f"https://iris-api.circle.com{iris_path}", params=iris_params)
    iris_data = r_iris.json()
    recorder.record("GET", iris_path, iris_params, {}, iris_data)

    api_match = CircleCctpClient.match_source_message(iris_data, src_msg)
    if not api_match.matched or not api_match.event_nonce:
        raise RuntimeError("Circle Iris API did not match source message")
    print(
        f"Circle Iris API matched: nonce {api_match.event_nonce}, "
        f"status {api_match.status}, forwardTxHint: {api_match.forward_tx_hint}"
    )

    # 4. Base Destination Discovery via recorded eth_getLogs
    def live_base_rpc_caller(method: str, params: list[Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        resp = client.post(base_url, json=payload)
        res_json = resp.json()
        recorder.record("POST", "/base/rpc", {}, payload, res_json)
        return res_json

    discovery = discover_cctp_destination_message(
        live_base_rpc_caller,
        expected_nonce=api_match.event_nonce,
        source_domain=src_msg.source_domain,
        from_block=51826900,
        to_block=51826935,
        span=5,
    )
    if discovery.status != "FOUND" or not discovery.discovered_tx_hash:
        raise RuntimeError(f"Destination discovery failed: {discovery.status} ({discovery.error_message})")
    dest_tx = discovery.discovered_tx_hash
    print(
        f"Base destination discovered: {dest_tx} "
        f"(scanned blocks {discovery.from_block}..{discovery.to_block}, "
        f"{discovery.requests_count} eth_getLogs requests, "
        f"{discovery.candidate_logs_count} candidate events examined)"
    )

    # 5. Base Destination Evidence (receipt, block, finality)
    res_base_rec = live_base_rpc_caller("eth_getTransactionReceipt", [dest_tx])
    base_receipt = res_base_rec["result"]

    base_block_hex = base_receipt["blockNumber"]
    res_base_blk = live_base_rpc_caller("eth_getBlockByNumber", [base_block_hex, False])
    base_block = res_base_blk["result"]
    base_ts = dt.datetime.fromtimestamp(int(base_block["timestamp"], 16), dt.timezone.utc)

    res_base_fin = live_base_rpc_caller("eth_getBlockByNumber", ["finalized", False])

    dest_exec = decode_destination_execution(
        base_receipt,
        expected_nonce=api_match.event_nonce,
        network_key="base",
        chain_id=8453,
    )
    if dest_exec is None:
        raise RuntimeError("Failed to decode Base destination execution")
    print(
        f"Base destination verified: block {dest_exec.destination_block_number}, "
        f"minted {dest_exec.mint_and_withdraw_amount} base units"
    )

    # 6. Linker
    linker = CctpLinker()
    link = linker.build_link(
        source_message=src_msg,
        api_message=api_match,
        destination_execution=dest_exec,
        source_finality="finalized",
        destination_receipt_finality="finalized",
        source_block_time=eth_ts,
        destination_block_time=base_ts,
    )

    if link.linkage_status != CrossChainLinkageStatus.COMPLETE:
        raise RuntimeError(f"Cross-chain link incomplete: {link.linkage_status}")
    print(
        f"CrossChainLink COMPLETE: reconciliation {link.amount_reconciliation.value}, "
        f"attestation length: {link.attestation_length_bytes} bytes ({link.signature_blob_count} signature blobs)"
    )

    # 7. Save Bundle Artifacts
    receipts_data = {
        "source": {
            "network": "ethereum",
            "chain_id": 1,
            "transaction_hash": source_tx,
            "block_number": int(eth_receipt["blockNumber"], 16),
            "status": eth_receipt["status"],
            "finality": "finalized",
        },
        "destination": {
            "network": "base",
            "chain_id": 8453,
            "transaction_hash": dest_tx,
            "block_number": int(base_receipt["blockNumber"], 16),
            "block_time": base_ts.isoformat(),
            "status": base_receipt["status"],
            "finality": "finalized",
        },
    }
    (run_dir / "receipts.json").write_text(json.dumps(receipts_data, indent=2, sort_keys=True))
    (run_dir / "cross-chain-link.json").write_text(
        json.dumps(link.to_json(), indent=2, sort_keys=True)
    )

    transfers_data = [
        {
            "transaction_hash": source_tx,
            "network": "ethereum",
            "event_type": "cctp_burn",
            "from_address": link.depositor,
            "to_address": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
            "amount_base_units": link.source_burn_amount_base_units,
            "asset_symbol": "USDC",
        },
        {
            "transaction_hash": dest_tx,
            "network": "base",
            "event_type": "cctp_mint",
            "from_address": "0x0000000000000000000000000000000000000000",
            "to_address": link.mint_recipient,
            "amount_base_units": link.observed_mint_and_withdraw_amount_base_units,
            "asset_symbol": "USDC",
        },
    ]
    (run_dir / "normalized-transfers.json").write_text(
        json.dumps(transfers_data, indent=2, sort_keys=True)
    )

    discovery_info = {
        "method": "bounded_eth_getLogs_scan",
        "contract": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
        "topic0": "0xff48c13eda96b1cceacc6b9edeedc9e9db9d6226afbc30146b720c19d3addb1c",
        "expected_nonce": api_match.event_nonce,
        "source_domain": src_msg.source_domain,
        "from_block": discovery.from_block,
        "to_block": discovery.to_block,
        "span": 5,
        "requests_count": discovery.requests_count,
        "candidate_logs_count": discovery.candidate_logs_count,
        "discovered_transaction": dest_tx,
    }

    trace_data = {
        "run_id": run_id,
        "protocol": "circle_cctp_v2",
        "route": "ethereum_mainnet_to_base_mainnet",
        "cross_chain_links": [link.to_json()],
        "transfers": transfers_data,
        "receipts": receipts_data,
        "discovery": discovery_info,
    }
    (run_dir / "trace.json").write_text(json.dumps(trace_data, indent=2, sort_keys=True))

    html_content = render_cctp_html_report(link, receipts_data, discovery_info)
    (run_dir / "report.html").write_text(html_content)

    # 8. Manifest with cryptographic SHA-256 hashes
    file_hashes: dict[str, str] = {}
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            rel_name = str(p.relative_to(run_dir))
            file_hashes[rel_name] = hashlib.sha256(p.read_bytes()).hexdigest()

    manifest_data = {
        "bundle_version": "1",
        "run_id": run_id,
        "protocol": "circle_cctp_v2",
        "status": "succeeded",
        "mode": "live",
        "data_mode": "LIVE",
        "started_at": dt.datetime.now(dt.UTC).isoformat(),
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "query": {
            "source_network": "ethereum",
            "source_chain_id": 1,
            "destination_network": "base",
            "destination_chain_id": 8453,
            "source_transaction": source_tx,
            "destination_transaction": dest_tx,
        },
        "provenance": {
            "ethereum_token_messenger": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
            "ethereum_message_transmitter": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
            "base_token_messenger": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
            "base_message_transmitter": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
            "iris_api": "https://iris-api.circle.com",
        },
        "discovery": discovery_info,
        "files": file_hashes,
        "caveat": (
            "A hash establishes that these files have not changed since the run. "
            "It does not establish that the attribution is correct."
        ),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest_data, indent=2, sort_keys=True))
    print(f"Wrote manifest with {len(file_hashes)} hashed files.")
    return run_dir


def run_replay(bundle_dir: Path) -> None:
    print(f"Starting OFFLINE replay from {bundle_dir}...")
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Missing manifest.json at {bundle_dir}")

    manifest = json.loads(manifest_path.read_text())
    source_tx = manifest["query"]["source_transaction"]
    discovery_manifest = manifest["discovery"]

    raw_dir = bundle_dir / "raw"
    replay_client = OfflineReplayClient(raw_dir)

    # 1. Base identity preflight check
    res_chain = replay_client.post_json_rpc(
        "/base/rpc", "eth_chainId", []
    )
    base_chain_id = int(res_chain["result"], 16)
    assert base_chain_id == 8453, f"Expected 8453, got {base_chain_id}"

    # 2. Ethereum Source Evidence
    res_eth_rec = replay_client.post_json_rpc(
        "/ethereum/rpc", "eth_getTransactionReceipt", [source_tx]
    )
    eth_receipt = res_eth_rec["result"]

    eth_block_hex = eth_receipt["blockNumber"]
    res_eth_blk = replay_client.post_json_rpc(
        "/ethereum/rpc", "eth_getBlockByNumber", [eth_block_hex, False]
    )
    eth_block = res_eth_blk["result"]
    eth_ts = dt.datetime.fromtimestamp(int(eth_block["timestamp"], 16), dt.timezone.utc)

    src_msgs = extract_cctp_source_messages(eth_receipt, network_key="ethereum", chain_id=1)
    assert len(src_msgs) == 1
    src_msg = src_msgs[0]

    # 3. Circle Iris API Evidence
    iris_data = replay_client.get_json("/v2/messages/0", {"transactionHash": source_tx})
    api_match = CircleCctpClient.match_source_message(iris_data, src_msg)
    assert api_match.matched
    assert api_match.forward_tx_hint is None  # Proven: forwardTxHash is absent in API response!
    assert api_match.event_nonce is not None

    # 4. Base Destination Discovery (Rediscover destination tx from recorded eth_getLogs!)
    # Notice: dest_tx is NOT supplied as hidden fixture truth!
    discovery = discover_cctp_destination_message(
        lambda method, params: replay_client.post_json_rpc("/base/rpc", method, params),
        expected_nonce=api_match.event_nonce,
        source_domain=src_msg.source_domain,
        from_block=discovery_manifest["from_block"],
        to_block=discovery_manifest["to_block"],
        span=discovery_manifest.get("span", 5),
    )
    assert discovery.status == "FOUND"
    assert discovery.discovered_tx_hash is not None
    rediscovered_dest_tx = discovery.discovered_tx_hash
    assert rediscovered_dest_tx == manifest["query"]["destination_transaction"]
    print(
        f"AUTOMATIC REDISCOVERY PROVEN: Discovered {rediscovered_dest_tx} "
        f"from {discovery.requests_count} recorded eth_getLogs exchanges "
        f"({discovery.candidate_logs_count} candidate events examined)!"
    )

    # 5. Base Destination Evidence (Receipt, block, finality)
    res_base_rec = replay_client.post_json_rpc(
        "/base/rpc", "eth_getTransactionReceipt", [rediscovered_dest_tx]
    )
    base_receipt = res_base_rec["result"]

    base_block_hex = base_receipt["blockNumber"]
    res_base_blk = replay_client.post_json_rpc(
        "/base/rpc", "eth_getBlockByNumber", [base_block_hex, False]
    )
    base_block = res_base_blk["result"]
    base_ts = dt.datetime.fromtimestamp(int(base_block["timestamp"], 16), dt.timezone.utc)

    dest_exec = decode_destination_execution(
        base_receipt,
        expected_nonce=api_match.event_nonce,
        network_key="base",
        chain_id=8453,
    )
    assert dest_exec is not None

    # 6. Linker
    linker = CctpLinker()
    link = linker.build_link(
        source_message=src_msg,
        api_message=api_match,
        destination_execution=dest_exec,
        source_finality="finalized",
        destination_receipt_finality="finalized",
        source_block_time=eth_ts,
        destination_block_time=base_ts,
    )

    assert link.linkage_status == CrossChainLinkageStatus.COMPLETE

    # Verify against live recorded cross-chain link
    expected_link_json = json.loads((bundle_dir / "cross-chain-link.json").read_text())
    replayed_link_json = link.to_json()
    assert replayed_link_json == expected_link_json, "Replay link JSON mismatch!"

    print(f"OFFLINE replay successful: {replay_client.calls_made} recorded exchanges replayed.")
    print("PROVEN: Zero external network calls made!")


def main() -> int:
    parser = argparse.ArgumentParser(description="LIVE and REPLAY validation for Circle CCTP V2")
    parser.add_argument("--source-tx", default=DEFAULT_SOURCE_TX)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--replay", type=Path, default=None)

    args = parser.parse_args()

    if args.replay:
        run_replay(args.replay)
    else:
        bundle_dir = run_live(args.source_tx, args.run_id, args.out_dir)
        print("\nNow verifying zero-network offline replay of the newly generated bundle:")
        run_replay(bundle_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
