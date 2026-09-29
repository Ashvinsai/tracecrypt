"""The live-validation harness, exercised offline.

No test here reaches TronGrid. The provider is mocked at the HTTP layer with
the documented response shapes, which is enough to prove the harness writes the
bundle, refuses what it should refuse, and replays a recording through the same
parser and tracer. Whether the real chain agrees is C06, below, and that one
needs a key.
"""

from __future__ import annotations

import contextlib
import csv
import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.core.settings import AppEnv, DataMode, LabelSource, Settings
from app.services.anchor_import import DisclosureKind, SourceDocument, import_anchors
from app.services.candidate_review import ReviewAction, ReviewRequest, review_candidates
from app.services.live_validation import (
    LiveValidationError,
    ValidationRequest,
    exchange_key,
    run_validation,
)

BASE = "https://api.trongrid.io"
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
VICTIM = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
SERVICE = "TBvGC1Nd8i5wmj185HTdoTWAZPmRUTFBZz"
TX = "5f2a1b"
CUTOFF = dt.datetime(2026, 9, 20, tzinfo=dt.UTC)
SOURCE_URL = "https://example-exchange.test/proof-of-reserves"
API_KEY = "test-key-not-a-real-one"

HISTORY = "/v1/accounts/{address}/transactions/trc20"
EVENTS = f"/v1/transactions/{TX}/events"
SOLID_RECEIPT = "/walletsolidity/gettransactioninfobyid"


def history_row(tx: str, frm: str, to: str, value: str) -> dict:
    return {
        "transaction_id": tx,
        "block_timestamp": 1789862400000,
        "from": frm,
        "to": to,
        "type": "Transfer",
        "value": value,
        "token_info": {"symbol": "USDT", "address": USDT, "decimals": 6, "name": "Tether USD"},
    }


def mock_provider() -> None:
    """One transfer from the seed address to the anchor, then nothing onward."""
    respx.get(f"{BASE}{HISTORY.format(address=VICTIM)}").mock(
        return_value=httpx.Response(
            200,
            json={"data": [history_row(TX, VICTIM, SERVICE, "95000000")], "meta": {}},
        )
    )
    respx.get(f"{BASE}{HISTORY.format(address=SERVICE)}").mock(
        return_value=httpx.Response(200, json={"data": [], "meta": {}})
    )
    respx.get(f"{BASE}{EVENTS}").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "block_number": 71000010,
                        "block_timestamp": 1789862400000,
                        "contract_address": USDT,
                        "event_index": 0,
                        "event_name": "Transfer",
                        "transaction_id": TX,
                        "result": {"from": VICTIM, "to": SERVICE, "value": "95000000"},
                    }
                ]
            },
        )
    )
    respx.post(f"{BASE}{SOLID_RECEIPT}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": TX,
                "fee": 1_100_000,
                "blockNumber": 71_000_010,
                "blockTimeStamp": 1789862400000,
                "contractResult": [""],
                "receipt": {"net_fee": 0, "result": "SUCCESS"},
            },
        )
    )


def accepted_label_dir(tmp_path: Path) -> Path:
    """A reviewed set holding one accepted claim for the destination address."""
    data_dir = tmp_path / "data"
    source = tmp_path / "disclosure.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{SERVICE},Example Exchange,exchange,service_control,cold_reserve\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url=SOURCE_URL,
            disclosure_kind=DisclosureKind.signed_address_verification,
            disclosure_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            retrieved_at=dt.datetime(2026, 9, 19, tzinfo=dt.UTC),
            methodology="Signed verification page, TRON entry.",
            label_set_version="live-validation-test",
        ),
        network_key="tron",
        out_dir=data_dir,
        write=True,
    )
    report = review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key="tron",
                address=SERVICE,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="Opened the signed verification; the address is listed.",
                evidence_inspected=(SOURCE_URL,),
            )
        ],
        write=True,
    )
    assert not report.refusals
    return data_dir


