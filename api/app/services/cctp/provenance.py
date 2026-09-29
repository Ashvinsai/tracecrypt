"""Official Circle CCTP V2 contract and token address provenance.

Retrieved from Circle's official contract references and documentation:
- https://developers.circle.com/cctp/references/contract-addresses
- https://developers.circle.com/stablecoins/usdc-contract-addresses
Retrieval date: 2026-09-27.
"""

from __future__ import annotations

from typing import Final

CCTP_PROVENANCE_RETRIEVAL_DATE: Final[str] = "2026-09-27"
CCTP_OFFICIAL_DOCS_URL: Final[str] = "https://developers.circle.com/cctp/references/contract-addresses"
CCTP_USDC_DOCS_URL: Final[str] = "https://developers.circle.com/stablecoins/usdc-contract-addresses"

# Official CCTP Domains (EVM chain IDs are separate identifiers)
# Ethereum: EVM Chain ID = 1, CCTP Domain = 0
# Base: EVM Chain ID = 8453, CCTP Domain = 6
DOMAIN_TO_NETWORK: Final[dict[int, str]] = {
    0: "ethereum",
    6: "base",
}

NETWORK_TO_DOMAIN: Final[dict[str, int]] = {
    "ethereum": 0,
    "base": 6,
}

CCTP_CONTRACTS: Final[dict[str, dict[str, str]]] = {
    "ethereum": {
        "network_key": "ethereum",
        "chain_id": "1",
        "cctp_domain": "0",
        "TokenMessengerV2": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
        "TokenMessengerWithFees": "0x71f54f818671cd0d7ea140da213e5c8b5c92a408",
        "MessageTransmitterV2": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
        "TokenMinterV2": "0xfd78ee919681417d192449715b2594ab58f5d002",
        "USDC": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    },
    "base": {
        "network_key": "base",
        "chain_id": "8453",
        "cctp_domain": "6",
        "TokenMessengerV2": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
        "TokenMessengerWithFees": "0x71f54f818671cd0d7ea140da213e5c8b5c92a408",
        "MessageTransmitterV2": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
        "TokenMinterV2": "0xfd78ee919681417d192449715b2594ab58f5d002",
        "USDC": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    },
}


def get_cctp_contract(network_key: str, role: str) -> str:
    """Return canonical lowercase hex address for a CCTP contract role."""
    contracts = CCTP_CONTRACTS.get(network_key)
    if contracts is None:
        raise ValueError(f"Network {network_key!r} not configured for CCTP V2")
    addr = contracts.get(role)
    if addr is None:
        raise ValueError(f"Role {role!r} not found for network {network_key!r}")
    return addr.lower()


def get_usdc_contract(network_key: str) -> str:
    """Return official USDC token contract address for network."""
    return get_cctp_contract(network_key, "USDC")
