"""Binary decoders for Circle CCTP V2 on-chain messages.

Direct byte-level layout decoders for:
- MessageV2: 148-byte header + dynamic messageBody
- BurnMessageV2: 228-byte header + dynamic hookData
- Pure-Python Keccak-256 (FIPS 202 keccak-f[1600] with 0x01 padding)
- Exact integer fee and amount reconciliation without floats.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from app.models.cross_chain import AmountReconciliationResult

# Keccak-256 round constants
_RC = [
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
]

_ROTC = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]


def keccak256(data: bytes) -> bytes:
    """Standard Ethereum Keccak-256 (FIPS 202 keccak-f[1600] with 0x01 padding)."""
    rate = 136  # 1088 bits / 8
    state = [[0] * 5 for _ in range(5)]

    # Padding with 0x01 (Ethereum keccak, not NIST sha3-256 0x06)
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != rate - 1:
        padded.append(0x00)
    padded.append(0x80)

    # Process blocks
    for block_idx in range(0, len(padded), rate):
        block = padded[block_idx : block_idx + rate]
        for i in range(17):  # 136 // 8 = 17 64-bit words
            x = i % 5
            y = i // 5
            word = int.from_bytes(block[i * 8 : (i + 1) * 8], "little")
            state[x][y] ^= word

        # 24 rounds of keccak-f
        for rc in _RC:
            # Theta
            c = [
                state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4]
                for x in range(5)
            ]
            d = [
                c[(x - 1) % 5]
                ^ (((c[(x + 1) % 5] << 1) & 0xFFFFFFFFFFFFFFFF) | (c[(x + 1) % 5] >> 63))
                for x in range(5)
            ]
            for x in range(5):
                for y in range(5):
                    state[x][y] ^= d[x]

            # Rho & Pi
            b = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    r = _ROTC[x][y]
                    val = state[x][y]
                    b[y][(2 * x + 3 * y) % 5] = (
                        ((val << r) & 0xFFFFFFFFFFFFFFFF) | (val >> (64 - r) if r else 0)
                    )

            # Chi
            for x in range(5):
                for y in range(5):
                    state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])

            # Iota
            state[0][0] ^= rc

    # Squeeze output (32 bytes = 4 64-bit words)
    out = bytearray()
    for i in range(4):
        x = i % 5
        y = i // 5
        out.extend(state[x][y].to_bytes(8, "little"))
    return bytes(out)


@dataclass(frozen=True)
class DecodedMessageV2:
    header_version: int
    source_domain: int
    destination_domain: int
    nonce_bytes: bytes
    nonce_hex: str
    sender_bytes32: bytes
    sender_address: str
    recipient_bytes32: bytes
    recipient_address: str
    destination_caller: str
    min_finality_threshold: int
    finality_threshold_executed: int
    message_body: bytes


@dataclass(frozen=True)
class DecodedBurnMessageV2:
    burn_message_version: int
    burn_token_address: str
    mint_recipient_address: str
    amount_base_units: int
    message_sender_address: str
    max_fee_base_units: int
    fee_executed_base_units: int
    expiration_block: int
    hook_data: bytes


def decode_message_v2(raw: bytes) -> DecodedMessageV2:
    """Decode 148-byte MessageV2 binary header and extract messageBody."""
    if len(raw) < 148:
        raise ValueError(
            f"Raw message length {len(raw)} too short for MessageV2 header (min 148 bytes)"
        )

    header_version = struct.unpack(">I", raw[0:4])[0]
    source_domain = struct.unpack(">I", raw[4:8])[0]
    destination_domain = struct.unpack(">I", raw[8:12])[0]
    nonce_bytes = raw[12:44]
    nonce_hex = "0x" + nonce_bytes.hex()
    sender_bytes32 = raw[44:76]
    sender_address = "0x" + sender_bytes32[-20:].hex()
    recipient_bytes32 = raw[76:108]
    recipient_address = "0x" + recipient_bytes32[-20:].hex()
    destination_caller = "0x" + raw[108:140].hex()
    min_finality_threshold = struct.unpack(">I", raw[140:144])[0]
    finality_threshold_executed = struct.unpack(">I", raw[144:148])[0]
    message_body = raw[148:]

    return DecodedMessageV2(
        header_version=header_version,
        source_domain=source_domain,
        destination_domain=destination_domain,
        nonce_bytes=nonce_bytes,
        nonce_hex=nonce_hex,
        sender_bytes32=sender_bytes32,
        sender_address=sender_address,
        recipient_bytes32=recipient_bytes32,
        recipient_address=recipient_address,
        destination_caller=destination_caller,
        min_finality_threshold=min_finality_threshold,
        finality_threshold_executed=finality_threshold_executed,
        message_body=message_body,
    )


def decode_burn_message_v2(raw: bytes) -> DecodedBurnMessageV2:
    """Decode 228-byte BurnMessageV2 binary payload."""
    if len(raw) < 228:
        raise ValueError(
            f"Burn message length {len(raw)} too short for BurnMessageV2 (min 228 bytes)"
        )

    version = struct.unpack(">I", raw[0:4])[0]
    burn_token = "0x" + raw[4:36][-20:].hex()
    mint_recipient = "0x" + raw[36:68][-20:].hex()
    amount = int.from_bytes(raw[68:100], "big")
    message_sender = "0x" + raw[100:132][-20:].hex()
    max_fee = int.from_bytes(raw[132:164], "big")
    fee_executed = int.from_bytes(raw[164:196], "big")
    expiration_block = int.from_bytes(raw[196:228], "big")
    hook_data = raw[228:]

    return DecodedBurnMessageV2(
        burn_message_version=version,
        burn_token_address=burn_token,
        mint_recipient_address=mint_recipient,
        amount_base_units=amount,
        message_sender_address=message_sender,
        max_fee_base_units=max_fee,
        fee_executed_base_units=fee_executed,
        expiration_block=expiration_block,
        hook_data=hook_data,
    )


def reconcile_cctp_amounts(
    *,
    burn_amount: int,
    max_fee: int,
    fee_executed: int,
    observed_mint_amount: int | None,
    observed_recipient_usdc: int | None,
) -> AmountReconciliationResult:
    """Reconcile burn amount, fee executed, and observed destination mint amounts.

    Exact uint256 integer comparison only; no floats.
    """
    if fee_executed > max_fee:
        return AmountReconciliationResult.MISMATCH

    expected_destination = burn_amount - fee_executed
    if expected_destination < 0:
        return AmountReconciliationResult.MISMATCH

    if observed_mint_amount is None and observed_recipient_usdc is None:
        return AmountReconciliationResult.UNKNOWN

    if observed_mint_amount is not None and observed_mint_amount != expected_destination:
        return AmountReconciliationResult.MISMATCH

    if observed_recipient_usdc is not None and observed_recipient_usdc != expected_destination:
        return AmountReconciliationResult.MISMATCH

    return AmountReconciliationResult.MATCHES_PROTOCOL_EXPECTATION