def live_settings(tmp_path: Path, **overrides) -> Settings:
    kwargs = {
        "app_env": AppEnv.test,
        "data_mode": DataMode.LIVE,
        "secret_key": "test-secret-key-that-is-long-enough-for-the-validator",
        "tron_api_key": API_KEY,
        "tron_api_base": BASE,
    }
    kwargs.update(overrides)
    # Building the label set twice re-reviews it and moves the decision
    # timestamps, so a caller comparing two runs passes the directory through.
    # (setdefault would not do: its default is evaluated either way.)
    if "label_dir" not in kwargs:
        kwargs["label_dir"] = str(accepted_label_dir(tmp_path))
    return Settings(**kwargs)


def request_for() -> ValidationRequest:
    return ValidationRequest(
        address=VICTIM,
        token_contract=USDT,
        seed_event_reference=f"tron:{TX}:0",
        analysis_cutoff=CUTOFF,
        run_id="test-run",
    )


# --- refusals ---------------------------------------------------------------


async def test_a_live_run_without_a_key_fails_it_does_not_skip(tmp_path: Path) -> None:
    settings = live_settings(tmp_path, tron_api_key=None)

    with pytest.raises(LiveValidationError, match="CFA_TRON_API_KEY"):
        await run_validation(settings, request_for(), out_root=tmp_path / "out")


async def test_a_live_run_in_synthetic_mode_is_refused(tmp_path: Path) -> None:
    settings = live_settings(
        tmp_path, data_mode=DataMode.SYNTHETIC, label_source=LabelSource.reviewed_sets
    )

    with pytest.raises(LiveValidationError, match="CFA_DATA_MODE=LIVE"):
        await run_validation(settings, request_for(), out_root=tmp_path / "out")


async def test_live_mode_with_no_accepted_anchor_fails_rather_than_attributing_nothing_quietly(
    tmp_path: Path,
) -> None:
    settings = live_settings(tmp_path, label_dir=str(tmp_path / "empty"))

    with pytest.raises(LiveValidationError, match="no accepted service claim"):
        await run_validation(settings, request_for(), out_root=tmp_path / "out")


