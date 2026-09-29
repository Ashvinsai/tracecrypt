"""Import address claims from a downloaded disclosure into the label sets.

    uv run python ../scripts/import_anchors.py \
        --file ~/Downloads/okx-por-tron.csv \
        --url https://www.okx.com/proof-of-reserves/download \
        --kind proof_of_reserves \
        --disclosed 2026-06-30 \
        --methodology "Selected the rows explicitly on TRON." \
        --label-set-version okx-por-2026-06

Prints what each row would become and changes nothing until ``--write``. Rows
land as ``review_state=unreviewed`` whatever the source: a human opens the
source and accepts it, and only an accepted service-control row can end a trace.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.services.anchor_import import (  # noqa: E402
    AnchorImportError,
    DisclosureKind,
    SourceDocument,
    import_anchors,
)

DEFAULT_OUT = REPO_ROOT / "data"


def parse_date(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--file", required=True, type=Path, help="the downloaded disclosure")
    parser.add_argument("--url", required=True, help="where the file came from")
    parser.add_argument(
        "--kind",
        required=True,
        choices=[k.value for k in DisclosureKind],
        help="what the document is; it decides what the rows may establish",
    )
    parser.add_argument(
        "--disclosed", required=True, type=parse_date, help="the document's own date"
    )
    parser.add_argument("--methodology", required=True, help="how the rows were selected")
    parser.add_argument("--label-set-version", required=True)
    parser.add_argument("--network", default="tron")
    parser.add_argument("--reviewer", default=None)
    parser.add_argument("--upstream-source", default=None, help="required for an aggregator copy")
    parser.add_argument("--reuse-terms", default=None, help="required for an aggregator copy")
    parser.add_argument(
        "--original-file",
        type=Path,
        default=None,
        help="the publication this file was cut from, preserved where it is and hashed",
    )
    parser.add_argument("--original-member", default=None, help="the file inside that archive")
    parser.add_argument(
        "--original-row-locator",
        default=None,
        help="where in that file the row is, e.g. absolute_line=44282;section_row=44257",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--write", action="store_true", help="without this, nothing is written")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    document = SourceDocument(
        path=args.file.expanduser(),
        url=args.url,
        disclosure_kind=DisclosureKind(args.kind),
        disclosure_date=args.disclosed,
        retrieved_at=dt.datetime.now(dt.UTC),
        methodology=args.methodology,
        label_set_version=args.label_set_version,
        reviewer=args.reviewer,
        upstream_source=args.upstream_source,
        reuse_terms=args.reuse_terms,
        original_file=args.original_file.expanduser() if args.original_file else None,
        original_member=args.original_member,
        original_row_locator=args.original_row_locator,
    )

    try:
        report = import_anchors(
            document, network_key=args.network, out_dir=args.out_dir, write=args.write
        )
    except AnchorImportError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    print(f"document          {document.path.name}  sha256:{report.document_hash[:16]}")
    if document.original_file is not None:
        original_hash = document.original_sha256() or ""
        print(f"original          {document.original_file.name}  sha256:{original_hash[:16]}")
        print(f"  member          {document.original_member}")
        print(f"  row             {document.original_row_locator}")
    print(f"result            {report.summary()}")
    for row in report.accepted:
        print(f"  -> {row.destination.value:<20} {row.address:<36} {row.address_role.value}")
    for address in report.updated:
        print(f"  ~= {'provenance updated':<20} {address:<36} (row not duplicated)")
    for downgrade in report.downgrades:
        print(f"  ~  line {downgrade.line}: {downgrade.code}: {downgrade.message}")
    for rejection in report.rejections:
        print(f"  x  line {rejection.line}: {rejection.code}: {rejection.message}")

    repeated = [(k, c) for k, c in report.corroboration.items() if c.documents > c.distinct_sources]
    for (network, address), corroboration in repeated:
        print(f"  !  {network}:{address}: {corroboration.note}")

    if not args.write:
        print("\nnothing written (pass --write)")
    else:
        print(f"\nwrote into {args.out_dir}; review each row before setting review_state=accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
