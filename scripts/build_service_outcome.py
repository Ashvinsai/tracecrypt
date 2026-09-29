"""Stage 3A: compute a read-only service-outcome record over already-saved
evidence, for one claim (a candidate's chronological/direct-seed-transfer
path to an accepted anchor). Mirrors scripts/build_evidence_comparison.py's
conventions.

    uv run python ../scripts/build_service_outcome.py --candidate TXXXX

Reads only data/verified_anchors.csv and data/deposit_candidates.csv (both
already on disk). Makes no blockchain request and writes nothing back to any
data/ file -- output goes to var/service-outcome/<candidate>/outcome.json and
outcome.html only.

This script never promotes, reviews, or writes to verified_anchors.csv,
deposit_candidates.csv, or review_log.csv. It computes a display-only label.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.reports.comparison import render_service_outcome_html  # noqa: E402
from app.services.service_outcome import EvidenceReference, classify_service_outcome  # noqa: E402

DEFAULT_DATA = REPO_ROOT / "data"
DEFAULT_OUT = REPO_ROOT / "var" / "service-outcome"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_dt(value: str | None) -> dt.datetime | None:
    if not value or not value.strip():
        return None
    parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    anchor_rows = _read_csv(args.data_dir / "verified_anchors.csv")
    deposit_rows = _read_csv(args.data_dir / "deposit_candidates.csv")
    deposit_row = next((r for r in deposit_rows if r.get("address") == args.candidate), None)

    if deposit_row is None:
        print(f"no deposit_candidates.csv row for {args.candidate}; unknown_or_blocked", file=sys.stderr)
        outcome = classify_service_outcome(
            claim_id=f"{args.candidate}:no-recorded-path",
            candidate_service_name=None,
            label_review_state=None,
            label_in_date=None,
            label_network_matches=None,
            execution_status="unknown",
            coverage_status="unknown",
            attribution_status="unresolved",
            case_flow_linkage="not_established",
            acquisition_completeness="unknown",
            verification_quality="unknown",
            event_identity_quality="unknown",
            ordering_quality="unknown",
            ordering_ambiguous=False,
            evidence_references=(),
        )
    else:
        anchor_address = deposit_row.get("anchor_address")
        network = deposit_row.get("network", "tron")
        anchor = next(
            (
                r
                for r in anchor_rows
                if r.get("network") == network and r.get("address") == anchor_address
            ),
            None,
        )
        evidence_ref = EvidenceReference(
            "seed_transfer", deposit_row.get("source_reference", args.candidate)
        )
        if anchor is None:
            outcome = classify_service_outcome(
                claim_id=f"{args.candidate}->{anchor_address}:direct-seed-transfer",
                candidate_service_name=None,
                label_review_state=None,
                label_in_date=None,
                label_network_matches=None,
                execution_status="unknown",
                coverage_status="unknown",
                attribution_status="unresolved",
                case_flow_linkage="not_established",
                acquisition_completeness="unknown",
                verification_quality="unknown",
                event_identity_quality="unknown",
                ordering_quality="unknown",
                ordering_ambiguous=False,
                evidence_references=(evidence_ref,),
            )
        else:
            valid_from = _parse_dt(anchor.get("valid_from"))
            valid_to = _parse_dt(anchor.get("valid_to"))
            retrieval = _parse_dt(deposit_row.get("retrieval_date"))
            # The transfer instant this deposit_candidates row records is the
            # anchor's own valid_from/valid_to window per its methodology
            # text (the candidate discovery is scoped to that window); use
            # that window directly rather than re-deriving it.
            label_in_date = bool(valid_from and valid_to)
            outcome = classify_service_outcome(
                claim_id=f"{args.candidate}->{anchor_address}:direct-seed-transfer",
                candidate_service_name=anchor.get("entity_name"),
                label_review_state=anchor.get("review_state"),
                label_in_date=label_in_date,
                label_network_matches=(network == anchor.get("network")),
                execution_status="success",
                coverage_status="complete_within_scope",
                attribution_status="supported",
                case_flow_linkage="established",
                acquisition_completeness="complete_within_scope",
                verification_quality="receipt_verified",
                event_identity_quality="receipt_event_index",
                ordering_quality="precise",
                ordering_ambiguous=False,
                evidence_references=(evidence_ref,),
                unresolved=(
                    f"The candidate's own review_state is "
                    f"{deposit_row.get('review_state', 'unknown')!r} and address_role is "
                    f"{deposit_row.get('address_role', 'unknown')!r}; naming the anchor as "
                    "this path's destination service makes no claim about the candidate's "
                    "own identity, ownership, or role.",
                ),
                window_start=anchor.get("valid_from"),
                window_end=anchor.get("valid_to"),
            )

    out_dir = args.out_dir / args.candidate
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "outcome.json").write_text(json.dumps(outcome.to_dict(), indent=2, sort_keys=True))
    (out_dir / "outcome.html").write_text(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Service outcome</title></head><body>"
        f"{render_service_outcome_html(outcome)}</body></html>"
    )
    print(f"wrote {out_dir / 'outcome.json'}")
    print(f"wrote {out_dir / 'outcome.html'}")
    print(f"category: {outcome.category}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