@respx.mock
async def test_a_provider_failure_fails_the_validation(tmp_path: Path) -> None:
    respx.get(f"{BASE}{HISTORY.format(address=VICTIM)}").mock(return_value=httpx.Response(429))
    settings = live_settings(tmp_path)

    with pytest.raises(LiveValidationError, match="failed and was not completed"):
        await run_validation(settings, request_for(), out_root=tmp_path / "out")

    # The failure is recorded, not hidden: a manifest exists and says so.
    manifest = json.loads((tmp_path / "out" / "test-run" / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert "rate_limit" in manifest["failure"]


# --- the bundle -------------------------------------------------------------


@respx.mock
async def test_the_bundle_holds_every_artefact_and_its_hash(tmp_path: Path) -> None:
    mock_provider()
    settings = live_settings(tmp_path)

    run = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    assert run.succeeded
    directory = run.directory
    for name in (
        "manifest.json",
        "trace.json",
        "normalized-transfers.json",
        "receipts.json",
        "accepted-label-snapshot.json",
        "report.html",
    ):
        assert (directory / name).is_file(), name
    assert list((directory / "raw").glob("*.json")), "raw exchanges were not saved"

    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["status"] == "succeeded"
    assert manifest["mode"] == "live"
    assert manifest["data_mode"] == "LIVE"
    assert manifest["provider_exchanges"] >= 3
    assert set(manifest["files"]) >= {"trace.json", "report.html"}
    assert all(len(h) == 64 for h in manifest["files"].values())


@respx.mock
async def test_the_bundle_never_contains_the_api_key(tmp_path: Path) -> None:
    mock_provider()
    settings = live_settings(tmp_path)

    run = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    for path in run.directory.rglob("*"):
        if path.is_file():
            assert API_KEY not in path.read_text(), f"{path} leaked the key"
    manifest = json.loads((run.directory / "manifest.json").read_text())
    assert manifest["configuration"]["tron_api_key_configured"] is True
    assert "tron_api_key" not in manifest["configuration"]


@respx.mock
async def test_the_live_trace_reaches_the_accepted_anchor_with_its_provenance(
    tmp_path: Path,
) -> None:
    mock_provider()
    settings = live_settings(tmp_path)

    run = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    assert run.trace is not None
    services = [b for b in run.trace["branch_endings"] if b["endpoint_class"] == "known_service"]
    (service,) = services
    assert service["address"] == SERVICE
    assert service["label"]["entity_name"] == "Example Exchange"
    assert service["label"]["reviewed_by"] == "investigator-1"
    snapshot = json.loads((run.directory / "accepted-label-snapshot.json").read_text())
    assert snapshot["registry"]["source"] == "reviewed_sets"
    assert snapshot["claims_used"][0]["address"] == SERVICE


@respx.mock
async def test_receipts_are_saved_and_separate_execution_from_finality(
    tmp_path: Path,
) -> None:
    mock_provider()
    settings = live_settings(tmp_path)

    run = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    receipts = json.loads((run.directory / "receipts.json").read_text())
    receipt = receipts["receipts"][TX]
    assert receipt["execution_status"] == "success"
    assert receipt["confirmation_state"] == "confirmed"
    assert receipt["solidified"] is True
    assert receipts["unverified"] == []
    assert run.trace is not None
    assert run.trace["seed_transfer"]["execution_status"] == "success"
    assert run.trace["seed_transfer"]["confirmation_state"] == "confirmed"


# --- report presentation -----------------------------------------------------

#: The exact block_time mock_provider()'s history row uses -- reused so a
#: snapshot-only label's bounds actually cover the transfer's arrival.
_TRANSFER_BLOCK_TIME = dt.datetime.fromtimestamp(1789862400000 / 1000, tz=dt.UTC)


def snapshot_label_dir(tmp_path: Path, *, methodology: str = "fixture") -> Path:
    """An accepted claim scoped to the transfer's own instant, role unknown --
    the shape that should surface every report-facing limitation at once."""
    data_dir = tmp_path / "data"
    source = tmp_path / "disclosure.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{SERVICE},Example Exchange,exchange,service_control,unknown\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url=SOURCE_URL,
            disclosure_kind=DisclosureKind.proof_of_reserves,
            disclosure_date=_TRANSFER_BLOCK_TIME,
            retrieved_at=dt.datetime(2026, 9, 19, tzinfo=dt.UTC),
            methodology=methodology,
            label_set_version="live-validation-test",
        ),
        network_key="tron",
        out_dir=data_dir,
        write=True,
    )
    report = review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key="tron",
                address=SERVICE,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="fixture",
                evidence_inspected=(SOURCE_URL,),
            )
        ],
        write=True,
    )
    assert not report.refusals
    # The importer never sets valid_to; pin it to the same instant as
    # valid_from so the claim is scoped to one moment, not an open interval.
    path = data_dir / "verified_anchors.csv"
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = list(reader)
    rows[0]["valid_to"] = _TRANSFER_BLOCK_TIME.isoformat()
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return data_dir


@respx.mock
async def test_the_limitations_section_reports_actual_run_facts(tmp_path: Path) -> None:
    mock_provider()
    settings = live_settings(tmp_path, label_dir=str(snapshot_label_dir(tmp_path)))

    run = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    codes = {x["code"] for x in run.trace["limitations"]}
    assert codes == {
        "snapshot_only_label",
        "address_role_unknown",
        "allocation_unknown",
        "bounded_analysis_window",
        "single_validation_case",
    }
    by_code = {x["code"]: x for x in run.trace["limitations"]}
    assert by_code["snapshot_only_label"]["address"] == SERVICE
    assert by_code["address_role_unknown"]["address"] == SERVICE


