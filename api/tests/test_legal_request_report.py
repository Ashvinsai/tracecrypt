"""HTML rendering of a legal-request draft."""

from __future__ import annotations

from app.reports.legal_request import render_request_draft_html


def _draft(**overrides) -> dict:
    draft = {
        "status": "drafted",
        "request_kind": "information",
        "refusal_reason": None,
        "target": {
            "address": "TService0000000000000000000000000",
            "network_key": "tron",
            "endpoint_class": "known_service",
            "attribution_status": "supported",
            "address_role": "deposit",
            "review_state": "accepted",
            "entity_name": "Northwind Exchange (FICTIONAL)",
        },
        "checklist": [
            {
                "key": "legal_authority_reference",
                "label": "A signed court order...",
                "value": "NOT PROVIDED -- required before this draft may be sent",
                "provided": False,
                "required_by": "provider",
            },
        ],
        "identifiers": {
            "network_key": "tron",
            "seed_address": "TVictim000000000000000000000000000",
            "target_address": "TService0000000000000000000000000",
            "observed_transaction_hashes": ["tx_seed", "tx_hop1"],
            "observed_transaction_count": 2,
            "note": "see the evidence export bundle",
        },
        "checklist_source": {
            "provider": "OKX",
            "source_reference": "https://www.okx.com/help/okx-law-enforcement-request-guide",
            "retrieved_at": "2026-09-22",
            "submission_channel": "Kodex portal",
        },
        "draft_marker": (
            "DRAFT -- INVESTIGATOR REVIEW REQUIRED. This is not legal process, "
            "establishes no legal authority, has not been sent to any "
            "provider, and was not signed or authorised by any officer."
        ),
        "generated_at": "2026-09-22T12:00:00+00:00",
    }
    draft.update(overrides)
    return draft


def test_drafted_page_states_its_status_and_marker() -> None:
    page = render_request_draft_html(_draft())
    assert "DRAFT" in page
    assert "REFUSED" not in page.split("</style>", 1)[1]
    flat = " ".join(page.split())
    assert "not legal process" in flat
    assert "has not been sent" in flat


def test_refused_page_shows_the_refusal_reason() -> None:
    draft = _draft(
        status="refused",
        request_kind="asset_restriction",
        refusal_reason="TService... carries address_role=hot_wallet: a pooled address.",
    )
    page = render_request_draft_html(draft)
    assert "REFUSED" in page
    assert "This draft was refused" in page
    assert "pooled address" in page


def test_checklist_field_not_provided_is_shown_as_no() -> None:
    page = render_request_draft_html(_draft())
    assert ">NO<" in page


def test_checklist_source_and_tx_hashes_are_rendered() -> None:
    page = render_request_draft_html(_draft())
    assert "okx.com/help/okx-law-enforcement-request-guide" in page
    assert "tx_seed" in page and "tx_hop1" in page


def test_hostile_text_in_target_entity_name_is_escaped() -> None:
    draft = _draft()
    draft["target"]["entity_name"] = "<script>alert(1)</script>"
    page = render_request_draft_html(draft)
    body = page.split("</style>", 1)[1]
    assert "<script" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_hostile_text_in_refusal_reason_is_escaped() -> None:
    draft = _draft(status="refused", refusal_reason="<img src=x onerror=alert(1)>")
    page = render_request_draft_html(draft)
    body = page.split("</style>", 1)[1]
    assert "<img" not in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body
