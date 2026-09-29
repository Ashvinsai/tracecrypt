"""Deterministic evidence report.

Every fact here comes from the trace result. No language model composes any of
it, nothing is summarised into a confidence score, and no number is recomputed:
the amounts printed are the exact strings the engine produced.

The page prints to PDF from any browser. That is the Stage 1 requirement; a
signed bundle with a checksum manifest is Stage 4.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from typing import Any

#: A methodology's own wording can go stale between when a candidate was
#: imported (written in anticipation of review) and when this report is read
#: (after a human has since accepted it). The stored text in
#: data/verified_anchors.csv is the historical record and is never edited;
#: this substitution is display-only, applied only when the label is
#: actually accepted, and only to the specific phrase it names.
_STALE_PENDING_REVIEW_PHRASES = {
    "Proposed scope, for human review": "Accepted scope",
}


def _presentation_methodology(label: dict[str, Any]) -> str:
    text = str(label.get("methodology") or "")
    if label.get("review_state") == "accepted":
        for stale, corrected in _STALE_PENDING_REVIEW_PHRASES.items():
            text = text.replace(stale, corrected)
    return text

STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 13px/1.5 ui-monospace, "SFMono-Regular", Menlo, monospace;
       color: #1b1d21; background: #fff; margin: 0; padding: 24px; }
h1 { font-size: 17px; margin: 0 0 2px; }
h2 { font-size: 13px; margin: 26px 0 8px; text-transform: uppercase;
     letter-spacing: .08em; border-bottom: 1px solid #1b1d21; padding-bottom: 4px; }
.mode { display: inline-block; padding: 3px 9px; margin-bottom: 14px;
        border: 1px solid #6a5c3f; background: #eeeae1; color: #6a5c3f;
        font-weight: 700; letter-spacing: .05em; }
.mode.live { border-color: #3f5747; background: #e9edea; color: #3f5747; }
table { table-layout: fixed; width: 100%; border-collapse: collapse; margin: 6px 0 2px; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid #d6d8dc;
         vertical-align: top; word-break: break-all; overflow-wrap: anywhere; word-wrap: break-word; }
th { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #5a5e66; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: normal; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 2px 18px; margin: 0; }
dt { color: #5a5e66; }
dd { margin: 0; word-break: break-all; overflow-wrap: anywhere; }
.record { padding: 10px 0; border-bottom: 1px solid #d6d8dc; }
.record dl { grid-template-columns: 145px 1fr; }
@page { size: A4; margin: 18mm; }
@media print { table { font-size: 10px; } th { font-size: 9px; letter-spacing: 0; } }
.tag { display: inline-block; padding: 1px 6px; border: 1px solid currentColor;
       font-size: 11px; letter-spacing: .04em; }
.supported { color: #3f5747; }
.candidate { color: #6a5c3f; }
.unresolved, .boundary { color: #5a5e66; }
.flag { color: #7c4444; }
.note { color: #5a5e66; font-size: 12px; margin: 4px 0 0; }
.caveat { border: 1px solid #1b1d21; padding: 10px 12px; margin-top: 26px; font-size: 12px; }
.empty { color: #5a5e66; font-style: italic; padding: 6px 0; }
@media print { body { padding: 0; } h2 { break-after: avoid; } tr { break-inside: avoid; } }
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _rows(headers: list[str], rows: list[list[str]], *, empty: str) -> str:
    if not rows:
        return f'<p class="empty">{_e(empty)}</p>'
    if len(headers) >= 8:
        # Ten-column provenance tables become unreadable/clipped in portrait
        # PDFs. Preserve every value, displaying these wide records vertically.
        records = []
        for cells in rows:
            values = [re.sub(r"^<td[^>]*>|</td>$", "", cell) for cell in cells]
            fields = "".join(f"<dt>{_e(name)}</dt><dd>{value}</dd>" for name, value in zip(headers, values))
            records.append(f'<section class="record"><dl>{fields}</dl></section>')
        return "".join(records)
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(cells) + "</tr>" for cells in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_evidence_html(result: dict[str, Any], *, request_id: str = "") -> str:
    seed = result["seed"]
    scope = result["scope"]
    mode = scope["data_mode"]
    mode_class = "mode live" if mode == "LIVE" else "mode"
    mode_text = mode if mode == "LIVE" else f"{mode} — NOT LIVE CHAIN DATA"

    def _transfer_cells(t: dict[str, Any]) -> list[str]:
        return [
            f"<td class='num'>{_e(t['hop_depth'])}</td>",
            f"<td>{_e(t['block_time'])}</td>",
            f"<td>{_e(t['from_address'])}</td>",
            f"<td>{_e(t['to_address'])}</td>",
            f"<td class='num'>{_e(t['amount_display'])} {_e(t['asset']['display_symbol'])}</td>",
            f"<td>{_e(t['event_reference'])}</td>",
            "<td>"
            + _e(t["execution_status"])
            + " / "
            + _e(t["confirmation_state"])
            + (
                "<br><span class='flag'>ordering ambiguous</span>"
                if t["ordering_ambiguous"]
                else ""
            )
            + "</td>",
        ]

    seed_transfer = result.get("seed_transfer")
    transfer_rows = (
        [_transfer_cells(seed_transfer)] if seed_transfer else []
    ) + [_transfer_cells(t) for t in result["observed_transfers"]]

    ending_rows = []
    for b in result["branch_endings"]:
        label = b.get("label")
        entity = (
            f"{_e(label['entity_name'])}<br><span class='note'>{_e(label['assertion_type'])}"
            f" · {_e(label['address_role'])} · {_e(label['review_state'])}</span>"
            if label
            else "<span class='note'>no label</span>"
        )
        ending_rows.append(
            [
                f"<td>{_e(b['address'])}</td>",
                f"<td><span class='tag {_e(b['endpoint_class'])}'>"
                f"{_e(b['endpoint_class'])}</span></td>",
                f"<td>{entity}</td>",
                f"<td class='num'>{_e(b['observed_amount_display'])}</td>",
                f"<td>{_e(b['case_amount_basis'])}</td>",
                f"<td>{_e(b['boundary_reason'] or '—')}</td>",
                f"<td class='num'>{_e(b['hop_depth'])}</td>",
            ]
        )

    label_rows = []
    for b in result["branch_endings"]:
        label = b.get("label")
        if not label:
            continue
        label_rows.append(
            [
                f"<td>{_e(label['entity_name'])}</td>",
                f"<td>{_e(b['address'])}</td>",
                f"<td>{_e(label['source_reference'])}</td>",
                f"<td>{_e(label['retrieval_date'])}</td>",
                f"<td>{_e(_presentation_methodology(label))}</td>",
                f"<td>{_e(label['valid_from'])} → {_e(label['valid_to'] or 'open')}</td>",
                f"<td>{_e(label['last_verified_at'])}</td>",
                f"<td>{_e(label.get('reviewed_by') or '—')}<br>"
                f"<span class='note'>{_e(label.get('reviewed_at') or 'not reviewed')}</span></td>",
                f"<td><span class='note'>{_e(label.get('source_hash') or '—')}</span></td>",
                f"<td>{_e(label.get('original_reference') or '—')}"
                + (
                    f"<br><span class='note'>{_e(label.get('original_member') or '')} · "
                    f"{_e(label.get('original_row_locator') or '')}<br>"
                    f"{_e(label.get('original_hash') or '')}</span>"
                    if label.get("original_reference")
                    else ""
                )
                + "</td>",
            ]
        )

    snapshot = scope.get("label_snapshot") or {}
    label_file_rows = [
        [
            f"<td>{_e(f['name'])}</td>",
            f"<td class='num'>{_e(f['rows_loaded'])}</td>",
            f"<td class='num'>{_e(f['rows_withdrawn'])}</td>",
            f"<td><span class='note'>{_e(f['sha256'])}</span></td>",
        ]
        for f in snapshot.get("files", [])
    ]

    limitation_rows = [
        [
            f"<td>{_e(x['code'])}</td>",
            f"<td>{_e(x['message'])}</td>",
            f"<td>{_e(x['address'] or '—')}</td>",
            f"<td>{_e(x['event_reference'] or '—')}</td>",
        ]
        for x in result["limitations"]
    ]

    budget = result["budget_use"]
    # A saved trace can predate a rename of the budget fields (for example
    # traversal_requests/provider_requests). Prefer the current name, fall
    # back to the older one, and never raise just to print a report.
    traversal_requests = budget.get("traversal_requests", budget.get("provider_requests", 0))
    traversal_limit = budget.get(
        "traversal_request_limit", budget.get("provider_request_limit", 0)
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Trace evidence — {_e(seed["address"])}</title>
<style>{STYLE}</style></head><body>
<div class="{mode_class}">{_e(mode_text)}</div>
<h1>Transfer trace evidence</h1>
<p class="note">Trace completed {_e(scope.get("finished_at") or "unknown")} ·
request {_e(request_id)} · engine {_e(scope["engine_version"])} ·
label set {_e(scope["label_set_version"])}</p>

<h2>Subject</h2>
<dl>
<dt>Network</dt><dd>{_e(seed["network_key"])}</dd>
<dt>Seed address</dt><dd>{_e(seed["address"])}</dd>
<dt>Seed event</dt><dd>{_e(seed["event_reference"] or "none — address-scoped activity only")}</dd>
<dt>Asset</dt><dd>{_e(seed["asset"]["display_symbol"])}
 (contract {_e(seed["asset"]["token_contract"] or "native")},
 {_e(seed["asset"]["decimals"])} decimals)</dd>
<dt>Case-flow linkage</dt><dd>{_e(scope["case_flow_linkage"])}</dd>
</dl>

<h2>Analysis scope</h2>
<dl>
<dt>Data mode</dt><dd>{_e(scope["data_mode"])}</dd>
<dt>Analysis cutoff</dt><dd>{_e(scope["analysis_cutoff"])}</dd>
<dt>Run window</dt><dd>{_e(scope["started_at"])} → {_e(scope["finished_at"])}</dd>
<dt>Coverage</dt><dd>{_e(scope["coverage_status"])}</dd>
 <dt>Budget use</dt><dd>{_e(budget.get("hops_used", 0))}/{_e(budget.get("hop_limit", 0))} hops ·
 {_e(budget.get("events_examined", 0))}/{_e(budget.get("event_limit", 0))} events ·
 {_e(traversal_requests)}/{_e(traversal_limit)} traversal requests ·
 {_e(budget.get("elapsed_seconds", 0))}s</dd>
</dl>
<p class="note">Traversal requests count only the tracer's own forward-walk
pages, not the seed-event search, enrichment, or receipt verification a live
run also performs. Recorded acquisition details, when available, are in the evidence JSON.
An absent total request count must not be interpreted as zero acquisition calls.</p>
<p class="note">Coverage is complete <em>within the declared scope</em> — this network,
this asset, this time window, these budgets. It never means complete knowledge of
the blockchain.</p>

<h2>Observed transfers</h2>
{
        _rows(
            ["Hop", "Block time (UTC)", "From", "To", "Amount", "Event reference", "Status"],
            transfer_rows,
            empty="No onward transfer of this asset was observed within the analysed scope.",
        )
    }
<p class="note">Hop 0 is the seed transfer that links the case to the path; it is
shown from the run's own saved event, not re-derived. Later rows are onward
transfers observed within the analysed scope.</p>

<h2>Branch endings</h2>
{
        _rows(
            ["Address", "Endpoint", "Entity", "Observed amount", "Case amount", "Boundary", "Hop"],
            ending_rows,
            empty="No branches recorded.",
        )
    }
<p class="note">A <strong>known_service</strong> ending is supported by a reviewed,
in-date service-control assertion. A <strong>deposit_candidate</strong> is a lead:
it is shown, and tracing continues past it. Neither identifies a person.</p>

<h2>Label provenance</h2>
{
        _rows(
            [
                "Entity",
                "Address",
                "Source",
                "Retrieved",
                "Methodology",
                "Validity",
                "Last verified",
                "Accepted by",
                "Source hash",
            ],
            label_rows,
            empty="No entity attribution was made.",
        )
    }
<p class="note">Every claim above is reproduced from the label set as it stood at
{_e(scope["started_at"])}, not read from today's files. The source hash identifies the
document the claim came from; the accepting reviewer and the decision date identify the
row in <code>review_log.csv</code>.</p>

<h3>Label sets read</h3>
{
        _rows(
            ["File", "Claims loaded", "Withdrawn by review", "SHA-256"],
            label_file_rows,
            empty=f"Label source: {_e(snapshot.get('source', 'unspecified'))}.",
        )
    }
<p class="note">Label source <strong>{_e(snapshot.get("source", "unspecified"))}</strong>,
{_e(snapshot.get("accepted_service_claims", 0))} accepted service claim(s) available to this
run. A withdrawn row is one a reviewer rejected or quarantined; it was not loaded.</p>

<h2>Limitations and unresolved items</h2>
{
        _rows(
            ["Code", "Detail", "Address", "Event"],
            limitation_rows,
            empty="No limitations were recorded for this run.",
        )
    }

<div class="caveat">
<strong>Read this before relying on the page above.</strong><br>
{_e(result["disclaimer"])}<br><br>
Observed transfer amounts are what the chain shows. A case-associated amount is a
separate question and defaults to <code>allocation_unknown</code>: an address holding
pre-existing funds mixes them, and a later outgoing transfer cannot be assumed to
consist of the funds under investigation.<br><br>
This document is investigative material for human review. It is not a legal
instrument, it establishes no authority to restrict any account, and it has not
been checked by anyone merely because it was generated.
</div>
</body></html>"""
