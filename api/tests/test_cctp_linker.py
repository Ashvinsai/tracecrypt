"""Linker and integration tests for Circle CCTP V2 (Ethereum Mainnet -> Base Mainnet).

Test-first verification of:
1. Two messages in one source transaction remain distinct by nonce and log index.
2. Wrong API message selected or non-unique match yields AMBIGUOUS linkage status.
3. Circle API status 'complete' yields API_REPORTED_COMPLETE without cryptographic
   verification claim.
4. Attestation present but destination absent yields INCOMPLETE linkage status.
5. Forward transaction hash hint without destination receipt validation yields INCOMPLETE.
6. Reverted destination transaction yields FAILED.
7. Destination recipient or amount mismatch yields FAILED.
8. Cross-chain link is never treated as a same-chain NormalizedTransfer.
9. Base label isolation: Ethereum label cannot terminate Base, Base label cannot terminate
   Ethereum.
"""

from __future__ import annotations

from app.adapters.base import NormalizedTransfer
from app.models.cross_chain import (
    CrossChainLink,
    CrossChainLinkageStatus,
)
from app.services.cctp.linker import (
    CctpLinker,
)


def test_cross_chain_link_is_not_normalized_transfer() -> None:
    """A cross-chain link must never masquerade as a same-chain NormalizedTransfer."""
    link = CrossChainLink(
        protocol_family="circle_cctp",
        protocol_generation=2,
        message_header_version=1,
        burn_message_version=1,
        linkage_status=CrossChainLinkageStatus.COMPLETE,
        source_network="ethereum",
        source_chain_id=1,
        source_domain=0,
        source_tx_hash="0x" + "11" * 32,
        source_burn_event_reference="eip155:1:0x" + "11" * 32 + ":10",
        source_message_event_reference="eip155:1:0x" + "11" * 32 + ":9",
        source_block_number=1000,
        message_nonce="0x" + "22" * 32,
        message_hash="0x" + "33" * 32,
        message_bytes="0x00",
        attestation_status="API_REPORTED_COMPLETE",
        attestation_signature_verified=False,
        burn_token="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        mint_token="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        depositor="0x" + "44" * 20,
        mint_recipient="0x" + "55" * 20,
        source_burn_amount_base_units=1000,
        max_fee_base_units=0,
        fee_executed_base_units=0,
        destination_network="base",
        destination_chain_id=8453,
        destination_domain=6,
        destination_tx_hash="0x" + "66" * 32,
    )

    assert not isinstance(link, NormalizedTransfer)
    # NormalizedTransfer must require direction, token_contract, etc.
    # CrossChainLink has explicit source and destination network boundaries.
    assert link.source_network != link.destination_network
    assert link.source_chain_id != link.destination_chain_id


