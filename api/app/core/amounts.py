"""Exact base-unit arithmetic and display conversion (D004).

Amounts are integers everywhere. The only place a decimal appears is the final
display string, produced exactly, without float.
"""

from __future__ import annotations

from decimal import Decimal, localcontext

#: uint256 maximum. Storage is NUMERIC(78,0), which holds it.
UINT256_MAX = 2**256 - 1


def to_display(amount_base_units: int, decimals: int) -> str:
    """Render base units as an exact decimal string. No float, no rounding."""
    if not isinstance(amount_base_units, int) or isinstance(amount_base_units, bool):
        raise TypeError("amount must be an int in base units")
    if decimals < 0:
        raise ValueError("decimals must be non-negative")
    if decimals == 0:
        return str(amount_base_units)
    sign = "-" if amount_base_units < 0 else ""
    digits = str(abs(amount_base_units)).rjust(decimals + 1, "0")
    return f"{sign}{digits[:-decimals]}.{digits[-decimals:]}"


def from_display(value: str, decimals: int) -> int:
    """Parse an exact decimal string into base units. Rejects excess precision."""
    with localcontext() as ctx:
        ctx.prec = 100
        d = Decimal(value)
    scaled = d.scaleb(decimals)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"value {value!r} has more precision than {decimals} decimals allow")
    return int(scaled)


def serialize(amount_base_units: int | None) -> str | None:
    """JSON representation of an amount: a string, never a number (D004)."""
    return None if amount_base_units is None else str(amount_base_units)
