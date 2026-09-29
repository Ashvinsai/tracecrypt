"""Dependency-free Bitcoin-alphabet Base58 codec; checksums remain in addresses.py.

No case folding or ambiguous-character substitution is performed. This is not
an alternative address-validation policy: the existing 25-byte length, network
prefix and double-SHA256 checksum checks still apply unchanged.
"""
from __future__ import annotations

ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_LOOKUP = {c: i for i, c in enumerate(ALPHABET)}


def b58encode(value: bytes) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError("Base58 input must be bytes")
    leading = len(value) - len(value.lstrip(b"\x00"))
    number = int.from_bytes(value, "big")
    encoded = bytearray()
    while number:
        number, remainder = divmod(number, 58)
        encoded.append(ALPHABET[remainder])
    return b"1" * leading + bytes(reversed(encoded))


def b58decode(value: str | bytes) -> bytes:
    if isinstance(value, str):
        try:
            value = value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("Base58 must contain only ASCII characters") from exc
    if not isinstance(value, bytes):
        raise TypeError("Base58 input must be str or bytes")
    number = 0
    for character in value:
        if character not in _LOOKUP:
            raise ValueError("invalid Base58 character")
        number = number * 58 + _LOOKUP[character]
    leading = len(value) - len(value.lstrip(b"1"))
    return b"\x00" * leading + number.to_bytes((number.bit_length() + 7) // 8, "big")