@respx.mock
async def test_an_accepted_labels_stale_review_wording_is_corrected_in_the_report_only(
    tmp_path: Path,
) -> None:
    """Stage 2 imports a candidate before it is reviewed, and the imported
    methodology says so. Once accepted, that wording is stale. The stored
    record must not change (it is the historical account of what was
    proposed); the rendered report must not keep saying it."""
    mock_provider()
    stale = (
        "Proposed scope, for human review, mirrors the sibling claim: "
        f"valid_from and valid_to both {_TRANSFER_BLOCK_TIME.isoformat()}."
    )
    settings = live_settings(
        tmp_path, label_dir=str(snapshot_label_dir(tmp_path, methodology=stale))
    )

    run = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    (ending,) = [b for b in run.trace["branch_endings"] if b["endpoint_class"] == "known_service"]
    assert ending["label"]["methodology"] == stale, "the stored record is untouched"

    html = (run.directory / "report.html").read_text()
    assert "Proposed scope, for human review" not in html
    assert "Accepted scope" in html


@respx.mock
async def test_budget_use_reports_traversal_requests_not_total_acquisition(
    tmp_path: Path,
) -> None:
    """A direct seed-to-anchor case never calls the tracer's own hop walk, so
    traversal_requests is honestly 0 even though real requests were made to
    find and verify the seed -- that total lives in run.exchanges instead."""
    mock_provider()
    settings = live_settings(tmp_path)

    run = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    budget = run.trace["budget_use"]
    assert "provider_requests" not in budget
    assert "provider_request_limit" not in budget
    assert budget["traversal_requests"] == 0
    assert run.exchanges > 0

    html = (run.directory / "report.html").read_text()
    assert "traversal requests" in html
    assert "provider requests" not in html.lower()
    assert "provider_exchanges" in html


# --- replay -----------------------------------------------------------------


@respx.mock
async def test_a_recorded_bundle_replays_through_the_same_pipeline(tmp_path: Path) -> None:
    mock_provider()
    settings = live_settings(tmp_path)
    live = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    respx.stop()  # nothing below may reach the network, mocked or not
    replay_settings = live_settings(
        tmp_path,
        data_mode=DataMode.RECORDED_PUBLIC,
        label_source=LabelSource.reviewed_sets,
        label_dir=settings.label_dir,
    )
    replay = await run_validation(
        replay_settings,
        ValidationRequest(
            address=VICTIM,
            token_contract=USDT,
            seed_event_reference=f"tron:{TX}:0",
            analysis_cutoff=CUTOFF,
            run_id="replay-run",
        ),
        out_root=tmp_path / "out",
        replay_from=live.directory / "raw",
    )

    assert replay.succeeded
    assert replay.trace is not None and live.trace is not None
    assert replay.trace["observed_transfers"] == live.trace["observed_transfers"]
    assert replay.trace["branch_endings"] == live.trace["branch_endings"]
    # And it is visibly a replay, not a live run.
    assert replay.trace["scope"]["data_mode"] == "RECORDED_PUBLIC"
    manifest = json.loads((replay.directory / "manifest.json").read_text())
    assert manifest["mode"] == "replay"


@respx.mock
async def test_a_replay_miss_is_an_error_not_an_empty_history(tmp_path: Path) -> None:
    mock_provider()
    settings = live_settings(tmp_path)
    live = await run_validation(settings, request_for(), out_root=tmp_path / "out")

    respx.stop()
    replay_settings = live_settings(
        tmp_path,
        data_mode=DataMode.RECORDED_PUBLIC,
        label_source=LabelSource.reviewed_sets,
        label_dir=settings.label_dir,
    )

    with pytest.raises(LiveValidationError, match="failed and was not completed"):
        await run_validation(
            replay_settings,
            ValidationRequest(
                # An address the recording knows nothing about.
                address="TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz",
                token_contract=USDT,
                analysis_cutoff=CUTOFF,
                run_id="replay-miss",
            ),
            out_root=tmp_path / "out",
            replay_from=live.directory / "raw",
        )


async def test_a_replay_cannot_claim_to_be_live(tmp_path: Path) -> None:
    settings = live_settings(tmp_path)

    with pytest.raises(LiveValidationError, match="a replay is not a live run"):
        await run_validation(
            settings,
            request_for(),
            out_root=tmp_path / "out",
            replay_from=tmp_path / "nonexistent",
        )


