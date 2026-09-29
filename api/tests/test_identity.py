"""A04-A06, A10: address and asset identity."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import DataMode
from app.models.chain import Address, Asset
from app.models.enums import AssetKind
from app.services.addresses import AddressValidationError, canonicalize_evm, canonicalize_tron

SHARED_HEX = "0xdAC17F958D2ee523a2206206994597C13D831ec7"


def _address(network, value: str, canonical: str) -> Address:
    return Address(
        network_id=network.id,
        canonical_address=canonical,
        original_input=value,
        address_format="hex_lowercase_unchecked",
        data_mode=DataMode.SYNTHETIC,
    )


def test_same_string_two_networks(db: Session, tron, ethereum) -> None:
    """A04: one hex string is a different address on each network (D002)."""
    canonical = canonicalize_evm(SHARED_HEX).canonical
    db.add(_address(ethereum, SHARED_HEX, canonical))
    db.add(_address(tron, SHARED_HEX, canonical))
    db.flush()

    rows = (
        db.query(Address).filter(Address.canonical_address == canonical).all()
    )
    assert len(rows) == 2
    assert {r.network_id for r in rows} == {tron.id, ethereum.id}


def test_address_identity_unique(db: Session, ethereum) -> None:
    """A05: (network, canonical_address) is unique."""
    canonical = canonicalize_evm(SHARED_HEX).canonical
    db.add(_address(ethereum, SHARED_HEX, canonical))
    db.flush()
    db.add(_address(ethereum, SHARED_HEX.lower(), canonical))
    with pytest.raises(IntegrityError):
        db.flush()


def test_original_input_preserved(db: Session, tron) -> None:
    """A06: canonicalization never destroys what the investigator actually typed."""
    supplied = "  0x41a614f803b6fd780986a42c78ec9c7f77e6ded13c  "
    canonical = canonicalize_tron(supplied)
    assert canonical.canonical == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    assert canonical.original == supplied

    row = Address(
        network_id=tron.id,
        canonical_address=canonical.canonical,
        original_input=canonical.original,
        address_format=canonical.address_format,
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(row)
    db.flush()
    db.expire(row)
    stored = db.get(Address, row.id)
    assert stored is not None
    assert stored.original_input == supplied
    assert stored.canonical_address == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def test_symbol_is_not_asset_identity(db: Session, tron) -> None:
    """A10: two contracts claiming the same ticker are two assets (D003)."""
    for contract in (
        "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
        "TUJmRrUmPrJZgqhRGjGKwbAzqZx3EHpoW2",
    ):
        db.add(
            Asset(
                network_id=tron.id,
                kind=AssetKind.token,
                token_contract=contract,
                decimals=6,
                display_symbol="USDT-SYN",
                data_mode=DataMode.SYNTHETIC,
            )
        )
    db.flush()
    same_symbol = db.query(Asset).filter(Asset.display_symbol == "USDT-SYN").all()
    assert len(same_symbol) == 2
    assert len({a.token_contract for a in same_symbol}) == 2


def test_tron_checksum_is_verified() -> None:
    with pytest.raises(AddressValidationError, match="checksum"):
        canonicalize_tron("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6X")


def test_tron_rejects_evm_address() -> None:
    """Network is never inferred from syntax: an EVM string is not a TRON address."""
    with pytest.raises(AddressValidationError):
        canonicalize_tron(SHARED_HEX)
