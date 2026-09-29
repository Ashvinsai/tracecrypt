"""EVM address canonicalization and cross-network separation (Phase T, group 1)."""

from __future__ import annotations

import pytest

from app.services.addresses import (
    AddressValidationError,
    canonicalize,
    canonicalize_evm,
    canonicalize_tron,
)

CHECKSUM = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
LOWER = "0xdac17f958d2ee523a2206206994597c13d831ec7"


def test_lowercase_address_accepted() -> None:
    result = canonicalize_evm(LOWER)
    assert result.canonical == LOWER


def test_mixed_case_checksum_address_normalizes_to_lowercase() -> None:
    """Equality never depends on letter case (constraint 5)."""
    result = canonicalize_evm(CHECKSUM)
    assert result.canonical == LOWER
    assert result.original == CHECKSUM


def test_invalid_length_rejected() -> None:
    with pytest.raises(AddressValidationError):
        canonicalize_evm("0x" + "ab" * 19)  # 38 hex chars, one short


def test_non_hex_rejected() -> None:
    with pytest.raises(AddressValidationError):
        canonicalize_evm("0x" + "zz" * 20)


def test_missing_0x_prefix_rejected() -> None:
    with pytest.raises(AddressValidationError):
        canonicalize_evm(LOWER[2:])


def test_whitespace_is_stripped() -> None:
    result = canonicalize_evm(f"  {LOWER}  ")
    assert result.canonical == LOWER
    assert result.original == f"  {LOWER}  "


def test_tron_rejects_evm_address() -> None:
    """Network is never inferred from syntax (D002)."""
    with pytest.raises(AddressValidationError):
        canonicalize_tron(LOWER)


def test_evm_generic_dispatch_routes_to_evm_canonicalizer() -> None:
    result = canonicalize("ethereum", CHECKSUM)
    assert result.canonical == LOWER


def test_tron_generic_dispatch_rejects_evm_string() -> None:
    with pytest.raises(AddressValidationError):
        canonicalize("tron", CHECKSUM)