def test_the_exchange_key_separates_pages_of_one_endpoint() -> None:
    first = exchange_key("GET", HISTORY.format(address=VICTIM), {"limit": "200"}, {})
    second = exchange_key(
        "GET", HISTORY.format(address=VICTIM), {"limit": "200", "fingerprint": "abc"}, {}
    )

    assert first != second


# --- C06: the one test that needs the chain ---------------------------------
#
# Previous result, recorded so it is not overstated later:
#   - C06 passed as implemented, on 2026-09-20, against api.trongrid.io.
#   - Its output did NOT establish whether the acquired page was non-empty:
#     the per-event assertions sat inside `for event in page.events:`, which an
#     empty page satisfies vacuously.
#   - Its pytest exit code was not separately captured (the command was piped
#     into `tail`, so the observed status was tail's).
#   - The "1 event parsed" figure reported alongside it came from a SEPARATE
#     acquisition made by a different command, not from the C06 run.
#
# What changed: the page must now contain at least one parsed event, and the
# count is reported on success.

#: Two independent conditions, both required, because they answer different
#: questions. The key says the request *could* be authenticated; the opt-in says
#: someone *asked* for network access in this run.
#:
#: The opt-in is read from the process environment on purpose. `api/.env` is
#: loaded by pydantic-settings into `Settings`, never into `os.environ`, so a
#: line in that file cannot switch this on — it has to be typed on the command
#: line. `make test` additionally never collects this test: `-m "not live"` is
#: in the pytest addopts, so a configured key alone reaches no network.
LIVE_OPT_IN = "CFA_LIVE_TESTS"

#: The public example C06 queries. The TRC-20 USDT contract on TRON mainnet is
#: continuously active and is not anybody's personal wallet, so its history is
#: a stable public fixture. The window is fixed rather than "now" so the query
#: is the same query every run.
#:
#: If this returns nothing, that is a finding — the endpoint, the contract or
#: the query contract has changed — and the test says so and fails. It does not
#: fall back to another address and it does not substitute recorded data: a
#: contract test that quietly re-aims is not a contract test.
C06_ADDRESS = USDT
C06_CUTOFF = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
C06_LIMIT = 5
C06_ARTEFACT = Path(__file__).resolve().parents[2] / "var" / "c06-last-run.json"


def live_tests_enabled() -> tuple[bool, str]:
    """(runnable, why not). Never returns the key or any part of it."""
    import os

    if os.environ.get(LIVE_OPT_IN) != "1":
        return False, (
            f"C06 needs an explicit opt-in: {LIVE_OPT_IN}=1 on the command line. "
            "A configured key is deliberately not enough"
        )
    if not Settings().tron_api_key:
        return False, (
            "C06 needs CFA_TRON_API_KEY in api/.env (or the environment); "
            "without it TronGrid answers unauthenticated"
        )
    return True, ""


def require_events(page, *, address: str, cutoff: dt.datetime, limit: int) -> int:
    """Fail loudly when the chosen public example returned nothing.

    Empty is a legitimate answer for an arbitrary account — see
    `test_an_empty_page_is_a_valid_acquisition_in_general` — but not for this
    example, which was chosen because it always has history.
    """
    count = len(page.events)
    if count == 0:
        raise AssertionError(
            f"C06 expected history for {address} up to {cutoff.isoformat()} "
            f"(limit={limit}) and the page parsed 0 events. Either the provider "
            "stopped returning this history, the response shape changed so the "
            "parser dropped every row, or the example needs revisiting. Not "
            "substituting another address or recorded data."
        )
    return count