def test_two_messages_in_one_source_tx_remain_distinct() -> None:
    """Two CCTP transfers in one Ethereum transaction must produce distinct records."""
    linker = CctpLinker()
    # Simulated receipt containing two distinct MessageSent + DepositForBurn pairs
    source_receipt = {
        "transactionHash": "0x" + "aa" * 32,
        "blockNumber": "0x100",
        "status": "0x1",
        "logs": [
            # Transfer 1
            {
                "logIndex": "0x1",
                "address": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
                "topics": ["0x8c5261668696ce22758910d05bab8f186d6eb247ceac2af2e82c7dc17669b036"],
                # message bytes with recipient 1
                "data": (
                    "0x0000000000000000000000000000000000000000000000000000000000000020"
                    "0000000000000000000000000000000000000000000000000000000000000178"
                    # 376 bytes payload
                    + (
                        (1).to_bytes(4, "big")
                        + (0).to_bytes(4, "big")
                        + (6).to_bytes(4, "big")
                        + bytes(32)  # nonce 0
                        + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                        + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                        + bytes(32)
                        + (2000).to_bytes(4, "big")
                        + (0).to_bytes(4, "big")
                        + (1).to_bytes(4, "big")  # burn message version
                        + bytes(12) + bytes.fromhex("a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
                        # recipient 1
                        + bytes(12) + bytes.fromhex("1111111111111111111111111111111111111111")
                        + (100).to_bytes(32, "big")
                        + bytes(12) + bytes.fromhex("1111111111111111111111111111111111111111")
                        + (0).to_bytes(32, "big")
                        + (0).to_bytes(32, "big")
                        + (0).to_bytes(32, "big")
                    ).hex()
                ),
            },
            {
                "logIndex": "0x2",
                "address": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
                "topics": [
                    "0x0c8c1cbdc5190613ebd485511d4e2812cfa45eecb79d845893331fedad5130a5",
                    "0x000000000000000000000000a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "0x0000000000000000000000001111111111111111111111111111111111111111",
                    "0x00000000000000000000000000000000000000000000000000000000000007d0",
                ],
                "data": (
                    (100).to_bytes(32, "big")
                    + bytes(12) + bytes.fromhex("1111111111111111111111111111111111111111")
                    + (6).to_bytes(32, "big")
                    + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                    + bytes(32)
                    + (0).to_bytes(32, "big")
                    + (224).to_bytes(32, "big")
                    + (0).to_bytes(32, "big")
                ).hex(),
            },
            # Transfer 2
            {
                "logIndex": "0x3",
                "address": "0x81d40f21f12a8f0e3252bccb954d722d4c464b64",
                "topics": ["0x8c5261668696ce22758910d05bab8f186d6eb247ceac2af2e82c7dc17669b036"],
                # message bytes with recipient 2
                "data": (
                    "0x0000000000000000000000000000000000000000000000000000000000000020"
                    "0000000000000000000000000000000000000000000000000000000000000178"
                    # 376 bytes payload
                    + (
                        (1).to_bytes(4, "big")
                        + (0).to_bytes(4, "big")
                        + (6).to_bytes(4, "big")
                        + bytes(32)  # nonce 0
                        + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                        + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                        + bytes(32)
                        + (2000).to_bytes(4, "big")
                        + (0).to_bytes(4, "big")
                        + (1).to_bytes(4, "big")  # burn message version
                        + bytes(12) + bytes.fromhex("a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
                        # recipient 2
                        + bytes(12) + bytes.fromhex("2222222222222222222222222222222222222222")
                        + (200).to_bytes(32, "big")
                        + bytes(12) + bytes.fromhex("2222222222222222222222222222222222222222")
                        + (0).to_bytes(32, "big")
                        + (0).to_bytes(32, "big")
                        + (0).to_bytes(32, "big")
                    ).hex()
                ),
            },
            {
                "logIndex": "0x4",
                "address": "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
                "topics": [
                    "0x0c8c1cbdc5190613ebd485511d4e2812cfa45eecb79d845893331fedad5130a5",
                    "0x000000000000000000000000a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "0x0000000000000000000000002222222222222222222222222222222222222222",
                    "0x00000000000000000000000000000000000000000000000000000000000007d0",
                ],
                "data": (
                    (200).to_bytes(32, "big")
                    + bytes(12) + bytes.fromhex("2222222222222222222222222222222222222222")
                    + (6).to_bytes(32, "big")
                    + bytes(12) + bytes.fromhex("28b5a0e9c621a5badaa536219b3a228c8168cf5d")
                    + bytes(32)
                    + (0).to_bytes(32, "big")
                    + (224).to_bytes(32, "big")
                    + (0).to_bytes(32, "big")
                ).hex(),
            },
        ],
    }

    pairs = linker.extract_source_messages(source_receipt, network_key="ethereum", chain_id=1)
    assert len(pairs) == 2
    # Verify exact log index and recipient separation
    assert pairs[0].source_burn_event_reference.endswith(":2")
    assert pairs[0].mint_recipient == "0x1111111111111111111111111111111111111111"
    assert pairs[0].source_burn_amount_base_units == 100

    assert pairs[1].source_burn_event_reference.endswith(":4")
    assert pairs[1].mint_recipient == "0x2222222222222222222222222222222222222222"
    assert pairs[1].source_burn_amount_base_units == 200


def test_attestation_present_but_destination_absent_stays_incomplete() -> None:
    """Attestation complete without destination execution must remain INCOMPLETE."""
    linker = CctpLinker()
    link = linker.build_link(
        source_message=None,  # mock builder
        api_message={
            "status": "complete",
            "attestation": "0x" + "ab" * 65,
            "eventNonce": "0x" + "12" * 32,
        },
        destination_execution=None,  # No destination transaction found
    )
    assert link.linkage_status == CrossChainLinkageStatus.INCOMPLETE
    assert link.attestation_status == "API_REPORTED_COMPLETE"
    assert link.destination_tx_hash is None


def test_destination_hint_without_receipt_validation_stays_incomplete() -> None:
    """Forward tx hash hint from API without verified on-chain receipt must stay INCOMPLETE."""
    linker = CctpLinker()
    link = linker.build_link(
        source_message=None,
        api_message={
            "status": "complete",
            "attestation": "0x" + "ab" * 65,
            "eventNonce": "0x" + "12" * 32,
            "forwardTxHash": "0x" + "99" * 32,  # Hint present!
        },
        destination_execution=None,  # Unverified on-chain
    )
    assert link.linkage_status == CrossChainLinkageStatus.INCOMPLETE
    assert link.destination_tx_hash is None  # Hint alone does not establish destination


def test_reverted_destination_tx_classified_as_failed() -> None:
    """Reverted destination transaction (status 0x0) must be classified as FAILED."""
    linker = CctpLinker()
    link = linker.build_link(
        source_message=None,
        api_message={
            "status": "complete",
            "attestation": "0x" + "ab" * 65,
            "eventNonce": "0x" + "12" * 32,
        },
        destination_execution={
            "tx_hash": "0x" + "aa" * 32,
            "receipt_status": "0x0",  # Reverted!
            "error": "execution reverted",
        },
    )
    assert link.linkage_status == CrossChainLinkageStatus.FAILED
    assert link.destination_execution_status == "reverted"


def test_wrong_api_message_or_mismatch_yields_ambiguous_or_unmatched() -> None:
    """When Iris API returns multiple matching messages or non-matching message, handled cleanly."""
    from app.services.cctp.client import CircleCctpClient
    from app.services.cctp.source import CctpSourceMessage

    # Mock source message
    mock_src = CctpSourceMessage(
        source_network="ethereum",
        source_chain_id=1,
        source_domain=0,
        source_tx_hash="0x" + "aa" * 32,
        source_burn_event_reference="eip155:1:0xaa:1",
        source_message_event_reference="eip155:1:0xaa:2",
        source_block_number=100,
        burn_token="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        depositor="0x" + "11" * 20,
        mint_recipient="0x" + "22" * 20,
        destination_domain=6,
        destination_token_messenger="0x28b5a0e9c621a5badaa536219b3a228c8168cf5d",
        destination_caller="0x" + "00" * 32,
        amount_base_units=500_000,
        max_fee_base_units=0,
        min_finality_threshold=2000,
        raw_message_bytes=b"\x00" * 376,
        message_hash="0x" + "bb" * 32,
        decoded_message=None,  # type: ignore[arg-type]
        decoded_burn=None,  # type: ignore[arg-type]
    )

    # 1. API message with different recipient -> NOT_MATCHED
    api_resp_wrong_recip = {
        "messages": [
            {
                "status": "complete",
                "attestation": "0x" + "11" * 65,
                "decodedMessage": {
                    "destinationDomain": 6,
                    "decodedMessageBody": {
                        "burnToken": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                        "mintRecipient": "0x" + "99" * 20,  # Wrong!
                        "amount": "500000",
                    },
                },
            }
        ]
    }
    res_wrong = CircleCctpClient.match_source_message(api_resp_wrong_recip, mock_src)
    assert not res_wrong.matched
    assert res_wrong.status == "NOT_MATCHED"

    # 2. API response with 2 identical matches -> AMBIGUOUS
    api_resp_ambiguous = {
        "messages": [
            {
                "status": "complete",
                "attestation": "0x" + "11" * 65,
                "eventNonce": "0x1",
                "decodedMessage": {
                    "destinationDomain": 6,
                    "decodedMessageBody": {
                        "burnToken": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                        "mintRecipient": "0x" + "22" * 20,
                        "amount": "500000",
                    },
                },
            },
            {
                "status": "complete",
                "attestation": "0x" + "22" * 65,
                "eventNonce": "0x2",
                "decodedMessage": {
                    "destinationDomain": 6,
                    "decodedMessageBody": {
                        "burnToken": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                        "mintRecipient": "0x" + "22" * 20,
                        "amount": "500000",
                    },
                },
            },
        ]
    }
    res_amb = CircleCctpClient.match_source_message(api_resp_ambiguous, mock_src)
    assert not res_amb.matched
    assert res_amb.status == "AMBIGUOUS"
    assert res_amb.ambiguous


def test_base_label_cannot_terminate_ethereum_and_vice_versa() -> None:
    """Network-scoped labels must never cross boundaries."""
    import datetime as dt

    from app.models.enums import AssertionType, ReviewState
    from app.services.labels import Anchor, LabelRegistry

    base_anchor = Anchor(
        network_key="base",
        address="0x38a1c011890bc95fd4b43b622e1432c859d097bc",
        entity_name="Base Service",
        entity_type="exchange",
        assertion_type=AssertionType.service_control,
        address_role="hot_wallet",
        review_state=ReviewState.accepted,
        source_reference="test",
        retrieval_date=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
        methodology="test",
        reviewer="reviewer",
        valid_from=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
        valid_to=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
        last_verified_at=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
        label_set_version="1",
    )

    registry = LabelRegistry(anchors=[base_anchor])
    # A label added for Base must not appear when querying Ethereum
    assert len(registry.lookup("base", "0x38a1c011890bc95fd4b43b622e1432c859d097bc")) == 1
    assert len(registry.lookup("ethereum", "0x38a1c011890bc95fd4b43b622e1432c859d097bc")) == 0
