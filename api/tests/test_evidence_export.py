"""Stage 4: the evidence export bundle (PDF + CSV + JSON + manifest).

Pure-function tests only -- no client, no database, no chain. The bundle is
built from the exact same result-dict contract ``app.reports.evidence`` and
the trace endpoints already use, so a hand-built dict here is as valid an
input as one that came from a real trace.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json

from app.services.evidence_export import (
    EXPORT_FORMAT_VERSION,
    build_evidence_bundle,
)

GENERATED_AT = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=dt.UTC)


def _result(**overrides) -> dict:
    result = {
        "seed": {
            "address": "TVictim000000000000000000000000000",
            "event_reference": "tron:tx_seed:0",
            "network_key": "tron",
            "asset": {
                "token_contract": "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
                "display_symbol": "USDT-SYN",
                "decimals": 6,
            },
        },
        "scope": {
            "data_mode": "SYNTHETIC",
            "analysis_cutoff": "2026-09-22T00:00:00+00:00",
            "started_at": "2026-09-22T00:00:00+00:00",
            "finished_at": "2026-09-22T00:00:01+00:00",
            "engine_version": "0.1.0",
            "label_set_version": "3",
            "coverage_status": "complete_within_scope",
            "case_flow_linkage": "established",
            "label_snapshot": {},
        },
        "seed_transfer": {
            "event_reference": "tron:tx_seed:0",
            "tx_hash": "tx_seed",
            "from_address": "TVictim000000000000000000000000000",
            "to_address": "TMule0000000000000000000000000000",
            "amount_base_units": "750000000000",
            "amount_display": "750000.000000",
            "asset": {
                "token_contract": "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
                "decimals": 6,
                "display_symbol": "USDT-SYN",
            },
            "block_time": "2026-09-22T00:00:00+00:00",
            "chain_sequence": "0",
            "ordering_ambiguous": False,
            "execution_status": "success",
            "confirmation_state": "solidified",
            "hop_depth": 0,
            "acquisition_id": None,
        },
        "observed_transfers": [
            {
                "event_reference": "tron:tx_hop1:0",
                "tx_hash": "tx_hop1",
                "from_address": "TMule0000000000000000000000000000",
                "to_address": "TService0000000000000000000000000",
                "amount_base_units": "745297300000",
                "amount_display": "745297.300000",
                "asset": {
                    "token_contract": "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
                    "decimals": 6,
                    "display_symbol": "USDT-SYN",
                },
                "block_time": "2026-09-22T01:00:00+00:00",
                "chain_sequence": "1",
                "ordering_ambiguous": False,
                "execution_status": "success",
                "confirmation_state": "solidified",
                "hop_depth": 1,
                "acquisition_id": None,
            }
        ],
        "branch_endings": [
            {
                "address": "TService0000000000000000000000000",
                "endpoint_class": "known_service",
                "attribution_status": "supported",
                "boundary_reason": None,
                "hop_depth": 1,
                "branch_path": [
                    "TVictim000000000000000000000000000",
                    "TMule0000000000000000000000000000",
                    "TService0000000000000000000000000",
                ],
                "arrival_event_reference": "tron:tx_hop1:0",
                "observed_amount_base_units": "745297300000",
                "observed_amount_display": "745297.300000",
                "case_amount_basis": "allocation_unknown",
                "label": {
                    "entity_name": "Northwind Exchange (FICTIONAL)",
                    "entity_type": "exchange",
                    "assertion_type": "service_control",
                    "address_role": "hot_wallet",
                    "review_state": "accepted",
                    "source_reference": "https://example.test/disclosure",
                    "retrieval_date": "2026-09-01",
                    "methodology": "Accepted scope",
                    "reviewer": "analyst-1",
                    "valid_from": "2026-08-01T00:00:00+00:00",
                    "valid_to": None,
                    "last_verified_at": "2026-09-01T00:00:00+00:00",
                    "label_set_version": "3",
                    "source_hash": "abc123",
                    "source_file": "verified_anchors.csv",
                    "reviewed_by": "analyst-1",
                    "reviewed_at": "2026-09-01T00:00:00+00:00",
                    "label_source": None,
                    "original_reference": None,
                    "original_hash": None,
                    "original_member": None,
                    "original_row_locator": None,
                    "review_reference": "abc123456789012@2026-09-01T00:00:00+00:00",
                },
                "note": None,
            }
        ],
        "limitations": [
            {
                "code": "hop_limit_reached",
                "message": "stopped after the configured hop budget",
                "address": "TService0000000000000000000000000",
                "event_reference": None,
            }
        ],
        "budget_use": {
            "hops_used": 1,
            "hop_limit": 8,
            "events_examined": 2,
            "event_limit": 5000,
            "traversal_requests": 1,
            "traversal_request_limit": 400,
            "elapsed_seconds": 0.02,
        },
        "acquisitions": [],
        "disclaimer": (
            "An observed path establishes a sequence of transfers, not ownership of "
            "fungible units. This output does not identify a person, establish guilt, "
            "or authorise a freeze."
        ),
    }
    result.update(overrides)
    return result


def test_bundle_contains_every_expected_file() -> None:
    bundle = build_evidence_bundle(_result(), request_id="req-1", generated_at=GENERATED_AT)
    names = {f.name for f in bundle.files}
    assert names == {
        "evidence.json",
        "evidence.html",
        "evidence.pdf",
        "transfers.csv",
        "branch_endings.csv",
        "labels.csv",
        "limitations.csv",
    }


def test_pdf_file_starts_with_the_pdf_magic_bytes() -> None:
    bundle = build_evidence_bundle(_result(), generated_at=GENERATED_AT)
    assert bundle.file("evidence.pdf").content.startswith(b"%PDF")


def test_json_file_round_trips_the_exact_source_result() -> None:
    result = _result()
    bundle = build_evidence_bundle(result, generated_at=GENERATED_AT)
    assert json.loads(bundle.file("evidence.json").content) == result


def test_transfers_csv_includes_the_seed_transfer_and_each_onward_hop() -> None:
    bundle = build_evidence_bundle(_result(), generated_at=GENERATED_AT)
    rows = list(csv.DictReader(io.StringIO(bundle.file("transfers.csv").content.decode())))
    assert len(rows) == 2, "one seed transfer (hop 0) plus one onward transfer (hop 1)"
    assert rows[0]["hop_depth"] == "0"
    assert rows[0]["from_address"] == "TVictim000000000000000000000000000"
    assert rows[1]["hop_depth"] == "1"
    assert rows[1]["amount_base_units"] == "745297300000"


def test_branch_endings_csv_reports_the_attribution_status() -> None:
    bundle = build_evidence_bundle(_result(), generated_at=GENERATED_AT)
    rows = list(csv.DictReader(io.StringIO(bundle.file("branch_endings.csv").content.decode())))
    assert len(rows) == 1
    assert rows[0]["endpoint_class"] == "known_service"
    assert rows[0]["attribution_status"] == "supported"
    assert rows[0]["entity_name"] == "Northwind Exchange (FICTIONAL)"


def test_labels_csv_is_empty_when_no_branch_carries_a_label() -> None:
    result = _result()
    result["branch_endings"][0]["label"] = None
    bundle = build_evidence_bundle(result, generated_at=GENERATED_AT)
    rows = list(csv.DictReader(io.StringIO(bundle.file("labels.csv").content.decode())))
    assert rows == []


def test_limitations_csv_reports_the_recorded_limitation() -> None:
    bundle = build_evidence_bundle(_result(), generated_at=GENERATED_AT)
    rows = list(csv.DictReader(io.StringIO(bundle.file("limitations.csv").content.decode())))
    assert rows == [
        {
            "code": "hop_limit_reached",
            "message": "stopped after the configured hop budget",
            "address": "TService0000000000000000000000000",
            "event_reference": "",
        }
    ]


def test_manifest_files_is_the_project_wide_name_to_sha256_mapping() -> None:
    """Same shape as live_validation.py / collect_resource_evidence.py /
    collect_behavioral_evidence.py: {relative filename: sha256 hex}, not a
    list of objects -- so this bundle needs no adapter to be checked by the
    existing app.services.operational_status.verify_manifest_hashes."""
    bundle = build_evidence_bundle(_result(), generated_at=GENERATED_AT)
    assert isinstance(bundle.manifest["files"], dict)
    for f in bundle.files:
        assert bundle.manifest["files"][f.name] == hashlib.sha256(f.content).hexdigest()


def test_manifest_interoperates_with_verify_manifest_hashes(tmp_path) -> None:
    from app.services.operational_status import verify_manifest_hashes

    bundle = build_evidence_bundle(_result(), generated_at=GENERATED_AT)
    for f in bundle.files:
        (tmp_path / f.name).write_bytes(f.content)

    report = verify_manifest_hashes(bundle.manifest, tmp_path)
    assert report["checked"] == len(bundle.files)
    assert report["ok"] == len(bundle.files)
    assert report["failed"] == 0
    assert report["missing"] == 0


def test_manifest_never_claims_the_hash_proves_correctness() -> None:
    bundle = build_evidence_bundle(_result(), generated_at=GENERATED_AT)
    caveat = bundle.manifest["caveat"].lower()
    assert "not establish that the attribution is correct" in caveat
    assert "not a legal instrument" in caveat


def test_manifest_carries_scope_and_format_version() -> None:
    bundle = build_evidence_bundle(_result(), request_id="req-9", generated_at=GENERATED_AT)
    assert bundle.manifest["export_format_version"] == EXPORT_FORMAT_VERSION
    assert bundle.manifest["request_id"] == "req-9"
    assert bundle.manifest["data_mode"] == "SYNTHETIC"
    assert bundle.manifest["coverage_status"] == "complete_within_scope"
    assert bundle.manifest["case_flow_linkage"] == "established"
    assert bundle.manifest["generated_at"] == GENERATED_AT.isoformat()


def test_json_and_csv_files_are_byte_identical_across_two_builds() -> None:
    """These are a pure function of the result: same input, same bytes, every
    time. (``evidence.html`` is excluded: its own "Generated at ..." line is
    ``datetime.now()``-stamped by ``render_evidence_html`` itself, independent
    of this module's ``generated_at`` parameter -- that non-determinism is
    existing Stage 1 report behaviour, not something introduced here. The PDF
    is excluded for the same reason plus its own embedded metadata.)"""
    result = _result()
    first = build_evidence_bundle(result, request_id="req-x", generated_at=GENERATED_AT)
    second = build_evidence_bundle(result, request_id="req-x", generated_at=GENERATED_AT)
    for name in ("evidence.json", "transfers.csv", "branch_endings.csv",
                 "labels.csv", "limitations.csv"):
        assert first.file(name).content == second.file(name).content, name

    # The manifest's own evidence.pdf and evidence.html entries are excluded:
    # xhtml2pdf/reportlab stamp the PDF with creation-time metadata, and
    # render_evidence_html stamps its "Generated at ..." line with
    # datetime.now() (existing Stage 1 report behaviour, not introduced here)
    # -- so both files' hashes legitimately differ run to run even for
    # identical input. Everything else in the manifest must not.
    def _without_timestamped_entries(manifest: dict) -> dict:
        return {
            **manifest,
            "files": {
                name: digest
                for name, digest in manifest["files"].items()
                if name not in ("evidence.pdf", "evidence.html")
            },
        }

    assert _without_timestamped_entries(first.manifest) == _without_timestamped_entries(
        second.manifest
    )


def test_pdf_rendering_failure_raises_instead_of_returning_a_partial_file(monkeypatch) -> None:
    from app.services import evidence_export

    class _FailingStatus:
        err = 1

    def _fail(_src, dest):  # noqa: ARG001 - matches xhtml2pdf.pisa.CreatePDF's signature
        return _FailingStatus()

    monkeypatch.setattr(evidence_export.pisa, "CreatePDF", _fail)
    try:
        build_evidence_bundle(_result(), generated_at=GENERATED_AT)
    except evidence_export.EvidenceExportError:
        pass
    else:
        raise AssertionError("expected EvidenceExportError when PDF rendering fails")