def _report_c06(count: int, page) -> None:
    """Make a passing run say what it saw. No key, no headers, no request URL."""
    summary = {
        "ran_at": dt.datetime.now(dt.UTC).isoformat(),
        "address": C06_ADDRESS,
        "analysis_cutoff": C06_CUTOFF.isoformat(),
        "limit": C06_LIMIT,
        "events_parsed": count,
        "acquisition_status": page.acquisition.status.value if page.acquisition else None,
        "coverage_status": page.acquisition.coverage_status.value if page.acquisition else None,
        "next_cursor_present": bool(page.next_cursor),
    }
    line = (
        f"C06: parsed {count} event(s) for {C06_ADDRESS} up to "
        f"{C06_CUTOFF.date()} (limit {C06_LIMIT}); "
        f"acquisition={summary['acquisition_status']}, "
        f"coverage={summary['coverage_status']}"
    )
    print(line)
    try:
        C06_ARTEFACT.parent.mkdir(parents=True, exist_ok=True)
        C06_ARTEFACT.write_text(json.dumps(summary, indent=2, sort_keys=True))
    except OSError:  # pragma: no cover - the artefact is a convenience
        pass


@pytest.mark.live
@pytest.mark.skipif(not live_tests_enabled()[0], reason=live_tests_enabled()[1])
async def test_c06_trongrid_answers_the_documented_shape(request) -> None:
    """Contract test: the live endpoint still returns what the adapter parses.

    Deliberately narrow. It asks for one bounded page of history for a public,
    continuously active contract address and checks the documented fields are
    present and parseable. It asserts nothing about any particular transfer,
    and it is not the Stage 1 gate — the gate is a validation bundle a person
    has inspected.

    The key comes from ``Settings``, the same path the application uses, so
    ``api/.env`` is enough and nothing here reads the value itself.
    """
    from app.adapters.base import AssetRef, Direction
    from app.adapters.tron import TronGridAdapter

    settings = Settings()
    adapter = TronGridAdapter(settings.tron_api_base, api_key=settings.tron_api_key)
    page = await adapter.fetch_transfers(
        address=C06_ADDRESS,
        asset=AssetRef("tron", USDT, 6, "USDT"),
        direction=Direction.both,
        analysis_cutoff=C06_CUTOFF,
        limit=C06_LIMIT,
    )

    assert page.acquisition is not None
    assert page.acquisition.status.value in {"succeeded", "partial"}

    count = require_events(page, address=C06_ADDRESS, cutoff=C06_CUTOFF, limit=C06_LIMIT)
    _report_c06(count, page)
    # Reporting must never be the reason a contract test fails.
    with contextlib.suppress(Exception):  # pragma: no cover - display only
        request.config.get_terminal_writer().line(
            f"\nC06 parsed {count} event(s); details in {C06_ARTEFACT}"
        )

    for event in page.events:
        assert event.tx_hash
        assert isinstance(event.amount_base_units, int)
        assert event.asset.token_contract == USDT


# --- offline coverage for the two halves of the rule ------------------------


@respx.mock
async def test_an_empty_page_is_a_valid_acquisition_in_general() -> None:
    """An account with no matching history is not an error anywhere else."""
    from app.adapters.base import AssetRef, Direction
    from app.adapters.tron import TronGridAdapter

    quiet = "TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz"
    respx.get(f"{BASE}{HISTORY.format(address=quiet)}").mock(
        return_value=httpx.Response(200, json={"data": [], "meta": {}})
    )

    page = await TronGridAdapter(BASE, api_key=API_KEY).fetch_transfers(
        address=quiet,
        asset=AssetRef("tron", USDT, 6, "USDT"),
        direction=Direction.both,
        analysis_cutoff=CUTOFF,
        limit=5,
    )

    assert page.events == []
    assert page.acquisition is not None
    assert page.acquisition.status.value == "succeeded"


def test_the_c06_example_rejects_an_empty_page() -> None:
    """The non-empty rule belongs to C06's example, not to every request."""
    from app.adapters.base import TransferPage

    with pytest.raises(AssertionError, match="parsed 0 events"):
        require_events(
            TransferPage(events=[]),
            address=C06_ADDRESS,
            cutoff=C06_CUTOFF,
            limit=C06_LIMIT,
        )


def test_the_c06_example_accepts_a_page_with_events() -> None:
    from app.adapters.base import TransferPage

    page = TransferPage(events=[object()])  # type: ignore[list-item]

    assert require_events(page, address=C06_ADDRESS, cutoff=C06_CUTOFF, limit=C06_LIMIT) == 1
