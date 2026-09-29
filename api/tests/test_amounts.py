"""A07-A09: amount precision. A float anywhere here is a bug in a legal document."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.core.amounts import UINT256_MAX, from_display, serialize, to_display
from app.core.settings import DataMode
from app.models.chain import Transaction
from app.models.enums import ExecutionStatus


def test_uint256_roundtrip(db: Session, tron) -> None:
    """A07: a uint256-scale amount survives the database exactly."""
    tx = Transaction(
        network_id=tron.id,
        tx_hash="tx_uint256",
        execution_status=ExecutionStatus.success,
        fee_base_units=UINT256_MAX,
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(tx)
    db.flush()
    db.expire(tx)
    stored = db.get(Transaction, tx.id)
    assert stored is not None
    assert stored.fee_base_units == UINT256_MAX
    assert isinstance(stored.fee_base_units, int)


def test_amount_serializes_as_string(db: Session, tron) -> None:
    """A08: amounts leave the system as JSON strings, never as JSON numbers."""
    payload = {"amount_base_units": serialize(UINT256_MAX)}
    encoded = json.dumps(payload)
    assert f'"{UINT256_MAX}"' in encoded
    reparsed = json.loads(encoded)
    assert isinstance(reparsed["amount_base_units"], str)
    assert int(reparsed["amount_base_units"]) == UINT256_MAX


@pytest.mark.parametrize(
    ("base_units", "decimals", "expected"),
    [
        (1_234_567, 6, "1.234567"),
        (1, 6, "0.000001"),
        (0, 6, "0.000000"),
        (100_000_000, 6, "100.000000"),
        (10**18 + 1, 18, "1.000000000000000001"),
        (-5, 6, "-0.000005"),
        (42, 0, "42"),
    ],
)
def test_display_conversion_exact(base_units: int, decimals: int, expected: str) -> None:
    """A09: exact decimal rendering at 6 and 18 decimals, with no float error."""
    assert to_display(base_units, decimals) == expected
    assert from_display(expected, decimals) == base_units


def test_float_amount_is_rejected() -> None:
    with pytest.raises(TypeError):
        to_display(1.5, 6)  # type: ignore[arg-type]


def test_excess_precision_is_rejected() -> None:
    with pytest.raises(ValueError, match="more precision"):
        from_display("1.1234567", 6)


def test_float_amount_rejected_at_the_database_boundary(db: Session, tron) -> None:
    """The column type refuses a float rather than silently truncating it."""
    tx = Transaction(
        network_id=tron.id,
        tx_hash="tx_float",
        execution_status=ExecutionStatus.success,
        fee_base_units=1.5,  # type: ignore[arg-type]
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(tx)
    with pytest.raises(StatementError) as caught:
        db.flush()
    assert isinstance(caught.value.orig, TypeError)
    assert "int in base units" in str(caught.value.orig)
