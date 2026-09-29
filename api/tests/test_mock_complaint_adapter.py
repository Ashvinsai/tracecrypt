"""Stage 4: the MOCK complaint intake.

Pure file-reading tests against the real fixture at
fixtures/mock_complaints.json, plus fixture-path-safety tests against a
tmp_path fixture built by hand.
"""

from __future__ import annotations

import json

import pytest

from app.services.mock_complaint_adapter import (
    SOURCE_CHANNEL,
    MockComplaintAdapterError,
    get_mock_complaint,
    list_mock_complaints,
    mock_complaint_to_seed_draft,
)


def test_the_real_fixture_loads_and_every_complaint_names_the_mock_channel() -> None:
    complaints = list_mock_complaints()
    assert complaints, "fixtures/mock_complaints.json should carry at least one row"
    for c in complaints:
        assert c.to_json()["source_channel"] == SOURCE_CHANNEL


def test_the_real_fixture_never_links_a_real_government_portal() -> None:
    """The fixture's own disclaimer legitimately names NCRP/SAHYOG in prose
    (to disclaim them), so this checks for an actual URL/endpoint reference
    instead of banning the bare words."""
    import re

    from app.services.mock_complaint_adapter import _DEFAULT_FIXTURE_PATH

    text = _DEFAULT_FIXTURE_PATH.read_text()
    urls = re.findall(r"https?://\S+", text, flags=re.IGNORECASE)
    for url in urls:
        lowered = url.lower()
        assert "ncrp.gov" not in lowered
        assert "sahyog" not in lowered
        assert "cybercrime.gov.in" not in lowered


def test_get_mock_complaint_finds_a_known_reference() -> None:
    complaint = get_mock_complaint("MOCK-Q-2026-000101")
    assert complaint is not None
    assert complaint.network_key == "tron"
    assert complaint.reported_address == "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"


def test_get_mock_complaint_returns_none_for_an_unknown_reference() -> None:
    assert get_mock_complaint("MOCK-Q-DOES-NOT-EXIST") is None


def test_seed_draft_for_a_complaint_with_a_seed_event_is_incident_mode() -> None:
    complaint = get_mock_complaint("MOCK-Q-2026-000101")
    assert complaint is not None
    draft = mock_complaint_to_seed_draft(complaint)
    assert draft["mode"] == "incident"
    assert draft["transfer_event_reference"] == "tron:tx_seed_multi:0"
    assert draft["amount_base_units"] == "100000000"
    assert draft["source"]["complaint_reference"] == "MOCK-Q-2026-000101"
    assert draft["source"]["channel"] == SOURCE_CHANNEL


def test_seed_draft_for_a_complaint_with_no_seed_event_is_address_discovery_mode() -> None:
    complaint = get_mock_complaint("MOCK-Q-2026-000102")
    assert complaint is not None
    assert complaint.seed_event_reference is None
    draft = mock_complaint_to_seed_draft(complaint)
    assert draft["mode"] == "address_discovery"
    # address_discovery asserts nothing about victim funds (PRD section 2),
    # so no amount is carried even though the complainant reported one.
    assert draft["amount_base_units"] is None


def test_seed_draft_never_invents_an_asset_id() -> None:
    complaint = get_mock_complaint("MOCK-Q-2026-000101")
    assert complaint is not None
    draft = mock_complaint_to_seed_draft(complaint)
    assert "asset_id" not in draft
    assert draft["token_contract"] == "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY"


def test_seed_draft_states_that_nothing_has_been_submitted() -> None:
    complaint = get_mock_complaint("MOCK-Q-2026-000101")
    assert complaint is not None
    draft = mock_complaint_to_seed_draft(complaint)
    assert "nothing has been submitted" in draft["note"]


def test_missing_fixture_file_raises(tmp_path) -> None:
    with pytest.raises(MockComplaintAdapterError, match="not found"):
        list_mock_complaints(fixture_path=tmp_path / "does-not-exist.json")


def test_fixture_with_the_wrong_source_channel_is_refused(tmp_path) -> None:
    """A basic guard against accidentally pointing this loader at some other
    project's JSON file: it must declare itself as this queue, or it is
    refused rather than silently loaded."""
    bad = tmp_path / "not-ours.json"
    bad.write_text(json.dumps({"source_channel": "SOMETHING_ELSE", "complaints": []}))
    with pytest.raises(MockComplaintAdapterError, match="source_channel"):
        list_mock_complaints(fixture_path=bad)


def test_a_custom_well_formed_fixture_loads_via_the_explicit_path(tmp_path) -> None:
    custom = tmp_path / "custom.json"
    custom.write_text(
        json.dumps(
            {
                "source_channel": SOURCE_CHANNEL,
                "complaints": [
                    {
                        "complaint_reference": "MOCK-TEST-1",
                        "received_at": "2026-01-01T00:00:00Z",
                        "network_key": "tron",
                        "reported_address": "TSomething0000000000000000000000000",
                        "asset": {"token_contract": None, "display_symbol": "TRX"},
                        "reported_transaction_hash": None,
                        "seed_event_reference": None,
                        "incident_time": None,
                        "amount_reported_base_units": None,
                        "incident_summary": "FICTIONAL test row.",
                        "reporter_contact": "FICTIONAL -- test@example.test",
                        "category": "other",
                    }
                ],
            }
        )
    )
    complaints = list_mock_complaints(fixture_path=custom)
    assert len(complaints) == 1
    assert complaints[0].complaint_reference == "MOCK-TEST-1"
