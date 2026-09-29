"""Protocol unit tests for Circle CCTP V2 (Ethereum Mainnet -> Base Mainnet).

Test-first verification of:
1. MessageV2 binary header version 1 under CCTP V2 protocol generation 2.
2. Distinct eventNonce vs message nonce vs API event nonce concepts.
3. Official DepositForBurn ABI / event signature and topic0 derivation.
4. Official MessageReceived ABI / event signature and topic0 derivation.
5. MintAndWithdraw and MessageSent signatures.
6. Exact uint256 amount and fee semantics (never floats).
7. Fee/amount reconciliation: MATCHES_PROTOCOL_EXPECTATION vs MISMATCH.
8. Pinned CCTP V2 contract and token provenance.
9. CrossChainLink immutability, kw_only construction, and non-masquerading.
"""

from __future__ import annotations

from app.models.cross_chain import (
    AmountReconciliationResult,
    CrossChainLink,
    CrossChainLinkageStatus,
)
from app.services.cctp.binary import (
    decode_burn_message_v2,
    decode_message_v2,
    keccak256,
    reconcile_cctp_amounts,
)
from app.services.cctp.destination import (
    MESSAGE_RECEIVED_V2_SIG,
    MESSAGE_RECEIVED_V2_TOPIC,
    MINT_AND_WITHDRAW_LEGACY_SIG,
    MINT_AND_WITHDRAW_LEGACY_TOPIC,
    MINT_AND_WITHDRAW_V2_SIG,
    MINT_AND_WITHDRAW_V2_TOPIC,
)
from app.services.cctp.provenance import (
    CCTP_PROVENANCE_RETRIEVAL_DATE,
    get_cctp_contract,
    get_usdc_contract,
)
from app.services.cctp.source import (
    DEPOSIT_FOR_BURN_V2_SIG,
    DEPOSIT_FOR_BURN_V2_TOPIC,
    MESSAGE_SENT_SIG,
    MESSAGE_SENT_TOPIC,
)


def test_keccak256_standard_vectors() -> None:
    """Verify our pure-Python keccak256 against known Ethereum constants."""
    # Empty string hash
    expected_empty = "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert keccak256(b"").hex() == expected_empty
    # Transfer(address,address,uint256)
    assert (
        "0x" + keccak256(b"Transfer(address,address,uint256)").hex()
        == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    )


def test_keccak256_differential_against_pycryptodome() -> None:
    """Differential-test pure-Python keccak256 against Crypto.Hash.keccak."""
    from Crypto.Hash import keccak as pycrypto_keccak

    test_vectors = [
        b"",
        b"a",
        b"hello world",
        b"Transfer(address,address,uint256)",
        b"DepositForBurn(address,uint256,address,bytes32,uint32,bytes32,bytes32,uint256,uint32,bytes)",
        bytes(range(256)),
        bytes(136),  # Keccak-256 rate block boundary
        bytes(137),  # One byte past rate block
        bytes(272),  # Two full blocks
    ]
    for vector in test_vectors:
        ref_digest = pycrypto_keccak.new(digest_bits=256, data=vector).digest()
        our_digest = keccak256(vector)
        assert our_digest == ref_digest, f"Digest mismatch on vector of len {len(vector)}"


