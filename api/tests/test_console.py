"""Tests for the local investigator console.

Two layers:

* Pure-render tests build a ``DemoView`` in memory, so they prove the escaping
  and display rules without depending on any saved artifact.
* Integration tests hit the real ``/console`` routes against the artifacts on
  disk. They skip (never fail) when this checkout has no ``var/`` bundle, so a
  fresh clone does not go red just because the demo data is missing.

Nothing here needs a model, a provider, or a live chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.reports.console import (
    _anomaly_evaluation_card,
    _copyable,
    _effective_transfer_rows,
    render_console_html,
    render_dashboard_html,
)
from app.services.demo_presets import (
    PRESETS,
    DemoView,
    Preset,
    PresetPathError,
    _saved_preset,
    all_presets,
    discover_presets,
    find_preset_by_address,
    load_preset,
)
from app.services.operational_status import build_capabilities, verify_manifest_hashes

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDED_TRACE = REPO_ROOT / "var" / "live-validation" / "20260920T090201Z-969305" / "trace.json"
SYNTHETIC_TRACE = REPO_ROOT / "var" / "trace.json"
MULTIHOP_TRACE = REPO_ROOT / "var" / "live-validation" / "20260926T103814Z-f75259" / "trace.json"
MULTIHOP_RECEIPTS = MULTIHOP_TRACE.with_name("receipts.json")
MULTIHOP_EXPORT_MANIFEST = (
    REPO_ROOT / "var" / "evidence-export" / "20260926T103814Z-f75259" / "manifest.json"
)

requires_recorded = pytest.mark.skipif(
    not RECORDED_TRACE.is_file(), reason="saved recorded demo artifacts are not present"
)
requires_synthetic = pytest.mark.skipif(
    not SYNTHETIC_TRACE.is_file(), reason="saved synthetic demo artifacts are not present"
)


# --------------------------------------------------------------------------
# In-memory fixtures (no disk dependency)
# --------------------------------------------------------------------------


def _preset(**overrides: Any) -> Preset:
    base: dict[str, Any] = {
        "id": "test-preset",
        "title": "Test preset",
        "scenario": "supported",
        "data_mode": "RECORDED_PUBLIC",
        "address": "TSeedAddress000000000000000000000",
        "description": "A test preset.",
        "trace": "var/does-not-need-to-exist.json",
        "scope_note": "Scope note.",
    }
    base.update(overrides)
    return Preset(**base)


def _trace(
    *,
    data_mode: str = "RECORDED_PUBLIC",
    seed_address: str = "TSeedAddress000000000000000000000",
    endings: list[dict[str, Any]] | None = None,
    transfers: list[dict[str, Any]] | None = None,
    limitations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "seed": {
            "address": seed_address,
            "event_reference": "tron:abcdef:0",
            "network_key": "tron",
            "asset": {
                "token_contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                "display_symbol": "USDT",
                "decimals": 6,
            },
        },
        "scope": {
            "data_mode": data_mode,
            "analysis_cutoff": "2026-08-10T15:59:55+00:00",
            "started_at": "2026-09-20T00:00:00+00:00",
            "finished_at": "2026-09-20T00:00:01+00:00",
            "engine_version": "0.1.0",
            "label_set_version": "0",
            "coverage_status": "complete_within_scope",
            "case_flow_linkage": "established",
            "label_snapshot": {},
        },
        "observed_transfers": transfers or [],
        "branch_endings": endings or [],
        "limitations": limitations or [],
    }


def _ending(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "address": "TEndingAddress0000000000000000000",
        "endpoint_class": "known_service",
        "attribution_status": "supported",
        "boundary_reason": "service_boundary",
        "hop_depth": 0,
        "branch_path": ["tron:abcdef:0"],
        "arrival_event_reference": "tron:abcdef:0",
        "observed_amount_base_units": "72140000",
        "observed_amount_display": "72.140000",
        "case_amount_basis": "allocation_unknown",
        "label": {
            "entity_name": "Example Exchange",
            "entity_type": "exchange",
            "assertion_type": "service_control",
            "address_role": "unknown",
            "review_state": "accepted",
            "source_reference": "https://example.test/disclosure",
            "retrieval_date": "2026-09-20T00:00:00+00:00",
            "methodology": "A saved methodology.",
            "reviewer": "prepared-for-review",
            "valid_from": "2026-08-10T15:59:54+00:00",
            "valid_to": "2026-08-10T15:59:54+00:00",
            "last_verified_at": "2026-09-20T00:00:00+00:00",
            "label_set_version": "test-0",
            "source_hash": "deadbeef",
            "review_reference": "deadbeef@2026-09-20T00:00:00+00:00",
        },
        "note": None,
    }
    base.update(overrides)
    return base


def _outcome(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "claim_id": "TSeed->TEnding:direct-seed-transfer",
        "category": "supported_destination",
        "service_name": "Example Exchange",
        "evidence_references": [{"kind": "seed_transfer", "evidence_id": "id-1"}],
        "reason_codes": [],
        "unresolved": ["The candidate's own ownership and role remain unknown."],
        "window_start": "2026-08-10T15:59:54+00:00",
        "window_end": "2026-08-10T15:59:54+00:00",
        "policy_version": None,
        "execution_status": "success",
        "coverage_status": "complete_within_scope",
        "attribution_status": "supported",
        "case_flow_linkage": "established",
        "acquisition_completeness": "complete_within_scope",
        "verification_quality": "receipt_verified",
        "event_identity_quality": "receipt_event_index",
        "ordering_quality": "precise",
    }
    base.update(overrides)
    return base


def _render(view: DemoView | None, **kwargs: Any) -> str:
    return render_console_html(
        view=view,
        presets=(view.preset if view else _preset(),),
        readiness=None,
        wallet_states=None,
        address_query="",
        **kwargs,
    )


# --------------------------------------------------------------------------
# Pure-render tests
# --------------------------------------------------------------------------


def test_data_mode_label_is_shown_and_recorded_is_not_live() -> None:
    view = DemoView(preset=_preset(), trace=_trace(data_mode="RECORDED_PUBLIC"))
    html = _render(view)
    assert "RECORDED PUBLIC" in html
    assert "not a live chain connection" in html


def test_synthetic_mode_label_cannot_disappear() -> None:
    view = DemoView(preset=_preset(data_mode="SYNTHETIC"), trace=_trace(data_mode="SYNTHETIC"))
    html = _render(view)
    assert "SYNTHETIC" in html
    assert "every address and service name is fictional" in html


def test_supported_destination_renders_from_outcome() -> None:
    view = DemoView(
        preset=_preset(),
        trace=_trace(endings=[_ending()]),
        outcome=_outcome(category="supported_destination", service_name="Example Exchange"),
    )
    html = _render(view)
    assert "Supported destination: Example Exchange" in html


def test_candidate_lead_is_not_rendered_as_supported_destination() -> None:
    view = DemoView(
        preset=_preset(),
        trace=_trace(endings=[_ending(endpoint_class="deposit_candidate")]),
        outcome=_outcome(
            category="candidate_lead",
            service_name="Example Exchange",
            verification_quality="history_only",
            reason_codes=["insufficient_verification"],
        ),
    )
    html = _render(view)
    assert "Candidate lead: Example Exchange (not an accepted destination)" in html
    assert "Supported destination: Example Exchange" not in html


def test_unknown_or_blocked_does_not_name_a_service() -> None:
    view = DemoView(
        preset=_preset(),
        trace=_trace(endings=[_ending(endpoint_class="unresolved")]),
        outcome=_outcome(
            category="unknown_or_blocked",
            service_name=None,
            reason_codes=["no_accepted_label"],
        ),
    )
    html = _render(view)
    assert "Supported destination" not in html
    assert "Unknown / blocked" in html


def test_all_eight_status_axes_are_independent() -> None:
    outcome = _outcome(
        execution_status="success",
        coverage_status="complete_within_scope",
        attribution_status="supported",
        case_flow_linkage="established",
        acquisition_completeness="complete_within_scope",
        verification_quality="receipt_verified",
        event_identity_quality="receipt_event_index",
        ordering_quality="precise",
    )
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=outcome)
    html = _render(view)
    for axis, value in outcome.items():
        if axis.endswith("_status") or axis.endswith("_quality") or axis in (
            "case_flow_linkage",
            "acquisition_completeness",
        ):
            assert axis in html
            assert value in html
    assert "never collapsed into one confidence score" in html


def test_exact_amounts_stay_strings_and_are_not_rounded() -> None:
    big_base = "123456789012345678901234567890"
    big_display = "123456789012345678901234.567890"
    transfer = {
        "hop_depth": 1,
        "block_time": "2026-08-10T15:59:50+00:00",
        "from_address": "TFrom",
        "to_address": "TTo",
        "amount_base_units": big_base,
        "amount_display": big_display,
        "asset": {"display_symbol": "USDT"},
        "event_reference": "tron:tx:0",
        "tx_hash": "tx",
        "execution_status": "success",
        "confirmation_state": "confirmed",
        "ordering_ambiguous": False,
    }
    view = DemoView(preset=_preset(), trace=_trace(transfers=[transfer]))
    html = _render(view)
    assert big_base in html
    assert big_display in html


def test_console_prefers_the_first_class_seed_transfer() -> None:
    onward = {
        "hop_depth": 1,
        "block_time": "2026-08-10T16:00:00+00:00",
        "from_address": "TEndingAddress0000000000000000000",
        "to_address": "TNext",
        "amount_base_units": "5000000",
        "amount_display": "5.000000",
        "asset": {"display_symbol": "USDT"},
        "event_reference": "tron:onward:0",
        "tx_hash": "onward",
        "execution_status": "success",
        "confirmation_state": "confirmed",
        "ordering_ambiguous": False,
    }
    trace = _trace(transfers=[onward])
    trace["seed_transfer"] = {
        "hop_depth": 0,
        "block_time": "2026-08-10T15:59:54+00:00",
        "from_address": "TSeedAddress000000000000000000000",
        "to_address": "TEndingAddress0000000000000000000",
        "amount_base_units": "72140000",
        "amount_display": "72.140000",
        "asset": {"display_symbol": "USDT"},
        "event_reference": "tron:abcdef:0",
        "tx_hash": "abcdef",
        "execution_status": "success",
        "confirmation_state": "confirmed",
        "ordering_ambiguous": False,
    }
    view = DemoView(preset=_preset(), trace=trace)
    rows = _effective_transfer_rows(view)
    assert rows[0]["seed_row"] is True
    assert rows[0]["hop"] == 0
    assert rows[0]["amount"] == "72.140000"
    assert rows[0]["time"] == "2026-08-10T15:59:54+00:00"
    assert rows[1]["event"] == "tron:onward:0"
    assert "Hop 0 is the seed transfer" in _render(view)


def test_allocation_unknown_is_visible() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]))
    html = _render(view)
    assert "allocation_unknown" in html


def test_walkthrough_renders_five_steps_on_overview() -> None:
    from app.reports.console import render_landing_html

    html = render_landing_html()
    assert "How this works" in html
    # The how-it-works animation is capped at five steps.
    assert html.count("class='walk-step") == 5
    assert "js-walk-play" in html
    assert "js-walk-step" in html
    assert "js-walk-reset" in html
    assert 'aria-live="polite"' in html
    assert "No live call is made" in html
    assert "Generated" not in html  # no wall-clock content in the walkthrough


def test_console_keeps_only_the_path_replay_animation() -> None:
    # The demo page keeps the path replay; the how-it-works animation lives on
    # the Overview page so the demo shows only its five primary sections.
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    html = _render(view)
    assert "How this works" not in html
    assert 'id="walk-steps"' not in html
    assert "js-replay-play" in html


def test_walkthrough_absent_without_a_trace() -> None:
    view = DemoView(
        preset=_preset(trace="var/nope.json"),
        trace=None,
        error="No saved trace result was found for this preset.",
    )
    html = _render(view)
    assert "How this works" not in html
    assert 'id="walk-steps"' not in html


def test_reduced_motion_and_dark_mode_css_present() -> None:
    html = _render(DemoView(preset=_preset(), trace=_trace()))
    assert "prefers-reduced-motion: reduce" in html
    assert "prefers-color-scheme: dark" in html
    # Autoplay must be gated on the reduced-motion query, not unconditional.
    assert "reducedMotion" in html


def test_path_nodes_carry_replay_order_and_legend() -> None:
    html = _render(DemoView(preset=_preset(), trace=_trace(endings=[_ending()])))
    assert "data-order='1'" in html
    assert "js-path-node" in html
    assert "js-replay-paths" in html
    assert "supported service boundary" in html
    assert "candidate lead" in html


def test_page_has_landmarks_and_no_external_scripts() -> None:
    html = _render(DemoView(preset=_preset(), trace=_trace(endings=[_ending()])))
    assert 'href="#result"' in html
    assert "skip-link" in html
    assert '<main id="result"' in html
    assert "<script src" not in html.lower()
    assert "accuracy" not in html.lower()
    assert "auc" not in html.lower()
    assert "ai-powered" not in html.lower()


def test_unknown_ownership_is_not_rewritten_as_service_ownership() -> None:
    view = DemoView(
        preset=_preset(),
        trace=_trace(endings=[_ending()]),
        outcome=_outcome(),
    )
    html = _render(view)
    assert "any intermediary on the path belongs to the" in html
    assert "own ownership and role remain unknown" in html


def test_hostile_label_text_is_escaped() -> None:
    hostile = "<script>alert('x')</script>"
    ending = _ending(
        address='TBad" onmouseover="alert(1)',
        label={
            **_ending()["label"],
            "entity_name": hostile,
            "source_reference": f"https://example.test/{hostile}",
            "methodology": f"</pre><img src=x onerror=alert(2)>{hostile}",
        },
    )
    view = DemoView(
        preset=_preset(address=hostile),
        trace=_trace(seed_address=hostile, endings=[ending]),
    )
    html = _render(view)
    assert "<script>alert('x')</script>" not in html
    assert "<img src=x onerror=alert(2)>" not in html
    assert "onmouseover=\"alert(1)\"" not in html
    assert "&lt;script&gt;" in html


def test_no_saved_result_is_not_an_empty_success() -> None:
    view = DemoView(
        preset=_preset(trace="var/nope.json"),
        trace=None,
        error="No saved trace result was found for this preset.",
    )
    html = _render(view)
    assert "No saved result" in html
    assert "Supported destination" not in html


def test_missing_transfer_rows_do_not_read_as_no_activity() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[]))
    html = _render(view)
    assert "not the same as no activity" in html
    assert "Supported destination" not in html


def test_readiness_card_reports_no_model_trained() -> None:
    readiness = {
        "status": "NOT_READY_FOR_REAL_EVALUATION",
        "real_wallet_count": 2,
        "accepted_real_registry_record_count": 1,
        "materialized_window_count_real": 0,
        "model_dataset_split_feasible": False,
        "no_model_trained_in_this_report": True,
        "status_reasons": ["2 real evaluation wallets on file"],
        "unresolved_blockers": [],
    }
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]))
    html = render_console_html(
        view=view,
        presets=(view.preset,),
        readiness=readiness,
        wallet_states={"accepted": 1, "quarantined": 1},
    )
    assert "No anomaly model trained" in html
    assert "NOT_READY_FOR_REAL_EVALUATION" in html
    assert "accuracy" not in html.lower()
    assert "auc" not in html.lower()


def test_path_escaping_repository_root_is_refused() -> None:
    outside = _preset(trace="../../../../etc/passwd")
    with pytest.raises(PresetPathError):
        load_preset(outside)


def test_find_preset_by_address_is_exact_and_offline() -> None:
    assert find_preset_by_address(PRESETS[0].address) is not None
    assert find_preset_by_address(PRESETS[0].address.lower()) is not None
    assert find_preset_by_address("TNotASavedAddress") is None
    assert find_preset_by_address("") is None


# --------------------------------------------------------------------------
# Integration tests against the saved artifacts on this machine
# --------------------------------------------------------------------------


@requires_recorded
def test_index_route_loads(client: TestClient) -> None:
    response = client.get("/console")
    assert response.status_code == 200
    assert "Crypto Attribution Triage" in response.text
    assert "LOCAL PROTOTYPE" in response.text
    assert "Investigation input" in response.text
    assert "Demo examples" in response.text


@requires_recorded
def test_recorded_preset_loads_with_outcome_and_readiness(client: TestClient) -> None:
    response = client.get("/console?preset=recorded-okx-direct")
    assert response.status_code == 200
    text = response.text
    assert "RECORDED PUBLIC" in text
    assert "Supported destination: OKX" in text
    assert "No anomaly model trained" in text
    assert "allocation_unknown" in text
    # The seed arrival time is joined from the separately saved behavioral
    # acquisition by tx_hash and labelled as such.
    assert "2026-08-10T15:59:54+00:00" in text


@requires_synthetic
def test_synthetic_preset_is_labelled_and_shows_unresolved(client: TestClient) -> None:
    response = client.get("/console?preset=synthetic-multihop")
    assert response.status_code == 200
    text = response.text
    assert "SYNTHETIC" in text
    assert "unresolved" in text
    assert "Northwind Exchange (FICTIONAL)" in text


@requires_recorded
def test_unknown_address_is_reported_not_emptied(client: TestClient) -> None:
    # A valid TRON address that is not a saved preset seed.
    response = client.get("/console?address=TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv")
    assert response.status_code == 200
    assert "No saved result matches" in response.text
    assert "Supported destination" not in response.text


@requires_recorded
def test_malformed_address_is_reported_as_invalid_not_as_no_activity(
    client: TestClient,
) -> None:
    response = client.get("/console?address=definitely-not-an-address")
    assert response.status_code == 200
    assert "not a valid TRON address" in response.text
    assert "No saved result matches" not in response.text


def test_console_route_is_registered_in_non_prod() -> None:
    from app.main import app

    assert "/console" in app.openapi()["paths"]


def test_console_route_is_not_registered_in_prod(monkeypatch: Any) -> None:
    import app.main as main
    from app.core.settings import AppEnv, DataMode, Settings

    prod = Settings(
        app_env=AppEnv.prod,
        data_mode=DataMode.SYNTHETIC,
        secret_key="x" * 40,
    )
    monkeypatch.setattr(main, "get_settings", lambda: prod)
    prod_app = main.create_app()
    assert "/console" not in prod_app.openapi()["paths"]


def test_saved_bundle_is_normalized_to_recorded_public() -> None:
    """A saved bundle must never wear a LIVE badge, whatever the capture mode."""

    trace_path = REPO_ROOT / "var" / "live-validation" / "fake-run" / "trace.json"
    trace = _trace(data_mode="LIVE")
    preset = _saved_preset("fake-run", trace_path, trace)
    assert preset is not None
    assert preset.data_mode == "RECORDED_PUBLIC"
    assert "LIVE" in preset.scope_note
    assert preset.id == "saved-fake-run"


def test_all_presets_keeps_synthetic_first_and_unique() -> None:
    presets = all_presets()
    assert presets[0].id == "synthetic-multihop"
    assert presets[: len(PRESETS)] == PRESETS
    ids = [p.id for p in presets]
    assert len(ids) == len(set(ids))


def test_console_defaults_to_synthetic_preset(client: TestClient, monkeypatch: Any) -> None:
    from app.routes import console

    loaded: list[str] = []

    def load_synthetic(preset: Preset) -> DemoView:
        loaded.append(preset.id)
        return DemoView(preset=preset, trace=_trace(data_mode="SYNTHETIC"))

    monkeypatch.setattr(console, "load_preset", load_synthetic)
    response = client.get("/console")

    assert response.status_code == 200
    assert loaded == ["synthetic-multihop"]
    assert "SYNTHETIC" in response.text


def test_optional_multihop_preset_is_hidden_without_its_complete_artifacts(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from app.services import demo_presets

    monkeypatch.setattr(demo_presets, "REPO_ROOT", tmp_path)
    presets = demo_presets.all_presets()

    assert presets[0].id == "synthetic-multihop"
    assert "recorded-tron-multihop" not in {preset.id for preset in presets}


def test_missing_recorded_artifacts_remain_distinct_from_synthetic_default(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from app.services import demo_presets

    monkeypatch.setattr(demo_presets, "REPO_ROOT", tmp_path)
    synthetic_trace = _trace(data_mode="SYNTHETIC")
    synthetic_trace_path = (tmp_path / "var" / "trace.json").resolve()
    monkeypatch.setattr(
        demo_presets,
        "_read_json",
        lambda path: synthetic_trace if path == synthetic_trace_path else None,
    )
    synthetic = demo_presets.load_preset("synthetic-multihop")
    recorded = demo_presets.load_preset("recorded-okx-direct")

    assert synthetic.trace is synthetic_trace
    assert synthetic.error is None
    assert recorded.trace is None
    assert recorded.error is not None
    assert synthetic.preset.data_mode == "SYNTHETIC"
    assert recorded.preset.data_mode == "RECORDED_PUBLIC"


@pytest.mark.skipif(
    not MULTIHOP_TRACE.is_file() or not MULTIHOP_RECEIPTS.is_file(),
    reason="recorded multi-hop validation bundle is not present",
)
def test_recorded_multihop_trace_has_receipt_ordered_supported_boundary() -> None:
    import json

    trace = json.loads(MULTIHOP_TRACE.read_text())
    receipts = json.loads(MULTIHOP_RECEIPTS.read_text())["receipts"]
    branch = next(
        ending
        for ending in trace["branch_endings"]
        if ending["address"] == "TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir"
    )
    transfers = {
        transfer["event_reference"]: transfer
        for transfer in [trace["seed_transfer"], *trace["observed_transfers"]]
    }
    path = [transfers[reference] for reference in branch["branch_path"]]
    receipt_rows = [receipts[transfer["tx_hash"]] for transfer in path]

    assert len(path) == 3
    assert all(
        transfer["asset"]["token_contract"]
        == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        for transfer in path
    )
    assert all(
        path[index]["to_address"] == path[index + 1]["from_address"]
        for index in range(len(path) - 1)
    )
    assert all(
        path[index]["block_time"] < path[index + 1]["block_time"]
        for index in range(len(path) - 1)
    )
    assert all(
        receipt["receipt_result"] == "SUCCESS" and receipt["solidified"]
        for receipt in receipt_rows
    )
    assert [receipt["block_number"] for receipt in receipt_rows] == sorted(
        receipt["block_number"] for receipt in receipt_rows
    )
    assert branch["endpoint_class"] == "known_service"
    assert branch["boundary_reason"] == "service_boundary"
    assert branch["attribution_status"] == "supported"
    assert branch["case_amount_basis"] == "allocation_unknown"
    assert branch["label"]["assertion_type"] == "service_control"
    assert branch["label"]["review_state"] == "accepted"
    assert branch["label"]["entity_name"] == "OKX"
    assert branch["label"]["valid_from"] == "2026-08-10T15:59:54+00:00"
    assert branch["label"]["valid_to"] == "2026-08-10T15:59:54+00:00"
    assert path[-1]["block_time"] == branch["label"]["valid_from"]
    assert all(
        ending["endpoint_class"] != "known_service"
        for ending in trace["branch_endings"]
        if not ending.get("label")
        or ending["label"].get("assertion_type") != "service_control"
    )
    assert any(ending["endpoint_class"] == "unresolved" for ending in trace["branch_endings"])


def test_optional_multihop_preset_loads_as_recorded_public_when_complete() -> None:
    presets = {preset.id: preset for preset in all_presets()}
    preset = presets["recorded-tron-multihop"]
    view = load_preset(preset)

    assert preset.data_mode == "RECORDED_PUBLIC"
    assert view.trace is not None
    assert view.trace["scope"]["data_mode"] == "RECORDED_PUBLIC"
    assert view.error is None
    assert view.has_report
    assert view.outcome is None
    assert preset.required_artifacts
    assert all((REPO_ROOT / artifact).is_file() for artifact in preset.required_artifacts)


@pytest.mark.skipif(
    not MULTIHOP_EXPORT_MANIFEST.is_file(), reason="multi-hop evidence export is not present"
)
def test_multihop_export_manifest_matches_offline_recorded_trace() -> None:
    import json

    manifest = json.loads(MULTIHOP_EXPORT_MANIFEST.read_text())
    export_dir = MULTIHOP_EXPORT_MANIFEST.parent
    result = verify_manifest_hashes(manifest, export_dir)

    assert len(manifest["files"]) == 7
    assert result["checked"] == 7
    assert result["failed"] == 0
    assert result["missing"] == 0
    assert (export_dir / "evidence.json").is_file()
    assert (export_dir / "evidence.pdf").read_bytes().startswith(b"%PDF")


def test_saved_neighborhood_report_is_distinct_from_trace_preset(client: TestClient) -> None:
    response = client.get("/neighborhood/vasp/20260926T143630Z-aab422")

    assert response.status_code == 200
    assert "RECORDED PUBLIC" in response.text
    assert "Reviewed service_control anchor" in response.text
    assert "Candidate relationship: deposit_candidate" in response.text
    assert "Review:</strong> unreviewed" in response.text
    assert "does not establish service ownership" in response.text
    assert "Supported service" not in response.text
    assert "84025aacbd098c91c8ea240481c6304d528807a84d3591246c06782071709997:0" in response.text


def test_neighborhood_report_route_rejects_path_traversal(client: TestClient) -> None:
    response = client.get("/neighborhood/vasp/..%2F..%2Fetc")
    assert response.status_code == 404


def test_neighborhood_report_escapes_saved_candidate_text(
    client: TestClient, monkeypatch: Any, tmp_path: Path
) -> None:
    from app.routes import console

    run_id = "fixture-neighborhood"
    report_root = tmp_path / "var" / "vasp-neighborhood"
    run_dir = report_root / run_id
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(console, "NEIGHBORHOOD_RUNS_DIR", report_root)
    report = {
        "report_type": "vasp_candidate_neighborhood",
        "policy_version": "test",
        "anchor": {
            "address": "TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir",
            "entity_name": "OKX",
            "assertion_type": "service_control",
            "review_state": "accepted",
            "valid_from": "2026-08-10T15:59:54+00:00",
            "valid_to": "2026-08-10T15:59:54+00:00",
        },
        "coverage": {"complete": True},
        "candidates": [
            {
                "address": "<script>alert(1)</script>",
                "relationship_type": "deposit_candidate",
                "review_status": "unreviewed",
                "human_reviewed": False,
                "not_service_control_reason": "not ownership",
                "features": {},
                "evidence_references": [],
            }
        ],
        "address_only_context": [],
        "limitations": [],
    }
    (run_dir / "report.json").write_text(json.dumps(report))
    (run_dir / "manifest.json").write_text(json.dumps({"data_mode": "RECORDED_PUBLIC"}))

    response = client.get(f"/neighborhood/vasp/{run_id}")

    assert response.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text


def test_multihop_preset_renders_recorded_mode_and_public_path_caveat(
    client: TestClient,
) -> None:
    response = client.get("/console?preset=recorded-tron-multihop")

    assert response.status_code == 200
    assert "RECORDED PUBLIC" in response.text
    assert "Public multi-hop TRON/TRC-20 validation route" in response.text
    assert (
        "does not assert criminality, common ownership, or unique fund ownership"
        in response.text
    )
    assert "allocation_unknown" in response.text
    assert "unresolved" in response.text


def test_discover_presets_finds_a_saved_live_bundle_without_live_badge() -> None:
    discovered = discover_presets()
    for preset in discovered:
        assert preset.data_mode == "RECORDED_PUBLIC"
        assert preset.trace not in {p.trace for p in PRESETS}


@requires_recorded
def test_trace_export_route_returns_saved_result(client: TestClient) -> None:
    response = client.get("/console/trace/recorded-okx-direct")
    assert response.status_code == 200
    payload = response.json()
    assert payload["seed"]["address"] == "TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq"
    assert payload["scope"]["data_mode"] == "RECORDED_PUBLIC"


def test_readiness_card_lists_sourced_wallets(client: TestClient) -> None:
    readiness = REPO_ROOT / "var" / "evaluation-readiness" / "readiness.json"
    if not readiness.is_file():
        pytest.skip("no saved readiness report present")
    response = client.get("/console")
    assert response.status_code == 200
    assert "Sourced evaluation wallets" in response.text
    assert "materializable" in response.text


@requires_recorded
def test_evidence_report_link_resolves(client: TestClient) -> None:
    response = client.get("/console/evidence/recorded-okx-direct")
    assert response.status_code == 200
    assert "Trace evidence" in response.text


@requires_recorded
def test_comparison_and_outcome_routes_resolve(client: TestClient) -> None:
    comparison = client.get("/console/comparison/recorded-okx-direct")
    assert comparison.status_code == 200
    assert "evidence-comparison" in comparison.text
    outcome = client.get("/console/outcome/recorded-okx-direct")
    assert outcome.status_code == 200
    assert "service outcome" in outcome.text


def test_unknown_preset_returns_404(client: TestClient) -> None:
    response = client.get("/console?preset=does-not-exist")
    assert response.status_code == 200  # page still renders, with a warning
    assert "Unknown preset" in response.text
    assert client.get("/console/evidence/does-not-exist").status_code == 404


# --------------------------------------------------------------------------
# Landing page, dashboard, and the missing-artifact warning fix
# --------------------------------------------------------------------------


def test_landing_page_lists_features_and_refusals(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    text = response.text
    assert "Key features" in text
    assert "What it will not do" in text
    assert "Chronological tracing" in text
    assert 'href="/console"' in text
    assert 'href="/dashboard"' in text
    # The generic walkthrough has five steps and no case result.
    assert text.count("class='walk-step") == 5


def test_dashboard_lists_saved_neighborhood_report_separately(client: TestClient) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "/neighborhood/vasp/20260926T143630Z-aab422" in response.text
    assert "Candidate observations only; not wallet ownership clusters" in response.text


def test_dashboard_loads_with_runs_and_limitations(client: TestClient) -> None:
    response = client.get("/dashboard")
    assert response.status_code == 200
    text = response.text
    assert "Saved runs" in text
    assert "Standing limitations" in text
    assert "Outcomes on file" in text
    # Aggregates the env-independent parts even if var/ artifacts are missing.
    assert "Data modes" in text


def test_pages_carry_shared_nav_and_landmarks(client: TestClient) -> None:
    for path, active in (("/", "/"), ("/dashboard", "/dashboard"), ("/console", "/console")):
        response = client.get(path)
        assert response.status_code == 200
        assert "class='sitenav'" in response.text
        assert "aria-current='page'" in response.text
        assert 'href="#result"' in response.text
        assert active in response.text


@requires_synthetic
def test_trace_only_preset_has_no_missing_artifact_warnings() -> None:
    view = load_preset("synthetic-multihop")
    assert view.trace is not None
    assert not any("Stage 3A" in w for w in view.warnings)
    assert not any("Stage 2" in w for w in view.warnings)


def test_trace_only_view_shows_neutral_note_not_a_warning() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]))
    html = _render(view)
    assert "That is expected for a trace-only or synthetic fixture" in html
    assert "No Stage 3A service-outcome record is saved" not in html
    assert "No Stage 2 comparison report is saved" not in html


def test_missing_configured_artifact_is_still_warned(tmp_path: Any) -> None:
    # A preset that *declares* an outcome file which does not exist must warn.
    preset = _preset(outcome="var/definitely-not-here/outcome.json")
    view = load_preset(preset)
    assert any("Configured Stage 3A outcome is missing" in w for w in view.warnings)


# --------------------------------------------------------------------------
# Operational status: capability matrix and bundle integrity
# --------------------------------------------------------------------------


def test_capabilities_are_honest_about_what_is_not_built() -> None:
    caps = build_capabilities(
        readiness={"status": "NOT_READY_FOR_REAL_EVALUATION"},
        saved_run_count=3,
        live_key_configured=False,
        configured_data_mode="SYNTHETIC",
    )
    by_key = {c["key"]: c for c in caps}
    assert by_key["chronological_tracing"]["status"] == "available"
    assert by_key["chronological_tracing"]["implementation_status"] == "implemented"
    assert by_key["label_registry"]["implementation_status"] == "implemented"
    assert by_key["service_outcome"]["status"] == "available"
    assert by_key["multi_chain"]["status"] == "partial"
    assert by_key["evm_token_tracing"]["implementation_status"] == "implemented"
    assert by_key["evm_token_tracing"]["live_verified"] is False
    assert by_key["bridge_tracing"]["status"] == "partial"
    assert by_key["bridge_tracing"]["implementation_status"] == "partial"
    assert by_key["wallet_clustering"]["status"] == "partial"
    assert "not ownership clusters" in by_key["wallet_clustering"]["detail"]
    assert "one unreviewed, single-event deposit lead" in by_key["wallet_clustering"]["detail"]
    assert by_key["ml_anomaly_ranking"]["trained_real_model"] is False
    # The ranker is implemented but demonstrated only on synthetic rows, so it
    # is partial -- never "available".
    assert by_key["ml_anomaly_ranking"]["status"] == "partial"
    assert "Isolation Forest" in by_key["ml_anomaly_ranking"]["detail"]
    assert by_key["held_out_evaluation"]["status"] == "partial"
    # Monitoring exists (D029) but no live poll has been verified: partial, and
    # its detail must never read as a mempool feed or as live.
    assert by_key["monitoring"]["status"] == "partial"
    assert "not a mempool feed" in by_key["monitoring"]["detail"]
    assert "local evidence outbox" in by_key["monitoring"]["detail"]
    assert "Live polling is not configured" in by_key["monitoring"]["detail"]
    assert by_key["government_connectors"]["status"] == "not_configured"
    assert by_key["live_acquisition"]["status"] == "not_configured"
    blob = " ".join(c["detail"].lower() for c in caps)
    assert "accuracy" not in blob and "auc" not in blob


def test_capability_live_status_tracks_key_and_mode() -> None:
    def row(
        key: str, key_configured: bool, mode: str, historical_live_run_recorded: bool = False
    ) -> dict[str, Any]:
        caps = build_capabilities(
            readiness=None,
            saved_run_count=0,
            live_key_configured=key_configured,
            configured_data_mode=mode,
            historical_live_run_recorded=historical_live_run_recorded,
        )
        return {c["key"]: c for c in caps}[key]

    live_configured = row("live_acquisition", True, "LIVE", historical_live_run_recorded=True)
    assert live_configured["status"] == "configured"
    assert live_configured["configuration_status"] == "configured"
    assert live_configured["live_verified"] is False
    assert live_configured["historical_live_run_recorded"] is True
    assert row("live_acquisition", True, "RECORDED_PUBLIC")["status"] == "partial"
    assert row("live_acquisition", False, "LIVE")["status"] == "not_configured"
    assert row("live_acquisition", False, "SYNTHETIC")["status"] == "not_configured"


def test_verify_manifest_hashes_reports_ok_mismatch_and_missing(tmp_path: Any) -> None:
    import hashlib

    (tmp_path / "a.json").write_text("hello")
    good = hashlib.sha256(b"hello").hexdigest()
    manifest = {"files": {"a.json": good, "b.json": "deadbeef"}, "caveat": "x"}
    result = verify_manifest_hashes(manifest, tmp_path)
    by_file = {row["file"]: row["status"] for row in result["files"]}
    assert by_file == {"a.json": "ok", "b.json": "missing"}
    assert result["ok"] == 1 and result["missing"] == 1 and result["failed"] == 0

    (tmp_path / "a.json").write_text("tampered")
    tampered = verify_manifest_hashes(manifest, tmp_path)
    assert tampered["failed"] == 1
    assert {row["file"]: row["status"] for row in tampered["files"]}["a.json"] == "mismatch"


def test_verify_manifest_hashes_without_manifest() -> None:
    result = verify_manifest_hashes(None, None)
    assert result["available"] is False
    assert result["checked"] == 0


def test_dashboard_shows_capabilities_and_integrity(client: TestClient) -> None:
    response = client.get("/dashboard")
    assert response.status_code == 200
    text = response.text
    assert "Capabilities and status" in text
    assert "Saved-bundle integrity" in text
    assert "No anomaly model has been trained" in text
    assert "not built" in text


def test_capabilities_reflect_a_saved_synthetic_evaluation() -> None:
    caps = build_capabilities(
        readiness=None,
        saved_run_count=0,
        live_key_configured=False,
        configured_data_mode="SYNTHETIC",
        anomaly_evaluation={"evaluation_kind": "pipeline_demonstration"},
    )
    by_key = {c["key"]: c for c in caps}
    assert by_key["ml_anomaly_ranking"]["status"] == "partial"
    assert "pipeline demonstration" in by_key["ml_anomaly_ranking"]["detail"]
    assert by_key["held_out_evaluation"]["status"] == "partial"
    assert "pipeline demonstration" in by_key["held_out_evaluation"]["detail"]


def _anomaly_report() -> dict[str, Any]:
    return {
        "evaluation_kind": "pipeline_demonstration",
        "evaluation": {
            "rubric_id": "synthetic-demonstration-v1",
            "split_description": "split_by_wallet(eval_fraction=0.25, seed=7)",
            "labeled_row_count": 5,
            "unlabeled_excluded": 0,
            "outside_rubric_excluded": 0,
            "metrics": {
                "at_k": 5,
                "review_worthy_precision_at_k": None,
                "random_ranking_baseline_precision_at_k": 0.2,
                "confounders_in_top_k": 2,
                "labeled_in_top_k": 5,
            },
            "confounder_ranks": [{"wallet_id": "synth-020", "rank": 1}],
            "top_k": [
                {
                    "rank": 1,
                    "wallet_id": "synth-020",
                    "score": -0.72,
                    "data_mode": "SYNTHETIC",
                    "imputed_features": [],
                }
            ],
            "notes": ["Review-prioritization only."],
        },
    }


def _flat(html: str) -> str:
    return " ".join(html.split())


def test_anomaly_card_renders_the_saved_evaluation_separately() -> None:
    html = _anomaly_evaluation_card(_anomaly_report())
    flat = _flat(html)
    assert "ML review-prioritization (experimental)" in html
    assert "SYNTHETIC DEMONSTRATION" in html
    assert "synthetic-demonstration-v1" in html
    assert "synth-020" in html
    # A null precision is shown as not computable, never as a fabricated 0.
    assert "not computable" in html
    assert "not an accuracy claim" in flat
    assert "accuracy</td>" not in html.lower()


def test_anomaly_card_empty_state_is_honest() -> None:
    html = _anomaly_evaluation_card(None)
    flat = _flat(html)
    assert "Not available for this preset" in flat
    assert "not an evaluation result" in flat
    assert "SYNTHETIC demonstration" in flat
    assert "no model has been trained on real data" in flat.lower()


def test_dashboard_renders_the_anomaly_card() -> None:
    html = render_dashboard_html(presets_summary=[], anomaly_evaluation=_anomaly_report())
    assert "ML review-prioritization (experimental)" in html
    assert "synthetic-demonstration-v1" in html


def test_console_sidebar_renders_the_anomaly_card() -> None:
    html = render_console_html(
        view=DemoView(preset=_preset(), trace=_trace()),
        presets=(_preset(),),
        anomaly_evaluation=_anomaly_report(),
    )
    assert "ML review-prioritization (experimental)" in html


def test_dashboard_route_exposes_the_anomaly_card(client: TestClient) -> None:
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "ML review-prioritization (experimental)" in response.text


@requires_recorded
def test_dashboard_integrity_verifies_the_recorded_bundle(client: TestClient) -> None:
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "all match" in response.text


def test_pages_offer_a_theme_toggle_and_declare_theme_support() -> None:
    html = render_console_html(
        view=DemoView(preset=_preset(), trace=_trace()),
        presets=(_preset(),),
    )
    assert 'class="theme-toggle"' in html
    assert "cfa-theme" in html
    assert "data-theme" in html
    assert "Theme: Auto" in html


def test_discovered_bundle_is_presented_as_recorded_public() -> None:
    discovered = discover_presets()
    if not discovered:
        pytest.skip("no discovered bundles on this checkout")
    view = load_preset(discovered[0])
    # A saved bundle is presented as RECORDED_PUBLIC even if captured LIVE.
    assert view.data_mode == "RECORDED_PUBLIC"
    assert view.capture_data_mode in ("LIVE", "RECORDED_PUBLIC", "SYNTHETIC", None)


# --------------------------------------------------------------------------
# Redesigned demo page: five sections, synchronization, progressive disclosure
# --------------------------------------------------------------------------


def _transfer(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "hop_depth": 1,
        "block_time": "2026-08-10T15:59:54+00:00",
        "from_address": "TSeedAddress000000000000000000000",
        "to_address": "TEndingAddress0000000000000000000",
        "amount_base_units": "72140000",
        "amount_display": "72.140000",
        "asset": {"display_symbol": "USDT"},
        "event_reference": "tron:abcdef:0",
        "tx_hash": "abcdef",
        "execution_status": "success",
        "confirmation_state": "confirmed",
        "ordering_ambiguous": False,
    }
    base.update(overrides)
    return base


def _sync_view() -> DemoView:
    ending = _ending(
        branch_path=["tron:abcdef:0"], arrival_event_reference="tron:abcdef:0"
    )
    return DemoView(preset=_preset(), trace=_trace(transfers=[_transfer()], endings=[ending]))


def test_demo_page_exposes_exactly_five_primary_sections() -> None:
    html = _render(DemoView(preset=_preset(), trace=_trace(endings=[_ending()])))
    for anchor in (
        'id="result"',
        'id="path"',
        'id="timeline"',
        'id="evidence"',
        'id="actions"',
    ):
        assert anchor in html
    order = [
        html.index('id="path"'),
        html.index('id="timeline"'),
        html.index('id="evidence"'),
        html.index('id="actions"'),
    ]
    assert order == sorted(order)


def test_supported_result_card_renders_compact_facts() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    html = _render(view)
    assert 'class="card result-card supported"' in html
    assert "Supported destination: Example Exchange" in html
    assert "Observed amount" in html
    assert "72.140000" in html
    assert "Execution / finality" in html
    assert "One important limitation" in html


def test_unresolved_result_card_renders_without_naming_a_service() -> None:
    view = DemoView(
        preset=_preset(),
        trace=_trace(endings=[_ending(endpoint_class="unresolved")]),
        outcome=_outcome(
            category="unknown_or_blocked",
            service_name=None,
            reason_codes=["no_accepted_label"],
        ),
    )
    html = _render(view)
    assert 'class="card result-card unknown_or_blocked"' in html
    assert "Unknown / blocked" in html
    assert "No accepted label reaches this claim" in html
    assert "Supported destination: Example Exchange" not in html


def test_candidate_lead_never_renders_as_a_supported_result() -> None:
    view = DemoView(
        preset=_preset(),
        trace=_trace(endings=[_ending(endpoint_class="deposit_candidate")]),
        outcome=_outcome(
            category="candidate_lead",
            service_name="Example Exchange",
            verification_quality="history_only",
            reason_codes=["insufficient_verification"],
        ),
    )
    html = _render(view)
    assert 'class="card result-card candidate_lead"' in html
    assert "Candidate lead: Example Exchange (not an accepted destination)" in html
    assert "Supported destination: Example Exchange" not in html


def test_graph_and_timeline_share_row_keys_and_sync_controls() -> None:
    html = _render(_sync_view())
    assert "js-path-node" in html
    assert "js-timeline-row' data-row='1'" in html
    # The path node and its timeline row share the same row key.
    assert html.count("data-row='1'") >= 2
    assert "js-focus-row" in html
    assert "js-replay-play" in html
    assert "js-replay-next" in html
    assert "js-replay-prev" in html
    assert "js-replay-reset" in html


def test_provenance_stays_accessible_in_the_evidence_panel() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    html = _render(view)
    assert 'id="panel-evidence"' in html
    assert 'id="tab-evidence"' in html
    assert "What the source supports" in html
    assert "Example Exchange" in html
    # A hash and source reference are still rendered from the saved label.
    assert "deadbeef" in html
    assert "https://example.test/disclosure" in html


def test_all_status_axes_stay_accessible_in_uncertainty_panel() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    html = _render(view)
    assert 'id="panel-uncertainty"' in html
    assert 'id="tab-uncertainty"' in html
    for axis in ("case_flow_linkage", "ordering_quality", "verification_quality"):
        assert axis in html
    assert "never collapsed into one confidence score" in html


def test_tabs_are_keyboard_navigable() -> None:
    html = _render(DemoView(preset=_preset(), trace=_trace(endings=[_ending()])))
    assert 'role="tablist"' in html
    assert html.count('role="tab"') == 3
    assert 'role="tabpanel"' in html
    assert 'aria-controls="panel-evidence"' in html
    assert "ArrowRight" in html  # roving tab focus is handled in the script
    assert 'href="#result"' in html  # skip link preserved
    assert "row-locator" in html  # keyboard reachable graph locator per row


def test_report_and_export_links_remain() -> None:
    view = DemoView(
        preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome()
    )
    html = _render(view)
    assert "/console/evidence/test-preset" in html
    assert "/console/outcome/test-preset" in html
    assert "/console/trace/test-preset" in html
    assert "Download JSON" in html
    assert "Print / Save PDF" in html


def test_no_confidence_percentage_or_risk_score_in_the_result_flow() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    html = _render(view)
    main = html.split('<main id="result"', 1)[1].split("</main>", 1)[0]
    assert "%" not in main
    low = main.lower()
    assert "risk score" not in low
    assert "confidence score:" not in low
    assert "probability" not in low


def test_experimental_ml_stays_labelled_and_separated() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]))
    html = render_console_html(
        view=view, presets=(view.preset,), anomaly_evaluation=_anomaly_report()
    )
    assert "Experimental ML &amp; evaluation readiness" in html
    for flag in (
        "EXPERIMENTAL",
        "SYNTHETIC DEMONSTRATION",
        "NOT ATTRIBUTION",
        "NOT FRAUD PROBABILITY",
    ):
        assert flag in html
    assert "ML review-prioritization (experimental)" in html
    # The ML card sits inside the collapsed, separately labelled drawer.
    assert html.index("Experimental ML &amp; evaluation readiness") < html.index(
        "ML review-prioritization"
    )


def test_print_rules_reveal_all_evidence_panels() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    html = _render(view)
    assert "@media print" in html
    assert ".tabpanel[hidden] { display: block" in html
    assert "Unknown ownership" in html
    assert "allocation_unknown" in html


def test_mobile_css_keeps_the_path_and_core_actions() -> None:
    html = _render(DemoView(preset=_preset(), trace=_trace(endings=[_ending()])))
    assert "@media (max-width: 700px)" in html
    assert "flex-direction: column" in html
    assert "Download JSON" in html
    assert "Evidence report" in html
    assert "Print / Save PDF" in html


def test_reduced_motion_disables_the_replay_animation() -> None:
    html = _render(DemoView(preset=_preset(), trace=_trace(endings=[_ending()])))
    assert "prefers-reduced-motion: reduce" in html
    assert "function reducedMotion()" in html
    # Under reduced motion the replay jumps to the final state, never animates.
    assert "if (reducedMotion()) { pi = pathNodes.length - 1; finish(); return; }" in html


def test_dashboard_is_four_sections() -> None:
    dashboard = render_dashboard_html(
        presets_summary=[],
        capabilities=[{"key": "x", "label": "X", "status": "available", "detail": "d"}],
    )
    assert "Saved evidence" in dashboard
    assert "Evaluation readiness" in dashboard
    assert "Capabilities and status" in dashboard
    assert "Saved-bundle integrity" in dashboard
    assert "Standing limitations" in dashboard
    assert "No anomaly model has been trained" in dashboard


# --------------------------------------------------------------------------
# Speed/clarity polish: concise copy, copy actions, grouping, states, pacing
# --------------------------------------------------------------------------


def _result_section(html: str) -> str:
    start = html.index("card result-card")
    end = html.index("</section>", start)
    return html[start:end]


def test_supported_result_copy_is_concise_and_not_repetitive() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    section = _result_section(_render(view))
    assert "Supported destination: Example Exchange" in section
    assert "inside the label" in section
    assert "dated window" in section
    assert "The observed path reached" not in section
    # Caveats live in the Limitations tab, not repeated in the result card.
    assert view.preset.scope_note not in section


def test_unresolved_result_is_equally_prominent() -> None:
    view = DemoView(
        preset=_preset(),
        trace=_trace(endings=[_ending(endpoint_class="unresolved")]),
        outcome=_outcome(category="unknown_or_blocked", service_name=None),
    )
    html = _render(view)
    assert 'class="card result-card unknown_or_blocked"' in html
    assert 'class="result-headline"' in _result_section(html)
    assert "Unknown / blocked" in _result_section(html)


def test_candidate_never_carries_the_supported_style() -> None:
    view = DemoView(
        preset=_preset(),
        trace=_trace(endings=[_ending(endpoint_class="deposit_candidate")]),
        outcome=_outcome(category="candidate_lead", service_name="Example Exchange"),
    )
    html = _render(view)
    assert "result-card candidate_lead" in html
    assert "result-card supported" not in html
    assert "Candidate lead: Example Exchange (not an accepted destination)" in html


def test_copy_buttons_expose_the_full_raw_value() -> None:
    full = "T" + "a" * 33
    html = _copyable(full, keep=16, label="address")
    assert f"data-copy='{full}'" in html
    assert "Copy full address" in html
    assert "\u2026" in html  # the visible label stays shortened
    assert full in html  # a print-only span keeps the full value readable
    assert "print-full" in html


def test_copy_feedback_is_announced_accessibly() -> None:
    html = _render(DemoView(preset=_preset(), trace=_trace(endings=[_ending()])))
    assert 'id="copy-status"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "Copy full" in html
    assert 'classList.add("copied")' in html
    assert "Copied " in html


def test_uncertainty_axes_are_grouped_but_still_independent() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    html = _render(view)
    for group in ("Observation quality", "Attribution", "Case linkage", "Coverage"):
        assert group in html
    for axis in (
        "execution_status",
        "coverage_status",
        "attribution_status",
        "case_flow_linkage",
        "acquisition_completeness",
        "verification_quality",
        "event_identity_quality",
        "ordering_quality",
    ):
        assert axis in html
    assert "never collapsed into one confidence score" in html


def test_no_saved_result_state_explains_what_it_is_not() -> None:
    view = DemoView(
        preset=_preset(trace="var/nope.json"),
        trace=None,
        error="No saved trace result was found for this preset.",
    )
    html = _render(view)
    assert "No saved result" in html
    assert "What this does not mean" in html
    assert "not a statement that the address had no activity" in html
    assert "Next step" in html


def test_missing_optional_artifacts_use_neutral_copy() -> None:
    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]))
    html = _render(view)
    assert "Not recorded for this preset" in html
    assert "no separate behavioral acquisition is saved" in html


def test_graph_timeline_selection_state_is_shared_and_keyboard_clearable() -> None:
    html = _render(_sync_view())
    assert "function setSelected(" in html
    assert 'classList.add("sel")' in html
    assert 'setAttribute("aria-current", "true")' in html
    assert 'row.classList.add("selected")' in html
    assert "tbody tr.selected td:first-child" in html  # CSS matches the accent
    assert 'e.key === "Escape"' in html


def test_print_reveals_all_evidence_and_neutralises_selection() -> None:
    view = DemoView(
        preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome()
    )
    html = _render(view)
    assert ".tabpanel[hidden] { display: block !important; }" in html
    assert ".print-full { display: inline; }" in html
    assert "box-shadow: none !important" in html
    assert "tbody tr.selected { background: transparent !important; }" in html


def test_replay_has_clean_finish_and_endpoint_pauses() -> None:
    html = _render(_sync_view())
    assert "function finish()" in html
    assert "clearSelection();" in html
    assert "isTerminal(pathNodes[target]) ? 1100 : 520" in html
    assert "Replay complete - " in html


def test_narrow_screen_grid_can_shrink_and_puts_result_first() -> None:
    html = _render(_sync_view())
    # Grid items must be allowed to shrink, or a wide table/token blows the
    # page open at tablet and phone widths.
    assert ".grid > * { min-width: 0; }" in html
    assert "grid-template-columns: minmax(0, 1fr)" in html
    # On one column, the result precedes the sidebar.
    assert ".grid > aside { order: 2; }" in html
    assert ".grid > main { order: 1; }" in html


def test_print_hides_screen_only_status_and_controls() -> None:
    html = _render(_sync_view())
    assert (
        ".replay-caption, .theme-toggle, #health { display: none !important; }" in html
    )


def test_path_truncates_a_very_long_amount_but_keeps_the_full_value() -> None:
    huge = "115792089237316195" "423570985008687907853269984665640564039457584007913129.639935"
    transfer = _transfer(
        amount_base_units=huge, amount_display=huge, event_reference="tron:huge:0"
    )
    ending = _ending(branch_path=["tron:huge:0"], arrival_event_reference="tron:huge:0")
    view = DemoView(preset=_preset(), trace=_trace(transfers=[transfer], endings=[ending]))
    html = _render(view)
    assert f"title='{huge} USDT'" in html  # full value stays in the title
    assert "\u2026" in html  # the visible edge amount is shortened


def test_no_outcome_headline_pluralises_branch_and_endpoint() -> None:
    one = _render(DemoView(preset=_preset(), trace=_trace(endings=[_ending()])))
    assert "1 branch reached a labelled service boundary" in one
    assert "branch(es)" not in one
    two = _render(
        DemoView(preset=_preset(), trace=_trace(endings=[_ending(), _ending()]))
    )
    assert "2 branches reached a labelled service boundary" in two


def test_no_risk_or_probability_language_anywhere_visible() -> None:
    import re

    view = DemoView(preset=_preset(), trace=_trace(endings=[_ending()]), outcome=_outcome())
    html = _render(view)
    body = html.split("<body>", 1)[1]
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    low = body.lower()
    assert "risk score" not in low
    assert "risk level" not in low
    assert "confidence level" not in low
    assert "probability of" not in low
    assert not re.search(r"\d+(\.\d+)?\s*%", body)
