"""EVM LIVE validation and its offline RECORDED_PUBLIC replay.

Constraint 1 of Task 05: the replay path must exercise the *real* production
EVM parsing path (``EvmRpcAdapter`` -- JSON-RPC parsing, ERC-20 log decoding,
receipt verification, finality, block/timestamp normalization), not a
``FixtureAdapter`` standing in for it. This module proves exactly that: the
same ``run_validation`` harness used for TRON, pointed at the EVM adapter, then
replayed from its own recorded bundle through that same adapter class with
zero network calls.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import respx

from app.core.settings import AppEnv, DataMode, Settings
from app.services.anchor_import import DisclosureKind, SourceDocument, import_anchors
from app.services.candidate_review import ReviewAction, ReviewRequest, review_candidates
from app.services.live_validation import ValidationRequest, run_validation
from tests.test_evm_adapter import ACCOUNT, PEER_A, RPC_URL, USDT, FakeEthNode, transfer_log

SOURCE_URL = "https://example-exchange.test/proof-of-reserves"


def accepted_label_dir(tmp_path: Path, *, network_key: str = "ethereum") -> Path:
    """A reviewed set holding one accepted, network-scoped claim over ``PEER_A``."""
    data_dir = tmp_path / "data"
    source = tmp_path / "disclosure.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"{network_key},{PEER_A},Example Exchange,exchange,service_control,hot_wallet\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url=SOURCE_URL,
            disclosure_kind=DisclosureKind.signed_address_verification,
            disclosure_date=dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
            retrieved_at=dt.datetime(2026, 9, 19, tzinfo=dt.UTC),
            methodology=f"Signed verification page, {network_key} entry.",
            label_set_version="evm-replay-test",
        ),
        network_key=network_key,
        out_dir=data_dir,
        write=True,
    )
    report = review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key=network_key,
                address=PEER_A,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="Opened the signed verification; the address is listed.",
                evidence_inspected=(SOURCE_URL,),
            )
        ],
        write=True,
    )
    assert not report.refusals
    return data_dir


def live_settings(tmp_path: Path, **overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "app_env": AppEnv.test,
        "data_mode": DataMode.LIVE,
        "secret_key": "test-secret-key-that-is-long-enough-for-the-validator",
        "ethereum_rpc_url": RPC_URL,
    }
    kwargs.update(overrides)
    if "label_dir" not in kwargs:
        kwargs["label_dir"] = str(accepted_label_dir(tmp_path))
    return Settings(**kwargs)  # type: ignore[arg-type]


def build_node() -> tuple[FakeEthNode, str]:
    node = FakeEthNode(latest=200, finalized=190, safe=195)
    tx = "0x" + "70" * 32
    node.logs.append(
        transfer_log(
            block_number=100,
            tx_index=0,
            log_index=0,
            tx_hash=tx,
            frm=ACCOUNT,
            to=PEER_A,
            value=5_000_000,
        )
    )
    node.receipts[tx] = {
        "status": "0x1",
        "blockNumber": hex(100),
        "gasUsed": "0x5208",
        "effectiveGasPrice": "0x3b9aca00",
    }
    return node, tx


def request_for(node: FakeEthNode) -> ValidationRequest:
    return ValidationRequest(
        address=ACCOUNT,
        token_contract=USDT,
        network_key="ethereum",
        asset_decimals=6,
        asset_symbol="USDT",
        analysis_start=dt.datetime.fromtimestamp(node.block_time(0), tz=dt.UTC),
        analysis_cutoff=dt.datetime.fromtimestamp(node.block_time(150), tz=dt.UTC),
        max_requests=80,
        run_id="evm-test-run",
    )


@respx.mock
async def test_evm_live_validation_reaches_accepted_anchor_and_hides_the_rpc_url(
    tmp_path: Path,
) -> None:
    node, _tx = build_node()
    respx.post(RPC_URL).mock(side_effect=node.handle)

    settings = live_settings(tmp_path)
    run = await run_validation(settings, request_for(node), out_root=tmp_path / "live")

    assert run.succeeded
    assert run.trace is not None
    endings = run.trace["branch_endings"]
    assert any(e["endpoint_class"] == "known_service" for e in endings)
    assert len(run.trace["observed_transfers"]) == 1

    manifest = json.loads((run.directory / "manifest.json").read_text())
    dumped = json.dumps(manifest)
    assert RPC_URL not in dumped
    assert manifest["configuration"]["network"] == "ethereum"
    assert manifest["configuration"]["expected_chain_id"] == 1
    assert manifest["configuration"]["observed_chain_id"] == 1
    assert manifest["configuration"]["ethereum_rpc_configured"] is True

    raw_dump = json.dumps(
        [json.loads(p.read_text()) for p in (run.directory / "raw").glob("*.json")]
    )
    assert RPC_URL not in raw_dump
    assert "authorization" not in raw_dump.lower()


@respx.mock
async def test_evm_recorded_replay_uses_the_real_adapter_and_reproduces_the_live_result(
    tmp_path: Path,
) -> None:
    node, _tx = build_node()
    respx.post(RPC_URL).mock(side_effect=node.handle)

    settings = live_settings(tmp_path)
    request = request_for(node)
    live = await run_validation(settings, request, out_root=tmp_path / "live")
    assert live.succeeded
    calls_after_live = len(node.calls)

    replay_settings = live_settings(
        tmp_path,
        data_mode=DataMode.RECORDED_PUBLIC,
        ethereum_rpc_url=None,
        label_dir=str(settings.label_dir),
    )
    replay = await run_validation(
        replay_settings, request, out_root=tmp_path / "replay", replay_from=live.directory / "raw"
    )

    assert replay.succeeded
    assert live.trace is not None and replay.trace is not None
    assert replay.trace["observed_transfers"] == live.trace["observed_transfers"]
    assert replay.trace["branch_endings"] == live.trace["branch_endings"]
    assert replay.trace["scope"]["data_mode"] == "RECORDED_PUBLIC"

    # Zero network calls during replay: the fake node saw nothing further.
    assert len(node.calls) == calls_after_live

    manifest = json.loads((replay.directory / "manifest.json").read_text())
    assert manifest["mode"] == "replay"


@respx.mock
async def test_replay_succeeds_even_when_the_real_rpc_url_is_still_configured(
    tmp_path: Path,
) -> None:
    """Regression: the same ``Settings`` commonly serves both LIVE and
    RECORDED_PUBLIC runs, so ``ethereum_rpc_url`` is often still set during a
    replay. Replay must use a placeholder regardless, or the real endpoint's
    URL path (never ``"/"``) breaks the recorded exchanges' path-based match."""
    node, _tx = build_node()
    respx.post(RPC_URL).mock(side_effect=node.handle)

    settings = live_settings(tmp_path)
    request = request_for(node)
    live = await run_validation(settings, request, out_root=tmp_path / "live")
    assert live.succeeded

    replay_settings = live_settings(
        tmp_path, data_mode=DataMode.RECORDED_PUBLIC, label_dir=str(settings.label_dir)
    )
    assert replay_settings.ethereum_rpc_url == RPC_URL  # deliberately still configured

    replay = await run_validation(
        replay_settings, request, out_root=tmp_path / "replay2", replay_from=live.directory / "raw"
    )
    assert replay.succeeded
    assert replay.trace is not None and live.trace is not None
    assert replay.trace["observed_transfers"] == live.trace["observed_transfers"]