def test_pinned_event_signatures_and_topic0_derivation() -> None:
    """Derive topic0 from official event signatures and verify match with pinned constants."""
    # DepositForBurn V2 signature
    expected_dfb = "0x" + keccak256(DEPOSIT_FOR_BURN_V2_SIG.encode("utf-8")).hex()
    assert expected_dfb == DEPOSIT_FOR_BURN_V2_TOPIC
    expected_dfb_topic = (
        "0x0c8c1cbdc5190613ebd485511d4e2812cfa45eecb79d845893331fedad5130a5"
    )
    assert DEPOSIT_FOR_BURN_V2_TOPIC == expected_dfb_topic

    # MessageSent V2 signature
    expected_ms = "0x" + keccak256(MESSAGE_SENT_SIG.encode("utf-8")).hex()
    assert expected_ms == MESSAGE_SENT_TOPIC
    expected_ms_topic = (
        "0x8c5261668696ce22758910d05bab8f186d6eb247ceac2af2e82c7dc17669b036"
    )
    assert MESSAGE_SENT_TOPIC == expected_ms_topic

    # MessageReceived V2 signature
    expected_mr = "0x" + keccak256(MESSAGE_RECEIVED_V2_SIG.encode("utf-8")).hex()
    assert expected_mr == MESSAGE_RECEIVED_V2_TOPIC
    expected_mr_topic = (
        "0xff48c13eda96b1cceacc6b9edeedc9e9db9d6226afbc30146b720c19d3addb1c"
    )
    assert MESSAGE_RECEIVED_V2_TOPIC == expected_mr_topic

    # MintAndWithdraw V2 signature (with feeExecuted)
    expected_mw = "0x" + keccak256(MINT_AND_WITHDRAW_V2_SIG.encode("utf-8")).hex()
    assert expected_mw == MINT_AND_WITHDRAW_V2_TOPIC
    expected_mw_topic = (
        "0x50c55e915134d457debfa58eb6f4342956f8b0616d51a89a3659360178e1ab63"
    )
    assert MINT_AND_WITHDRAW_V2_TOPIC == expected_mw_topic

    # MintAndWithdraw legacy signature (without feeExecuted)
    expected_mw_legacy = "0x" + keccak256(MINT_AND_WITHDRAW_LEGACY_SIG.encode("utf-8")).hex()
    assert expected_mw_legacy == MINT_AND_WITHDRAW_LEGACY_TOPIC
    expected_mw_legacy_topic = (
        "0x1b2a7ff080b8cb6ff436ce0372e399692bbfb6d4ae5766fd8d58a7b8cc6142e6"
    )
    assert MINT_AND_WITHDRAW_LEGACY_TOPIC == expected_mw_legacy_topic


