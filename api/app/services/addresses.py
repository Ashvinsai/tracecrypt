"""Address validation and canonicalization, per network (D002).

A network is never inferred from address syntax. The caller states the network;
this module only answers whether the string is valid *on that network* and what
its canonical form is.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.core import base58codec as base58

TRON_MAINNET_PREFIX = 0x41
TRON_BASE58_LENGTH = 34


class AddressValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalAddress:
    canonical: str
    original: str
    address_format: str


def _b58check_encode(payload: bytes) -> str:
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return base58.b58encode(payload + checksum).decode()


def _b58check_decode(value: str) -> bytes:
    raw = base58.b58decode(value)
    if len(raw) != 25:
        raise AddressValidationError("TRON address must decode to 25 bytes")
    payload, checksum = raw[:21], raw[21:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected:
        raise AddressValidationError("TRON address checksum mismatch")
    return payload


def canonicalize_tron(value: str) -> CanonicalAddress:
    """Accept base58check (``T...``) or 41-prefixed hex; canonical form is base58check."""
    original = value
    value = value.strip()
    if not value:
        raise AddressValidationError("empty address")

    hex_candidate = value[2:] if value.lower().startswith("0x") else value
    if len(hex_candidate) == 42 and all(c in "0123456789abcdefABCDEF" for c in hex_candidate):
        payload = bytes.fromhex(hex_candidate)
        if payload[0] != TRON_MAINNET_PREFIX:
            raise AddressValidationError("TRON hex address must start with 0x41")
        return CanonicalAddress(_b58check_encode(payload), original, "base58check")

    if not value.startswith("T") or len(value) != TRON_BASE58_LENGTH:
        raise AddressValidationError("TRON address must be 34 characters starting with 'T'")
    try:
        payload = _b58check_decode(value)
    except ValueError as exc:  # base58 raises ValueError on bad alphabet
        raise AddressValidationError(str(exc)) from exc
    if payload[0] != TRON_MAINNET_PREFIX:
        raise AddressValidationError("TRON address must carry the 0x41 mainnet prefix")
    return CanonicalAddress(_b58check_encode(payload), original, "base58check")


def canonicalize_evm(value: str) -> CanonicalAddress:
    """Syntax check only.

    Canonical form is lowercase hex. EIP-55 mixed-case checksum verification needs
    keccak256 and arrives with the EVM adapter in phase 12; until then a mixed-case
    string is accepted on syntax and normalized, and the checksum is NOT verified.
    The same string is valid on every EVM chain, so this never implies a network.
    """
    original = value
    value = value.strip()
    if not (value.startswith("0x") and len(value) == 42):
        raise AddressValidationError("EVM address must be 0x followed by 40 hex characters")
    body = value[2:]
    if not all(c in "0123456789abcdefABCDEF" for c in body):
        raise AddressValidationError("EVM address must be hexadecimal")
    return CanonicalAddress("0x" + body.lower(), original, "hex_lowercase_unchecked")


_CANONICALIZERS = {
    "tron": canonicalize_tron,
    "evm": canonicalize_evm,
}


def canonicalize(network_key: str, value: str) -> CanonicalAddress:
    family = "tron" if network_key == "tron" else "evm"
    fn = _CANONICALIZERS.get(family)
    if fn is None:
        raise AddressValidationError(f"no canonicalizer for network {network_key!r}")
    return fn(value)
