"""Stage 4: the evidence export bundle (PDF + CSV + JSON + a checksum manifest).

The Stage 1 report (``app.reports.evidence.render_evidence_html``) already
prints to PDF from a browser -- that was the Stage 1 requirement. This module
is the upgrade the five-stage plan calls for: a generated PDF plus a CSV/JSON
package with file-integrity hashes, built for an investigator to attach to a
case file without needing a browser's print dialog.

The PDF is rendered from the *same* HTML the report route already serves and
already has tests for, so the PDF, the HTML report, and this bundle's
``evidence.json`` can never disagree with each other -- there is exactly one
template. A SHA-256 hash in the manifest establishes that a file has not
changed since this bundle was generated; per AGENTS.md, that is file
consistency, not evidence that the underlying attribution is correct, and
this module never claims otherwise.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

from app.reports.evidence import render_evidence_html

#: Bumped when the set of files in a bundle, or a file's own column layout,
#: changes in a way a downstream consumer (a records system, a script) would
#: need to know about.
EXPORT_FORMAT_VERSION = "1"

#: Matches the wording used by every other manifest in this project (see
#: live_validation.py, collect_resource_evidence.py, collect_behavioral_
#: evidence.py) so an investigator reads the same caveat regardless of which
#: bundle they opened.
MANIFEST_CAVEAT = (
    "A hash establishes that these files have not changed since this bundle "
    "was generated. It does not establish that the attribution is correct, "
    "and this bundle is not a legal instrument."
)


class EvidenceExportError(RuntimeError):
    """Raised when a bundle file cannot be produced from a valid trace result."""


@dataclass(frozen=True)
class EvidenceBundleFile:
    name: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class EvidenceBundle:
    files: tuple[EvidenceBundleFile, ...]
    manifest: dict[str, Any]

    def file(self, name: str) -> EvidenceBundleFile:
        for f in self.files:
            if f.name == name:
                return f
        raise KeyError(name)

    def manifest_bytes(self) -> bytes:
        return json.dumps(self.manifest, indent=2, sort_keys=True).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(headers)
    # JSON remains the exact machine-readable evidence. Prefix potentially
    # executable spreadsheet cells, including whitespace-prefixed formulas.
    def safe_cell(value):
        text = str(value)
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")) else text
    writer.writerows([[safe_cell(value) for value in row] for row in rows])
    return buf.getvalue().encode("utf-8")


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _transfers_csv(result: dict[str, Any]) -> bytes:
    headers = [
        "hop_depth",
        "block_time",
        "from_address",
        "to_address",
        "amount_base_units",
        "amount_display",
        "asset_symbol",
        "event_reference",
        "execution_status",
        "confirmation_state",
        "ordering_ambiguous",
    ]
    seed_transfer = result.get("seed_transfer")
    transfers = ([seed_transfer] if seed_transfer else []) + list(result["observed_transfers"])
    rows = [
        [
            _str(t["hop_depth"]),
            _str(t["block_time"]),
            _str(t["from_address"]),
            _str(t["to_address"]),
            _str(t["amount_base_units"]),
            _str(t["amount_display"]),
            _str(t["asset"]["display_symbol"]),
            _str(t["event_reference"]),
            _str(t["execution_status"]),
            _str(t["confirmation_state"]),
            _str(t["ordering_ambiguous"]),
        ]
        for t in transfers
    ]
    return _csv_bytes(headers, rows)


def _branch_endings_csv(result: dict[str, Any]) -> bytes:
    headers = [
        "address",
        "endpoint_class",
        "attribution_status",
        "entity_name",
        "assertion_type",
        "address_role",
        "review_state",
        "observed_amount_base_units",
        "observed_amount_display",
        "case_amount_basis",
        "boundary_reason",
        "hop_depth",
    ]
    rows = []
    for b in result["branch_endings"]:
        label = b.get("label") or {}
        rows.append(
            [
                _str(b["address"]),
                _str(b["endpoint_class"]),
                _str(b["attribution_status"]),
                _str(label.get("entity_name")),
                _str(label.get("assertion_type")),
                _str(label.get("address_role")),
                _str(label.get("review_state")),
                _str(b["observed_amount_base_units"]),
                _str(b["observed_amount_display"]),
                _str(b["case_amount_basis"]),
                _str(b["boundary_reason"]),
                _str(b["hop_depth"]),
            ]
        )
    return _csv_bytes(headers, rows)


def _labels_csv(result: dict[str, Any]) -> bytes:
    headers = [
        "entity_name",
        "address",
        "source_reference",
        "retrieval_date",
        "methodology",
        "valid_from",
        "valid_to",
        "last_verified_at",
        "reviewed_by",
        "reviewed_at",
        "source_hash",
    ]
    rows = []
    for b in result["branch_endings"]:
        label = b.get("label")
        if not label:
            continue
        rows.append(
            [
                _str(label.get("entity_name")),
                _str(b["address"]),
                _str(label.get("source_reference")),
                _str(label.get("retrieval_date")),
                _str(label.get("methodology")),
                _str(label.get("valid_from")),
                _str(label.get("valid_to")),
                _str(label.get("last_verified_at")),
                _str(label.get("reviewed_by")),
                _str(label.get("reviewed_at")),
                _str(label.get("source_hash")),
            ]
        )
    return _csv_bytes(headers, rows)


def _limitations_csv(result: dict[str, Any]) -> bytes:
    headers = ["code", "message", "address", "event_reference"]
    rows = [
        [_str(x["code"]), _str(x["message"]), _str(x["address"]), _str(x["event_reference"])]
        for x in result["limitations"]
    ]
    return _csv_bytes(headers, rows)


def _render_pdf(html: str) -> bytes:
    buf = io.BytesIO()
    if pisa is None:
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise EvidenceExportError(
                "PDF export requires xhtml2pdf (recommended) or WeasyPrint. "
                "HTML and JSON remain available through the saved investigation endpoints."
            ) from exc
        # Generated reports contain no external resources. Deny URL fetches
        # even if a future report template accidentally introduces one.
        def no_external_fetch(url, **kwargs):
            raise ValueError("external resources are disabled for evidence PDFs")
        return HTML(string=html, url_fetcher=no_external_fetch).write_pdf()
    pdf_status = pisa.CreatePDF(io.StringIO(html), dest=buf)
    if pdf_status.err:
        raise EvidenceExportError(
            f"PDF rendering reported {pdf_status.err} error(s); refusing to return a partial PDF"
        )
    return buf.getvalue()


def build_evidence_bundle(
    result: dict[str, Any],
    *,
    request_id: str = "",
    generated_at: dt.datetime | None = None,
) -> EvidenceBundle:
    """Build every export file from one trace result. Pure function: no I/O.

    ``generated_at`` is a parameter (not always ``datetime.now``) so a caller
    that persists a bundle can pin its manifest timestamp to when the trace
    itself finished, and so tests are deterministic.
    """
    generated_at = generated_at or dt.datetime.now(dt.UTC)
    html = render_evidence_html(result, request_id=request_id)

    file_contents: dict[str, bytes] = {
        "evidence.json": json.dumps(result, indent=2, sort_keys=True).encode("utf-8"),
        "evidence.html": html.encode("utf-8"),
        "evidence.pdf": _render_pdf(html),
        "transfers.csv": _transfers_csv(result),
        "branch_endings.csv": _branch_endings_csv(result),
        "labels.csv": _labels_csv(result),
        "limitations.csv": _limitations_csv(result),
    }

    files = tuple(
        EvidenceBundleFile(name=name, content=content, sha256=_sha256(content))
        for name, content in file_contents.items()
    )

    scope = result["scope"]
    manifest = {
        "export_format_version": EXPORT_FORMAT_VERSION,
        "generated_at": generated_at.isoformat(),
        "request_id": request_id,
        "seed": result["seed"],
        "data_mode": scope["data_mode"],
        "analysis_cutoff": scope["analysis_cutoff"],
        "coverage_status": scope["coverage_status"],
        "case_flow_linkage": scope["case_flow_linkage"],
        "engine_version": scope["engine_version"],
        "label_set_version": scope["label_set_version"],
        #: {relative filename: sha256 hex digest} -- the same shape every other
        #: manifest in this project uses (live_validation.py,
        #: collect_resource_evidence.py, collect_behavioral_evidence.py), so
        #: this bundle can be checked with the existing
        #: app.services.operational_status.verify_manifest_hashes without
        #: adapting either side.
        "files": {f.name: f.sha256 for f in files},
        "caveat": MANIFEST_CAVEAT,
        "csv_safety": "Formula-like text cells are prefixed with an apostrophe; evidence.json retains exact source strings.",
    }

    return EvidenceBundle(files=files, manifest=manifest)