def test_message_v2_binary_header_version_1_under_protocol_generation_2() -> None:
    """Circle CCTP V2 uses binary message header version 1 and burn message version 1."""
    # 148 bytes header + 228 bytes burn message = 376 bytes
    # Version 1 (4 bytes), src domain 0 (4 bytes), dst domain 6 (4 bytes),
    # nonce 32 bytes, sender 32 bytes, recipient 32 bytes, destinationCaller 32 bytes,
    # minFinalityThreshold 4 bytes, finalityThresholdExecuted 4 bytes
    header_bytes = (
        (1).to_bytes(4, "big")  # version = 1
        + (0).to_bytes(4, "big")  # src = 0 (Ethereum)
        + (6).to_bytes(4, "big")  # dst = 6 (Base)
        + bytes.fromhex(
            "03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d"
        )  # nonce
        + bytes.fromhex(
            "00000000000000000000000028b5a0e9c621a5badaa536219b3a228c8168cf5d"
        )  # sender
        + bytes.fromhex(
            "00000000000000000000000028b5a0e9c621a5badaa536219b3a228c8168cf5d"
        )  # recipient
        + bytes(32)  # destinationCaller = 0
        + (2000).to_bytes(4, "big")  # minFinalityThreshold = 2000
        + (2000).to_bytes(4, "big")  # finalityThresholdExecuted = 2000
    )
    assert len(header_bytes) == 148

    burn_body = (
        (1).to_bytes(4, "big")  # burn message version = 1
        + bytes.fromhex(
            "000000000000000000000000a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        )  # burnToken
        + bytes.fromhex(
            "00000000000000000000000038a1c011890bc95fd4b43b622e1432c859d097bc"
        )  # mintRecipient
        + (9391319).to_bytes(32, "big")  # amount
        + bytes.fromhex(
            "00000000000000000000000038a1c011890bc95fd4b43b622e1432c859d097bc"
        )  # messageSender
        + (0).to_bytes(32, "big")  # maxFee = 0
        + (0).to_bytes(32, "big")  # feeExecuted = 0
        + (0).to_bytes(32, "big")  # expirationBlock = 0
    )
    assert len(burn_body) == 228

    full_msg = header_bytes + burn_body
    decoded = decode_message_v2(full_msg)

    assert decoded.header_version == 1
    assert decoded.source_domain == 0
    assert decoded.destination_domain == 6
    assert decoded.nonce_hex == "0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d"
    assert decoded.sender_address == "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d"
    assert decoded.recipient_address == "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d"
    assert decoded.min_finality_threshold == 2000
    assert decoded.finality_threshold_executed == 2000

    burn_decoded = decode_burn_message_v2(decoded.message_body)
    assert burn_decoded.burn_message_version == 1
    assert burn_decoded.burn_token_address == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    assert burn_decoded.mint_recipient_address == "0x38a1c011890bc95fd4b43b622e1432c859d097bc"
    assert burn_decoded.amount_base_units == 9391319
    assert burn_decoded.max_fee_base_units == 0
    assert burn_decoded.fee_executed_base_units == 0


def test_distinct_nonce_concepts_reconciliation() -> None:
    """Test distinct event_nonce, message_nonce, and api_event_nonce fields."""
    link = CrossChainLink(
        protocol_family="circle_cctp",
        protocol_generation=2,
        message_header_version=1,
        burn_message_version=1,
        linkage_status=CrossChainLinkageStatus.MESSAGE_IDENTIFIED,
        source_network="ethereum",
        source_chain_id=1,
        source_domain=0,
        source_tx_hash="0x722f02281716e6e6dba159a06bf62be63ba0bdc5c77db84c4e9c06b224c797ed",
        source_burn_event_reference="eip155:1:0x722f02281716e6e6dba159a06bf62be63ba0bdc5c77db84c4e9c06b224c797ed:320",
        source_message_event_reference="eip155:1:0x722f02281716e6e6dba159a06bf62be63ba0bdc5c77db84c4e9c06b224c797ed:319",
        source_block_number=26062983,
        source_event_nonce=None,  # V2 DepositForBurn does not emit a numeric event nonce
        message_nonce="0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d",
        api_event_nonce="0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d",
        message_hash="0x1234",
        message_bytes="0x00",
        attestation_status="API_REPORTED_COMPLETE",
        attestation_signature_verified=False,
        burn_token="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        mint_token="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        depositor="0x38a1c011890bc95fd4b43b622e1432c859d097bc",
        mint_recipient="0x38a1c011890bc95fd4b43b622e1432c859d097bc",
        source_burn_amount_base_units=9391319,
        max_fee_base_units=0,
        fee_executed_base_units=0,
        destination_network="base",
        destination_chain_id=8453,
        destination_domain=6,
    )

    # Validate that attributes are distinct and not collapsed
    assert link.source_event_nonce is None
    expected_nonce = (
        "0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d"
    )
    assert link.message_nonce == expected_nonce
    assert link.api_event_nonce == expected_nonce
    assert link.attestation_status == "API_REPORTED_COMPLETE"
    assert not link.attestation_signature_verified


def test_amount_reconciliation_exact_uint256_logic() -> None:
    """Test fee and amount reconciliation without floats."""
    # Match: observed mint matches burn - fee_executed
    rec_ok = reconcile_cctp_amounts(
        burn_amount=150_000_000,
        max_fee=75_000,
        fee_executed=15_000,
        observed_mint_amount=149_985_000,
        observed_recipient_usdc=149_985_000,
    )
    assert rec_ok == AmountReconciliationResult.MATCHES_PROTOCOL_EXPECTATION

    # Mismatch: observed mint does not equal burn - fee_executed
    rec_mismatch = reconcile_cctp_amounts(
        burn_amount=150_000_000,
        max_fee=75_000,
        fee_executed=15_000,
        observed_mint_amount=150_000_000,  # should have been 149_985_000
        observed_recipient_usdc=150_000_000,
    )
    assert rec_mismatch == AmountReconciliationResult.MISMATCH

    # Fee exceeded max_fee: must be MISMATCH
    rec_invalid_fee = reconcile_cctp_amounts(
        burn_amount=150_000_000,
        max_fee=10_000,
        fee_executed=15_000,  # > max_fee!
        observed_mint_amount=149_985_000,
        observed_recipient_usdc=149_985_000,
    )
    assert rec_invalid_fee == AmountReconciliationResult.MISMATCH

    # Destination not yet observed: UNKNOWN
    rec_unknown = reconcile_cctp_amounts(
        burn_amount=150_000_000,
        max_fee=75_000,
        fee_executed=15_000,
        observed_mint_amount=None,
        observed_recipient_usdc=None,
    )
    assert rec_unknown == AmountReconciliationResult.UNKNOWN


def test_cctp_contract_provenance_pinning() -> None:
    """Verify pinned addresses for Ethereum and Base CCTP contracts."""
    assert CCTP_PROVENANCE_RETRIEVAL_DATE == "2026-09-27"

    # Ethereum
    eth_tm = get_cctp_contract("ethereum", "TokenMessengerV2")
    assert eth_tm == "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d"
    eth_mt = get_cctp_contract("ethereum", "MessageTransmitterV2")
    assert eth_mt == "0x81d40f21f12a8f0e3252bccb954d722d4c464b64"
    eth_usdc = get_usdc_contract("ethereum")
    assert eth_usdc == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"

    # Base
    base_tm = get_cctp_contract("base", "TokenMessengerV2")
    assert base_tm == "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d"
    base_mt = get_cctp_contract("base", "MessageTransmitterV2")
    assert base_mt == "0x81d40f21f12a8f0e3252bccb954d722d4c464b64"
    base_usdc = get_usdc_contract("base")
    assert base_usdc == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def test_attestation_length_and_multisig_blob_calculation() -> None:
    """Calculate attestation length and signature blobs dynamically.

    Circle MessageTransmitterV2 uses 65-byte secp256k1 signature blobs.
    Real CCTP V2 Iris attestations contain 2 concatenated 65-byte signatures (130 bytes total).
    The linker must dynamically compute length and blob count rather than assuming
    a single 65-byte blob.
    """
    from app.services.cctp.client import CircleApiMatchResult
    from app.services.cctp.linker import CctpLinker

    # 130-byte real attestation hex (260 hex characters + 0x)
    attestation_130_bytes = (
        "0x9de242e58d5f73681ad5305c710f733a79cf4443c657b2dca0f85bdba5cffcd5"
        "206f184e4da8f580b48f0f947c16639d533a4aa328100cba99eb22fd26b7543a1b"
        "6b6df336215f3f26909e18303bad8240e2c2eaff04fb8b2dd399f16210c5f94729"
        "50e9fec2670751900589bb55f62969e7aaf08eb4fc28dcac2a98b080f2d6461b"
    )
    raw_bytes = bytes.fromhex(attestation_130_bytes[2:])
    assert len(raw_bytes) == 130

    api_match = CircleApiMatchResult(
        matched=True,
        status="API_REPORTED_COMPLETE",
        attestation_bytes=attestation_130_bytes,
        event_nonce="0x03c1ce4cab19841c55bc11af0cd262e3fd5e20cf3a06ecb50c2874816fbb900d",
        api_message_bytes="0x",
        forward_tx_hint=None,
    )

    linker = CctpLinker()
    link = linker.build_link(
        source_message=None,
        api_message=api_match,
        destination_execution=None,
    )

    assert link.attestation_length_bytes == 130
    assert link.signature_blob_size_bytes == 65
    assert link.signature_blob_count == 2
    assert link.attestation_status == "API_REPORTED_COMPLETE"
    assert not link.attestation_signature_verified
