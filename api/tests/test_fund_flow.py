"""Fund-flow graph: model, rendering, and the /graph page.

Model and rendering tests build traces in memory. Route tests use the saved demo
artifacts and skip, like ``test_console.py``, when a checkout has none.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.reports.console import render_fund_flow_html
from app.reports.fund_flow import build_fund_flow, graph_json_script, render_fund_flow_svg
from app.services.demo_presets import DemoView, Preset

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_TRACE = REPO_ROOT / "var" / "trace.json"
RECORDED_TRACE = REPO_ROOT / "var" / "live-validation" / "20260920T090201Z-969305" / "trace.json"
requires_synthetic = pytest.mark.skipif(
    not SYNTHETIC_TRACE.is_file(), reason="saved synthetic demo artifacts are not present"
)
requires_recorded = pytest.mark.skipif(
    not RECORDED_TRACE.is_file(), reason="saved recorded demo artifacts are not present"
)

SEED = "TSeedAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
HOP1 = "THop1BBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
FAN_A = "TFanACCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
FAN_B = "TFanBDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"
JOIN = "TJoinEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"
CAND = "TCandFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"
SVC = "TSvcGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG"
UINT256_MAX = str(2**256 - 1)


def transfer(ref: str, frm: str, to: str, amount: str = "1.000000", **extra: Any) -> dict:
    row = {
        "event_reference": ref,
        "tx_hash": ref.split(":")[1],
        "from_address": frm,
        "to_address": to,
        "amount_base_units": str(int(amount.replace(".", ""))) if "." in amount else amount,
        "amount_display": amount,
        "asset": {"token_contract": "TContract", "decimals": 6, "display_symbol": "USDT-SYN"},
        "block_time": "2026-08-01T10:00:00+00:00",
        "ordering_ambiguous": False,
        "execution_status": "success",
        "confirmation_state": "confirmed",
        "hop_depth": 1,
    }
    row.update(extra)
    return row


def ending(address: str, cls: str, path: list[str], **extra: Any) -> dict:
    row = {
        "address": address,
        "endpoint_class": cls,
        "attribution_status": {"known_service": "supported", "deposit_candidate": "candidate"}.get(
            cls, "unresolved"
        ),
        "boundary_reason": "service_boundary" if cls == "known_service" else None,
        "hop_depth": len(path) - 1,
        "branch_path": path,
        "arrival_event_reference": path[-1] if path else None,
        "label": None,
        "note": None,
    }
    row.update(extra)
    return row


def multihop_trace() -> dict:
    """Seed -> hop1 -> fan A/B -> join (reconverge) -> candidate -> service."""
    seed = transfer("tron:tx_seed:0", SEED, HOP1, "100.000000", hop_depth=0)
    fan_a = transfer("tron:tx_fan:0", HOP1, FAN_A, "60.000000")
    fan_b = transfer("tron:tx_fan:1", HOP1, FAN_B, "40.000000")
    join_a = transfer("tron:tx_join_a:0", FAN_A, JOIN, "60.000000", hop_depth=2)
    join_b = transfer("tron:tx_join_b:0", FAN_B, JOIN, "40.000000", hop_depth=2)
    to_cand = transfer("tron:tx_cand:0", JOIN, CAND, "95.000000", hop_depth=3)
    to_svc = transfer("tron:tx_svc:0", CAND, SVC, "95.000000", hop_depth=4)
    return {
        "seed": {
            "address": SEED,
            "event_reference": "tron:tx_seed:0",
            "network_key": "tron",
            "asset": {"token_contract": "TContract", "display_symbol": "USDT-SYN", "decimals": 6},
        },
        "seed_transfer": seed,
        "observed_transfers": [fan_a, fan_b, join_a, join_b, to_cand, to_svc],
        "branch_endings": [
            ending(
                JOIN,
                "unresolved",
                ["tron:tx_seed:0", "tron:tx_fan:1", "tron:tx_join_b:0"],
                note="Branch reconverged onto an already-explored path.",
            ),
            ending(
                CAND,
                "deposit_candidate",
                ["tron:tx_seed:0", "tron:tx_fan:0", "tron:tx_join_a:0", "tron:tx_cand:0"],
            ),
            ending(
                SVC,
                "known_service",
                [
                    "tron:tx_seed:0",
                    "tron:tx_fan:0",
                    "tron:tx_join_a:0",
                    "tron:tx_cand:0",
                    "tron:tx_svc:0",
                ],
                label={"entity_name": "Northwind Exchange (FICTIONAL)"},
            ),
        ],
        "limitations": ["Synthetic test trace."],
    }


def _nodes(graph):
    return {n.address: n for n in graph.nodes}


# -- model ---------------------------------------------------------------------


def test_one_node_per_wallet_and_one_edge_per_transfer() -> None:
    graph = build_fund_flow(multihop_trace())
    nodes = _nodes(graph)

    assert len(graph.nodes) == 7
    assert len(graph.edges) == 7
    # The reconverging wallet is one node with both arrivals, not two copies.
    assert len(nodes[JOIN].incoming) == 2
    assert graph.warnings == []


def test_two_transfers_in_one_transaction_are_two_edges() -> None:
    trace = multihop_trace()
    trace["observed_transfers"].append(
        transfer(
            "tron:tx_fan:2", HOP1, FAN_A, "5.000000"
        )  # same tx as fan:0/fan:1, same pair as fan:0
    )

    graph = build_fund_flow(trace)

    same_tx = [e for e in graph.edges if e.tx_hash == "tx_fan"]
    assert len(same_tx) == 3
    assert len([e for e in graph.edges if (e.source, e.target) == (HOP1, FAN_A)]) == 2


def test_a_repeated_event_reference_is_drawn_once() -> None:
    trace = multihop_trace()
    trace["observed_transfers"].append(dict(trace["observed_transfers"][0]))

    assert len(build_fund_flow(trace).edges) == 7


def test_roles_follow_recorded_endings_and_a_candidate_is_never_supported() -> None:
    graph = build_fund_flow(multihop_trace())
    nodes = _nodes(graph)

    assert nodes[SEED].role == "seed"
    assert nodes[SVC].role == "known_service"
    assert nodes[SVC].entity_name == "Northwind Exchange (FICTIONAL)"
    assert nodes[CAND].role == "deposit_candidate"
    svg = render_fund_flow_svg(graph)
    candidate = re.search(r"<g class='ff-node role-deposit_candidate'.*?</g>", svg)
    assert candidate is not None
    assert "Candidate lead (not verified)" in candidate.group(0)
    assert "Supported service" not in candidate.group(0)


def test_a_reconvergence_ending_is_not_drawn_as_a_boundary() -> None:
    graph = build_fund_flow(multihop_trace())
    join = _nodes(graph)[JOIN]

    assert join.role == "wallet"
    assert join.reconverged_branches == [1]
    stats = graph.stats()
    assert stats["reconverged"] == 1
    assert stats["unresolved"] == 0


def test_a_terminal_unresolved_ending_stays_unresolved() -> None:
    trace = multihop_trace()
    trace["branch_endings"].append(
        ending(
            FAN_B,
            "unresolved",
            ["tron:tx_seed:0", "tron:tx_fan:1"],
            boundary_reason="no_outgoing_activity",
        )
    )

    node = _nodes(build_fund_flow(trace))[FAN_B]

    # FAN_B has an onward transfer, but a stated boundary reason is a boundary.
    assert node.role == "unresolved"
    assert node.boundary_reasons == ["no_outgoing_activity"]


def test_conflicting_endings_are_shown_as_a_conflict() -> None:
    trace = multihop_trace()
    trace["branch_endings"].append(ending(SVC, "deposit_candidate", ["tron:tx_seed:0"]))

    graph = build_fund_flow(trace)

    assert _nodes(graph)[SVC].role == "mixed"
    assert any("conflicting" in w for w in graph.warnings)


def test_amounts_stay_exact_strings_and_nothing_is_summed() -> None:
    trace = multihop_trace()
    trace["observed_transfers"].append(
        transfer("tron:tx_huge:0", SVC, SVC, UINT256_MAX, amount_display=UINT256_MAX)
    )

    graph = build_fund_flow(trace)
    payload = graph.to_json()

    huge = next(e for e in payload["edges"] if e["event_reference"] == "tron:tx_huge:0")
    assert huge["amount_base_units"] == UINT256_MAX
    assert isinstance(huge["amount_base_units"], str)
    assert not any("amount" in key or "total" in key for key in payload["stats"])
    html = render_fund_flow_html(view=_view(trace), presets=[_preset()])
    assert UINT256_MAX in html  # the table carries the exact value


def test_edges_point_forward_when_the_flow_is_acyclic() -> None:
    graph = build_fund_flow(multihop_trace())
    layer = {n.address: n.layer for n in graph.nodes}

    assert graph.acyclic is True
    assert all(layer[e.target] > layer[e.source] for e in graph.edges)
    assert layer[SEED] == 0 and layer[SVC] == 5


def test_a_cycle_terminates_and_is_reported() -> None:
    trace = multihop_trace()
    trace["observed_transfers"].append(transfer("tron:tx_back:0", SVC, HOP1, "1.000000"))

    graph = build_fund_flow(trace)

    assert graph.acyclic is False
    assert any("cycle" in w for w in graph.warnings)
    assert "tron:tx_back:0" in render_fund_flow_svg(graph)


def test_ambiguous_ordering_is_drawn_dashed() -> None:
    trace = multihop_trace()
    trace["observed_transfers"][0]["ordering_ambiguous"] = True

    svg = render_fund_flow_svg(build_fund_flow(trace))

    assert re.search(r"<g class='ff-edge ambiguous' data-edge='1'", svg)


def test_an_older_result_reconstructs_only_the_seed_transfer() -> None:
    trace = {
        "seed": {
            "address": SEED,
            "event_reference": "tron:tx_old:0",
            "network_key": "tron",
            "asset": {"display_symbol": "USDT"},
        },
        "seed_transfer": None,
        "observed_transfers": [],
        "branch_endings": [
            ending(
                SVC,
                "known_service",
                ["tron:tx_old:0"],
                observed_amount_display="72.140000",
                observed_amount_base_units="72140000",
                hop_depth=0,
            ),
            ending(CAND, "deposit_candidate", ["tron:tx_old:0", "tron:tx_unsaved:0"]),
        ],
    }

    graph = build_fund_flow(trace)

    [edge] = graph.edges
    assert (edge.source, edge.target, edge.amount_base_units) == (SEED, SVC, "72140000")
    assert edge.is_seed and edge.derived_from
    assert edge.block_time is None and edge.execution_status is None
    # A missing non-seed event has no known sender, so it is reported, not invented.
    assert any("not in the saved transfer list" in w for w in graph.warnings)
    assert "derived" in render_fund_flow_svg(graph)


def test_rendering_is_deterministic() -> None:
    first = render_fund_flow_svg(build_fund_flow(multihop_trace()))
    second = render_fund_flow_svg(build_fund_flow(multihop_trace()))

    assert first == second


def test_hostile_strings_are_escaped_in_svg_json_and_page() -> None:
    hostile = "</script><script>alert(1)</script><img src=x onerror=alert(2)>"
    trace = multihop_trace()
    trace["branch_endings"][2]["label"] = {"entity_name": hostile}
    trace["branch_endings"][2]["note"] = hostile
    trace["observed_transfers"][0]["event_reference"] = "tron:x:0" + hostile

    graph = build_fund_flow(trace)
    svg = render_fund_flow_svg(graph)
    blob = graph_json_script(graph)
    page = render_fund_flow_html(view=_view(trace), presets=[_preset()])

    for text in (svg, page):
        assert "<script>alert" not in text
        assert "<img src=x" not in text
    assert blob.count("</script>") == 1  # only its own closing tag
    assert "\\u003c/script\\u003e" in blob
    embedded = json.loads(blob[blob.index(">") + 1 : blob.rindex("</script>")])
    assert any(n["entity_name"] == hostile for n in embedded["nodes"])


# -- page ---------------------------------------------------------------------------


def _preset(**overrides: Any) -> Preset:
    base: dict[str, Any] = {
        "id": "test-preset",
        "title": "Test preset",
        "scenario": "test",
        "data_mode": "SYNTHETIC",
        "address": SEED,
        "description": "in-memory test trace",
        "trace": "var/none.json",
    }
    base.update(overrides)
    return Preset(**base)


def _view(trace: dict | None, **preset: Any) -> DemoView:
    return DemoView(preset=_preset(**preset), trace=trace)


def test_page_states_mode_and_what_is_not_drawn() -> None:
    page = render_fund_flow_html(view=_view(multihop_trace()), presets=[_preset()])

    assert "SYNTHETIC" in page
    assert "saved evidence, not a live trace" in page
    assert "Resource delegations, TRX funding, and inferred control relationships" in page
    assert "allocation_unknown" in page
    assert "<script src" not in page.lower()
    assert "aria-current='page'" in page


def test_recorded_preset_notes_its_capture_mode() -> None:
    trace = multihop_trace()
    trace["scope"] = {"data_mode": "LIVE"}

    page = render_fund_flow_html(
        view=_view(trace, data_mode="RECORDED_PUBLIC"), presets=[_preset()]
    )

    assert "Presented as RECORDED_PUBLIC (captured as LIVE)" in page


def test_no_transfers_and_no_trace_are_stated_not_drawn_empty() -> None:
    empty = multihop_trace()
    empty["seed_transfer"] = None
    empty["observed_transfers"] = []
    empty["branch_endings"] = []

    assert "No transfers recorded" in render_fund_flow_html(view=_view(empty), presets=[])
    none_page = render_fund_flow_html(view=None, presets=[])
    assert "No graph" in none_page
    assert "not a statement that the address had no activity" in none_page


@requires_synthetic
def test_graph_route_draws_the_saved_synthetic_preset(client: TestClient) -> None:
    response = client.get("/graph?preset=synthetic-multihop")

    assert response.status_code == 200
    assert "<svg class='ff-svg'" in response.text
    assert "id='ff-data'" in response.text
    assert "SYNTHETIC" in response.text


@requires_recorded
def test_graph_route_draws_the_recorded_okx_preset(client: TestClient) -> None:
    response = client.get("/graph?preset=recorded-okx-direct")

    assert response.status_code == 200
    assert "RECORDED PUBLIC" in response.text
    assert "72.140000" in response.text
    assert "reconstructed" in response.text


def test_graph_route_unknown_preset_is_404(client: TestClient) -> None:
    response = client.get("/graph?preset=does-not-exist")

    assert response.status_code == 404
    assert "Unknown preset" in response.text


@requires_synthetic
def test_graph_json_route(client: TestClient) -> None:
    response = client.get("/console/graph/synthetic-multihop")

    assert response.status_code == 200
    body = response.json()
    assert body["data_mode"] == "SYNTHETIC"
    assert body["drawn"] == "observed token transfers only"
    assert all(isinstance(e["amount_base_units"], str) for e in body["edges"])
    assert client.get("/console/graph/does-not-exist").status_code == 404


def test_nav_links_the_fund_flow_page(client: TestClient) -> None:
    response = client.get("/")

    assert "href='/graph'" in response.text
    assert ">Fund flow<" in response.text


@requires_synthetic
def test_console_path_card_links_to_the_graph(client: TestClient) -> None:
    response = client.get("/console?preset=synthetic-multihop")

    assert "/graph?preset=synthetic-multihop" in response.text


def test_graph_route_is_not_registered_in_prod(monkeypatch: Any) -> None:
    import app.main as main
    from app.core.settings import AppEnv, DataMode, Settings

    prod = Settings(app_env=AppEnv.prod, data_mode=DataMode.SYNTHETIC, secret_key="x" * 40)
    monkeypatch.setattr(main, "get_settings", lambda: prod)
    paths = main.create_app().openapi()["paths"]
    assert "/graph" not in paths
    assert "/console/graph/{preset_id}" not in paths
