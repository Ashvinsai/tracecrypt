"""Task 06: a second EVM network (BNB Smart Chain) on the same generic adapter.

Covers what is *not* per-network behavior of ``EvmRpcAdapter`` (that is
parametrized over every network in ``test_evm_adapter.py``): the registry
itself, network-specific RPC configuration that must never cross over,
chain-id refusal in both directions, event identity across networks, label
isolation across networks, capability reporting, and replay network
selection from saved evidence.

No real RPC URL is ever read: every ``Settings`` here is built with
``_env_file=None`` and the RPC variables removed from the environment, so a
developer's local ``api/.env`` can neither leak into nor satisfy a test.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import respx

from app.adapters.base import AssetRef, Direction, ProviderError, ProviderErrorClass
from app.adapters.evm import BLOCK_RESOLUTION_CURRENT, BLOCK_RESOLUTION_LEGACY, EvmRpcAdapter
from app.core.settings import AppEnv, DataMode, Settings
from app.services import live_validation, trace_service
from app.services.live_validation import LiveValidationError, ValidationRequest, run_validation
from app.services.operational_status import build_capabilities
from app.services.trace_service import TraceUnavailable
from tests.test_evm_adapter import (
    ACCOUNT,
    CUTOFF,
    PEER_A,
    RPC_URL,
    USDT,
    FakeEthNode,
    transfer_log,
)
from tests.test_evm_replay import accepted_label_dir

NETWORK_CHAIN_IDS = {"ethereum": 1, "bsc": 56}
ETH_URL = "https://eth.example.test/v1/eth-only-key"
BSC_URL = "https://bsc.example.test/v1/bsc-only-key"
SECRET_RPC_URL = "https://provider.example/v2/SECRET_KEY?token=ANOTHER_SECRET"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_rpc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CFA_ETHEREUM_RPC_URL", "CFA_BSC_RPC_URL"):
        monkeypatch.delenv(name, raising=False)


def make_settings(**overrides: Any) -> Settings:
    kwargs: dict[str, Any] = {
        "app_env": AppEnv.test,
        "data_mode": DataMode.LIVE,
        "secret_key": "test-secret-key-that-is-long-enough-for-the-validator",
    }
    kwargs.update(overrides)
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


# -- registry and identity ----------------------------------------------------


def test_bsc_is_a_registry_entry_on_the_same_adapter_class() -> None:
    from app.adapters.evm import EVM_NETWORKS

    bsc = EVM_NETWORKS["bsc"]
    assert bsc.chain_id == 56
    assert bsc.caip2 == "eip155:56"
    assert bsc.native_symbol == "BNB"
    assert bsc.rpc_setting == "bsc_rpc_url"
    assert EVM_NETWORKS["ethereum"].rpc_setting == "ethereum_rpc_url"
    assert EVM_NETWORKS["ethereum"].caip2 == "eip155:1"
    assert type(EvmRpcAdapter(RPC_URL, network_key="bsc")) is EvmRpcAdapter


@pytest.mark.parametrize(
    ("expected_network", "reported_chain_id"),
    [("bsc", 1), ("ethereum", 56)],
)
@respx.mock
async def test_endpoint_reporting_the_other_evm_chain_is_refused(
    expected_network: str, reported_chain_id: int
) -> None:
    node = FakeEthNode(chain_id=reported_chain_id)
    respx.post(RPC_URL).mock(side_effect=node.handle)
    a = EvmRpcAdapter(RPC_URL, network_key=expected_network)
    with pytest.raises(ProviderError) as exc_info:
        await a.fetch_transfers(
            address=ACCOUNT,
            asset=AssetRef(expected_network, USDT, 6, "USDT"),
            direction=Direction.outgoing,
            analysis_cutoff=CUTOFF,
        )
    assert exc_info.value.error_class is ProviderErrorClass.unsupported
    assert a.observed_chain_id == reported_chain_id
    assert [c for c in node.calls if c[0] != "eth_chainId"] == []


@respx.mock
async def test_same_tx_hash_and_log_index_differ_across_networks() -> None:
    tx = "0x" + "81" * 32
    references = {}
    for key in ("ethereum", "bsc"):
        node = FakeEthNode(chain_id=NETWORK_CHAIN_IDS[key])
        node.logs.append(
            transfer_log(
                block_number=5, tx_index=0, log_index=4, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=1
            )
        )
        respx.post(RPC_URL).mock(side_effect=node.handle)
        page = await EvmRpcAdapter(RPC_URL, network_key=key).fetch_transfers(
            address=ACCOUNT,
            asset=AssetRef(key, USDT, 6, "USDT"),
            direction=Direction.outgoing,
            analysis_cutoff=CUTOFF,
        )
        (event,) = page.events
        assert event.asset.network_key == key
        references[key] = event.event_reference
    assert references == {"ethereum": f"eip155:1:{tx}:4", "bsc": f"eip155:56:{tx}:4"}


def test_adapter_repr_does_not_expose_the_rpc_url() -> None:
    a = EvmRpcAdapter(SECRET_RPC_URL, network_key="bsc")
    assert "SECRET_KEY" not in repr(a)


# -- network-specific RPC configuration ---------------------------------------


def test_bsc_rpc_url_is_read_only_from_its_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CFA_BSC_RPC_URL", BSC_URL)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.bsc_rpc_url == BSC_URL
    assert settings.ethereum_rpc_url is None
    assert settings.evm_rpc_url("bsc") == BSC_URL
    assert settings.evm_rpc_url("ethereum") is None


def test_ethereum_rpc_url_never_serves_bsc_and_bsc_never_serves_ethereum() -> None:
    only_eth = make_settings(ethereum_rpc_url=ETH_URL)
    assert only_eth.evm_rpc_url("ethereum") == ETH_URL
    assert only_eth.evm_rpc_url("bsc") is None
    only_bsc = make_settings(bsc_rpc_url=BSC_URL)
    assert only_bsc.evm_rpc_url("bsc") == BSC_URL
    assert only_bsc.evm_rpc_url("ethereum") is None


def test_evm_rpc_url_rejects_a_non_evm_network() -> None:
    with pytest.raises(ValueError):
        make_settings().evm_rpc_url("tron")


def test_settings_repr_hides_both_rpc_urls() -> None:
    settings = make_settings(ethereum_rpc_url=ETH_URL, bsc_rpc_url=BSC_URL)
    assert "eth-only-key" not in repr(settings)
    assert "bsc-only-key" not in repr(settings)


def test_build_adapter_uses_each_networks_own_rpc_url() -> None:
    settings = make_settings(ethereum_rpc_url=ETH_URL, bsc_rpc_url=BSC_URL)
    eth = trace_service.build_adapter(settings, network_key="ethereum")
    bsc = trace_service.build_adapter(settings, network_key="bsc")
    assert isinstance(eth, EvmRpcAdapter) and isinstance(bsc, EvmRpcAdapter)
    assert (eth.rpc_url, eth.chain_id) == (ETH_URL, 1)
    assert (bsc.rpc_url, bsc.chain_id) == (BSC_URL, 56)


def test_missing_bsc_rpc_is_refused_even_when_ethereum_is_configured() -> None:
    settings = make_settings(ethereum_rpc_url=ETH_URL)
    with pytest.raises(TraceUnavailable, match="CFA_BSC_RPC_URL"):
        trace_service.build_adapter(settings, network_key="bsc")
    with pytest.raises(LiveValidationError, match="CFA_BSC_RPC_URL"):
        live_validation.preflight(settings, "bsc")


def test_missing_ethereum_rpc_is_refused_even_when_bsc_is_configured() -> None:
    settings = make_settings(bsc_rpc_url=BSC_URL)
    with pytest.raises(TraceUnavailable, match="CFA_ETHEREUM_RPC_URL"):
        trace_service.build_adapter(settings, network_key="ethereum")
    with pytest.raises(LiveValidationError, match="CFA_ETHEREUM_RPC_URL"):
        live_validation.preflight(settings, "ethereum")


def test_validation_adapter_for_live_bsc_uses_the_bsc_url_only() -> None:
    settings = make_settings(ethereum_rpc_url=ETH_URL, bsc_rpc_url=BSC_URL)
    adapter = live_validation._build_adapter(
        settings, "bsc", client=None, recorder=None, max_requests=None
    )
    assert isinstance(adapter, EvmRpcAdapter)
    assert adapter.rpc_url == BSC_URL


# -- LIVE bundle, replay, and label isolation across networks -----------------


def bsc_node() -> tuple[FakeEthNode, str]:
    node = FakeEthNode(chain_id=56, latest=200, finalized=190, safe=195)
    node.token_meta[USDT] = (18, "USDT", "Tether USD")
    tx = "0x" + "90" * 32
    node.logs.append(
        transfer_log(
            block_number=100,
            tx_index=0,
            log_index=0,
            tx_hash=tx,
            frm=ACCOUNT,
            to=PEER_A,
            value=5 * 10**18,
        )
    )
    node.receipts[tx] = {"status": "0x1", "blockNumber": hex(100)}
    return node, tx


def request_for(
    node: FakeEthNode, network: str, decimals: int, **overrides: Any
) -> ValidationRequest:
    kwargs: dict[str, Any] = {
        "address": ACCOUNT,
        "token_contract": USDT,
        "network_key": network,
        "asset_decimals": decimals,
        "asset_symbol": "USDT",
        "analysis_start": dt.datetime.fromtimestamp(node.block_time(0), tz=dt.UTC),
        "analysis_cutoff": dt.datetime.fromtimestamp(node.block_time(150), tz=dt.UTC),
        "max_requests": 80,
        "run_id": f"{network}-test-run",
    }
    kwargs.update(overrides)
    return ValidationRequest(**kwargs)


@respx.mock
async def test_bsc_live_bundle_records_network_facts_and_no_secret(tmp_path: Path) -> None:
    node, tx = bsc_node()
    respx.post(SECRET_RPC_URL).mock(side_effect=node.handle)
    settings = make_settings(
        bsc_rpc_url=SECRET_RPC_URL,
        ethereum_rpc_url=ETH_URL,
        label_dir=str(accepted_label_dir(tmp_path, network_key="bsc")),
    )
    run = await run_validation(settings, request_for(node, "bsc", 18), out_root=tmp_path / "live")
    assert run.succeeded
    assert run.trace is not None
    assert run.trace["seed"]["network_key"] == "bsc"
    assert run.trace["seed_transfer"] is None or (
        run.trace["seed_transfer"]["event_reference"].startswith("eip155:56:")
    )
    assert {t["event_reference"] for t in run.trace["observed_transfers"]} == {f"eip155:56:{tx}:0"}

    manifest = json.loads((run.directory / "manifest.json").read_text())
    configuration = manifest["configuration"]
    assert manifest["query"]["network"] == "bsc"
    assert configuration["network"] == "bsc"
    assert configuration["expected_chain_id"] == 56
    assert configuration["observed_chain_id"] == 56
    assert configuration["bsc_rpc_configured"] is True
    assert "ethereum_rpc_configured" not in configuration

    token = json.loads((run.directory / "token-verification.json").read_text())
    assert token["chain_id"] == 56
    assert token["decimals"] == 18
    assert token["code_present"] is True
    assert token["replayed_from_recorded_exchanges"] is False

    for path in run.directory.rglob("*"):
        if path.is_file():
            text = path.read_text()
            for secret in ("provider.example", "SECRET_KEY", "ANOTHER_SECRET", "eth-only-key"):
                assert secret not in text, (path.name, secret)


@respx.mock
async def test_bsc_replay_reproduces_live_with_zero_network_calls(tmp_path: Path) -> None:
    node, _tx = bsc_node()
    respx.post(BSC_URL).mock(side_effect=node.handle)
    label_dir = str(accepted_label_dir(tmp_path, network_key="bsc"))
    settings = make_settings(bsc_rpc_url=BSC_URL, label_dir=label_dir)
    request = request_for(node, "bsc", 18)
    live = await run_validation(settings, request, out_root=tmp_path / "live")
    assert live.succeeded
    calls_after_live = len(node.calls)

    replay = await run_validation(
        make_settings(data_mode=DataMode.RECORDED_PUBLIC, label_dir=label_dir),
        request,
        out_root=tmp_path / "replay",
        replay_from=live.directory / "raw",
    )
    assert replay.succeeded
    assert live.trace is not None and replay.trace is not None
    for key in ("seed", "seed_transfer", "observed_transfers", "branch_endings"):
        assert replay.trace[key] == live.trace[key], key
    assert replay.receipts["receipts"] == live.receipts["receipts"]
    assert replay.trace["scope"]["data_mode"] == "RECORDED_PUBLIC"
    assert len(node.calls) == calls_after_live  # nothing reached the (fake) network

    live_token = json.loads((live.directory / "token-verification.json").read_text())
    replay_token = json.loads((replay.directory / "token-verification.json").read_text())
    assert replay_token["replayed_from_recorded_exchanges"] is True
    for key in ("chain_id", "contract", "code_present", "decimals", "symbol", "name"):
        assert replay_token[key] == live_token[key]


@respx.mock
async def test_onchain_decimals_mismatch_refuses_the_validation(tmp_path: Path) -> None:
    node, _tx = bsc_node()
    respx.post(BSC_URL).mock(side_effect=node.handle)
    settings = make_settings(
        bsc_rpc_url=BSC_URL, label_dir=str(accepted_label_dir(tmp_path, network_key="bsc"))
    )
    with pytest.raises(LiveValidationError, match="decimals"):
        await run_validation(settings, request_for(node, "bsc", 6), out_root=tmp_path / "live")
    assert [c for c in node.calls if c[0] == "eth_getLogs"] == []


@pytest.mark.parametrize(
    ("trace_network", "label_network"), [("bsc", "ethereum"), ("ethereum", "bsc")]
)
@respx.mock
async def test_service_control_on_one_network_never_terminates_the_other(
    tmp_path: Path, trace_network: str, label_network: str
) -> None:
    """Same 20 address bytes, different networks: separate identities. An
    accepted claim on one network must not end a branch on the other."""
    chain_id = NETWORK_CHAIN_IDS[trace_network]
    node = FakeEthNode(chain_id=chain_id, latest=200, finalized=190, safe=195)
    tx = "0x" + "91" * 32
    node.logs.append(
        transfer_log(
            block_number=100, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=7
        )
    )
    node.receipts[tx] = {"status": "0x1", "blockNumber": hex(100)}
    respx.post(RPC_URL).mock(side_effect=node.handle)
    label_dir = str(accepted_label_dir(tmp_path, network_key=label_network))
    settings = make_settings(label_dir=label_dir, **{f"{trace_network}_rpc_url": RPC_URL})
    run = await run_validation(
        settings, request_for(node, trace_network, 6), out_root=tmp_path / "live"
    )
    assert run.succeeded and run.trace is not None
    peer_endings = [e for e in run.trace["branch_endings"] if e["address"] == PEER_A]
    assert peer_endings
    assert all(e["endpoint_class"] != "known_service" for e in peer_endings)
    assert all(e["label"] is None for e in peer_endings)


# -- replay network comes from the saved evidence ------------------------------


def load_validation_script() -> Any:
    path = REPO_ROOT / "scripts" / "validate_evm_live.py"
    spec = importlib.util.spec_from_file_location("validate_evm_live_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@respx.mock
async def test_replay_cli_takes_the_network_from_the_manifest_and_refuses_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    node, _tx = bsc_node()
    respx.post(BSC_URL).mock(side_effect=node.handle)
    label_dir = str(accepted_label_dir(tmp_path, network_key="bsc"))
    live = await run_validation(
        make_settings(bsc_rpc_url=BSC_URL, label_dir=label_dir),
        request_for(node, "bsc", 18),
        out_root=tmp_path / "live",
    )
    assert live.succeeded
    calls_after_live = len(node.calls)

    script = load_validation_script()
    replay_settings = make_settings(data_mode=DataMode.RECORDED_PUBLIC, label_dir=label_dir)
    monkeypatch.setattr(script, "get_settings", lambda: replay_settings)

    args = script.build_parser().parse_args(
        [
            "--replay",
            str(live.directory),
            "--network",
            "ethereum",
            "--out-dir",
            str(tmp_path / "r1"),
        ]
    )
    assert await script.main_async(args) == 2
    assert "conflicts with the saved bundle's network 'bsc'" in capsys.readouterr().err

    args = script.build_parser().parse_args(
        ["--replay", str(live.directory), "--out-dir", str(tmp_path / "r2")]
    )
    assert await script.main_async(args) == 0
    (replayed,) = (tmp_path / "r2").iterdir()
    manifest = json.loads((replayed / "manifest.json").read_text())
    assert manifest["query"]["network"] == "bsc"
    assert manifest["configuration"]["evm_block_resolution_policy"] == BLOCK_RESOLUTION_CURRENT
    assert manifest["configuration"]["observed_chain_id"] == 56
    assert len(node.calls) == calls_after_live


async def test_live_cli_without_bsc_rpc_stops_with_the_exact_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_validation_script()
    monkeypatch.setattr(script, "get_settings", lambda: make_settings(ethereum_rpc_url=ETH_URL))
    args = script.build_parser().parse_args(
        ["--network", "bsc", "--address", ACCOUNT, "--contract", USDT]
    )
    assert await script.main_async(args) == 2
    err = capsys.readouterr().err
    assert "BSC LIVE validation blocked: RPC not configured" in err
    assert "eth-only-key" not in err


# -- capability reporting -------------------------------------------------------


def _caps(**kwargs: Any) -> dict[str, dict[str, Any]]:
    rows = build_capabilities(
        readiness=None,
        saved_run_count=0,
        live_key_configured=False,
        configured_data_mode="SYNTHETIC",
        **kwargs,
    )
    return {row["key"]: row for row in rows}


def test_bsc_capability_before_any_live_run() -> None:
    caps = _caps(
        evm_networks={"bsc": {"rpc_configured": True, "historical_live_run_recorded": False}}
    )
    bsc = caps["bsc_token_tracing"]
    assert bsc["implementation_status"] == "implemented"
    assert bsc["configuration_status"] == "configured"
    assert bsc["live_verified"] is False
    assert bsc["historical_live_run_recorded"] is False
    assert caps["multi_chain"]["status"] == "partial"
    unconfigured = _caps()["bsc_token_tracing"]
    assert unconfigured["configuration_status"] == "not_configured"
    assert unconfigured["historical_live_run_recorded"] is False


def test_historical_bsc_run_is_not_current_live_verification() -> None:
    caps = _caps(
        evm_networks={"bsc": {"rpc_configured": False, "historical_live_run_recorded": True}}
    )
    bsc = caps["bsc_token_tracing"]
    assert bsc["historical_live_run_recorded"] is True
    assert bsc["live_verified"] is False
    assert bsc["configuration_status"] == "not_configured"
    assert caps["multi_chain"]["status"] == "partial"


def test_one_networks_evidence_never_credits_another() -> None:
    caps = _caps(
        evm_networks={"ethereum": {"rpc_configured": True, "historical_live_run_recorded": True}}
    )
    assert caps["evm_token_tracing"]["historical_live_run_recorded"] is True
    assert caps["bsc_token_tracing"]["historical_live_run_recorded"] is False
    assert caps["bsc_token_tracing"]["configuration_status"] == "not_configured"


def test_evm_network_states_come_from_settings_and_per_network_bundles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import demo_presets, operational_status

    seen: list[str | None] = []

    def fake(*, network_key: str | None = None) -> bool:
        seen.append(network_key)
        return network_key == "ethereum"

    monkeypatch.setattr(demo_presets, "has_recorded_successful_live_validation", fake)
    states = operational_status.evm_network_states(make_settings(bsc_rpc_url=BSC_URL))
    assert states == {
        "ethereum": {"rpc_configured": False, "historical_live_run_recorded": True},
        "bsc": {"rpc_configured": True, "historical_live_run_recorded": False},
        "base": {"rpc_configured": False, "historical_live_run_recorded": False},
    }
    assert sorted(n for n in seen if n) == ["base", "bsc", "ethereum"]


@respx.mock
async def test_replay_of_a_bundle_without_a_recorded_policy_uses_the_legacy_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node, _tx = bsc_node()
    respx.post(BSC_URL).mock(side_effect=node.handle)
    label_dir = str(accepted_label_dir(tmp_path, network_key="bsc"))
    live = await run_validation(
        make_settings(bsc_rpc_url=BSC_URL, label_dir=label_dir),
        request_for(node, "bsc", 18, block_resolution_policy=BLOCK_RESOLUTION_LEGACY),
        out_root=tmp_path / "live",
    )
    assert live.succeeded
    manifest_path = live.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["configuration"]["evm_block_resolution_policy"] == BLOCK_RESOLUTION_LEGACY
    # Simulate a bundle recorded before the policy was written down.
    del manifest["configuration"]["evm_block_resolution_policy"]
    manifest_path.write_text(json.dumps(manifest))

    script = load_validation_script()
    monkeypatch.setattr(
        script,
        "get_settings",
        lambda: make_settings(data_mode=DataMode.RECORDED_PUBLIC, label_dir=label_dir),
    )
    args = script.build_parser().parse_args(
        ["--replay", str(live.directory), "--out-dir", str(tmp_path / "r")]
    )
    assert await script.main_async(args) == 0
    (replayed,) = (tmp_path / "r").iterdir()
    replayed_manifest = json.loads((replayed / "manifest.json").read_text())
    assert (
        replayed_manifest["configuration"]["evm_block_resolution_policy"]
        == BLOCK_RESOLUTION_LEGACY
    )


@respx.mock
async def test_manifest_counts_requests_issued_and_range_splits_not_only_recorded_exchanges(
    tmp_path: Path,
) -> None:
    """A provider that rejects a wide eth_getLogs range is split, and the failed
    request is never recorded -- so ``provider_exchanges`` alone undercounts
    what the run actually sent. The manifest must say both."""
    node, _tx = bsc_node()
    node.http_fail_ranges.add((0, 150))
    respx.post(BSC_URL).mock(side_effect=node.handle)
    label_dir = str(accepted_label_dir(tmp_path, network_key="bsc"))
    request = request_for(node, "bsc", 18)
    live = await run_validation(
        make_settings(bsc_rpc_url=BSC_URL, label_dir=label_dir), request, out_root=tmp_path / "l"
    )
    assert live.succeeded
    stats = json.loads((live.directory / "manifest.json").read_text())["acquisition_stats"]
    assert stats["provider_requests_issued"] == len(node.calls)
    assert stats["provider_requests_issued"] > live.exchanges
    assert stats["log_range_splits"] >= 1
    assert stats["incomplete_log_ranges"] == []

    replay = await run_validation(
        make_settings(data_mode=DataMode.RECORDED_PUBLIC, label_dir=label_dir),
        request,
        out_root=tmp_path / "r",
        replay_from=live.directory / "raw",
    )
    replay_stats = json.loads((replay.directory / "manifest.json").read_text())[
        "acquisition_stats"
    ]
    assert replay_stats == stats


# -- the real, saved BSC Mainnet validation bundle -----------------------------

BSC_LIVE_BUNDLE = REPO_ROOT / "var" / "live-validation" / "20260926-bsc-usdt-live-002"


@pytest.mark.skipif(not BSC_LIVE_BUNDLE.is_dir(), reason="saved BSC LIVE bundle not present")
@respx.mock
async def test_saved_bsc_mainnet_bundle_replays_identically_offline(tmp_path: Path) -> None:
    """Replays the real recorded BSC Mainnet exchanges through the production
    adapter, decoder, receipt/finality code and tracer. ``respx.mock`` rejects
    any request that is not intercepted, so a real network call would fail."""
    from app.services.operational_status import verify_manifest_hashes

    manifest = json.loads((BSC_LIVE_BUNDLE / "manifest.json").read_text())
    integrity = verify_manifest_hashes(manifest, BSC_LIVE_BUNDLE)
    assert integrity["failed"] == 0 and integrity["missing"] == 0
    assert manifest["configuration"]["observed_chain_id"] == 56

    query = manifest["query"]
    token = json.loads((BSC_LIVE_BUNDLE / "token-verification.json").read_text())
    request = ValidationRequest(
        address=query["address"],
        token_contract=query["token_contract"],
        seed_event_reference=query["seed_event_reference"],
        network_key="bsc",
        asset_decimals=token["requested_decimals"],
        asset_symbol=token["requested_display_symbol"],
        analysis_start=dt.datetime.fromisoformat(query["analysis_start"]),
        analysis_cutoff=dt.datetime.fromisoformat(query["analysis_cutoff"]),
        max_requests=manifest["configuration"]["acquisition_max_requests"],
        block_resolution_policy=manifest["configuration"]["evm_block_resolution_policy"],
    )
    settings = make_settings(
        data_mode=DataMode.RECORDED_PUBLIC,
        label_dir=manifest["configuration"]["label_dir"],
        budget_max_hops=manifest["configuration"]["budgets"]["max_hops"],
    )
    replay = await run_validation(
        settings, request, out_root=tmp_path, replay_from=BSC_LIVE_BUNDLE / "raw"
    )
    live_trace = json.loads((BSC_LIVE_BUNDLE / "trace.json").read_text())
    assert replay.trace is not None
    for key in ("seed", "seed_transfer", "observed_transfers", "branch_endings"):
        assert replay.trace[key] == live_trace[key], key
    assert replay.trace["seed"]["event_reference"].startswith("eip155:56:")
    receipts = json.loads((BSC_LIVE_BUNDLE / "receipts.json").read_text())
    assert replay.receipts["receipts"] == receipts["receipts"]
