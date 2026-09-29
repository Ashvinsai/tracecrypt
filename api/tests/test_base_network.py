"""Tests for Base Mainnet network configuration and adapter integration.

Test-first verification of:
1. Base registered in EVM_NETWORKS with chain_id 8453 and caip2 'eip155:8453'.
2. Independent CFA_BASE_RPC_URL setting (no fallback to Ethereum or BSC).
3. CAIP-2 event-reference formatting for Base.
"""

from __future__ import annotations

import pytest

from app.adapters.evm import EVM_NETWORKS
from app.core.settings import Settings


def test_base_network_registry_configuration() -> None:
    """Base network configuration in EVM_NETWORKS."""
    assert "base" in EVM_NETWORKS
    base_cfg = EVM_NETWORKS["base"]
    assert base_cfg.network_key == "base"
    assert base_cfg.chain_id == 8453
    assert base_cfg.caip2 == "eip155:8453"
    assert base_cfg.display_name == "Base Mainnet"
    assert base_cfg.native_symbol == "ETH"
    assert base_cfg.rpc_setting == "base_rpc_url"
    assert base_cfg.rpc_env_var == "CFA_BASE_RPC_URL"


def test_base_rpc_setting_independent_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Base RPC setting must be strictly independent of Ethereum and BSC."""
    monkeypatch.setenv("CFA_ETHEREUM_RPC_URL", "https://ethereum.mock.rpc")
    monkeypatch.setenv("CFA_BSC_RPC_URL", "https://bsc.mock.rpc")
    monkeypatch.delenv("CFA_BASE_RPC_URL", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.evm_rpc_url("ethereum") == "https://ethereum.mock.rpc"
    assert settings.evm_rpc_url("bsc") == "https://bsc.mock.rpc"
    # Base RPC must be None when CFA_BASE_RPC_URL is unset
    assert settings.evm_rpc_url("base") is None

    # When CFA_BASE_RPC_URL is set, it returns its own URL
    monkeypatch.setenv("CFA_BASE_RPC_URL", "https://base.mock.rpc")
    settings_base = Settings()
    assert settings_base.evm_rpc_url("base") == "https://base.mock.rpc"


def test_base_event_reference_caip2_format() -> None:
    """Base event references must use eip155:8453:<tx_hash>:<log_index>."""
    tx_hash = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    log_index = 42
    expected = f"eip155:8453:{tx_hash}:{log_index}"

    base_cfg = EVM_NETWORKS["base"]
    ref = f"{base_cfg.caip2}:{tx_hash}:{log_index}"
    assert ref == expected
