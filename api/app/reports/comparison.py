"""Printable HTML for the Stage 2 four-level evidence-comparison report.

Pure rendering over an already-built ComparisonReport: no computation, no
wall-clock read, no network. Prints from any browser to PDF, matching the
Stage 1 evidence report's approach in app/reports/evidence.py.
"""

from __future__ import annotations

import html
from typing import Any

from app.services.evidence_comparison import ComparisonReport
from app.services.service_outcome import ServiceOutcome

STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 13px/1.5 ui-monospace, "SFMono-Regular", Menlo, monospace;
       color: #1b1d21; background: #fff; margin: 0; padding: 24px; }
h1 { font-size: 17px; margin: 0 0 2px; }
h2 { font-size: 14px; margin: 26px 0 8px; }
h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em;
     color: #5a5e66; margin: 14px 0 4px; }
ul { margin: 4px 0; padding-left: 20px; }
li { margin: 2px 0; word-break: break-word; }
.level { border: 1px solid #d6d8dc; padding: 12px 14px; margin: 14px 0; }
.badge { display: inline-block; padding: 2px 8px; border: 1px solid currentColor;
         font-size: 11px; letter-spacing: .04em; margin-left: 8px; }
.complete { color: #3f5747; }
.truncated { color: #6a5c3f; }
.not_collected, .not_applicable { color: #5a5e66; }
.mono { font-size: 12px; color: #5a5e66; word-break: break-all; }
.caveat { border: 1px solid #1b1d21; padding: 10px 12px; margin-top: 22px; font-size: 12px; }
@media print { body { padding: 0; } .level { break-inside: avoid; } }
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _list(items: tuple[str, ...], *, empty: str) -> str:
    if not items:
        return f"<p class='mono'>{_e(empty)}</p>"
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"


def render_service_outcome_html(outcome: ServiceOutcome) -> str:
    """Render one Stage 3A ServiceOutcome as escaped, printable HTML. This is
    the same data as ``outcome.to_dict()`` -- JSON and HTML never disagree
    because both are produced from the same ServiceOutcome record and this
    function performs no computation, only escaping."""
    d = outcome.to_dict()
    evidence_items = "".join(
        f"<li>{_e(r['kind'])}: {_e(r['evidence_id'])}</li>" for r in d["evidence_references"]
    )
    return f"""<div class="level">
<h2>service outcome
<span class="badge">{_e(d['category'])}</span></h2>
<p class="mono">claim {_e(d['claim_id'])} &middot; service {_e(d['service_name'])}
&middot; policy_version {_e(d['policy_version'])}</p>

<h3>Reason codes</h3>
{_list(tuple(d['reason_codes']), empty='none')}

<h3>Evidence references</h3>
{'<ul>' + evidence_items + '</ul>' if evidence_items else "<p class='mono'>none</p>"}

<h3>Unresolved / limitations</h3>
{_list(tuple(d['unresolved']), empty='none recorded')}

<h3>Temporal scope</h3>
<p class="mono">{_e(d['window_start'] or '—')} &rarr; {_e(d['window_end'] or '—')}</p>

<h3>Existing status axes (copied through, unmodified)</h3>
<ul>
<li>execution_status: {_e(d['execution_status'])}</li>
<li>coverage_status: {_e(d['coverage_status'])}</li>
<li>attribution_status: {_e(d['attribution_status'])}</li>
<li>case_flow_linkage: {_e(d['case_flow_linkage'])}</li>
<li>acquisition_completeness: {_e(d['acquisition_completeness'])}</li>
<li>verification_quality: {_e(d['verification_quality'])}</li>
<li>event_identity_quality: {_e(d['event_identity_quality'])}</li>
<li>ordering_quality: {_e(d['ordering_quality'])}</li>
</ul>
</div>"""


def render_comparison_html(
    report: ComparisonReport, outcomes: tuple[ServiceOutcome, ...] = ()
) -> str:
    level_blocks = []
    for level in report.levels:
        level_blocks.append(
            f"""<div class="level">
<h2>{_e(level.level)}
<span class="badge {_e(level.completeness_status)}">{_e(level.completeness_status)}</span></h2>

<h3>Observed evidence</h3>
{_list(level.observed_evidence, empty="none on record at this level")}

<h3>Supported conclusion</h3>
<p>{_e(level.supported_conclusion)}</p>

<h3>Unresolved / unknown</h3>
{_list(level.unresolved, empty="none recorded")}

<h3>Additional signals introduced at this level</h3>
{_list(level.additional_signals, empty="none")}

<h3>Temporal scope</h3>
<p class="mono">{_e(level.temporal_scope_start or "—")}
 &rarr; {_e(level.temporal_scope_end or "—")}</p>

<h3>Completeness notes</h3>
{_list(level.completeness_notes, empty="none recorded")}

<h3>Source evidence IDs</h3>
{_list(level.source_evidence_ids, empty="none")}
</div>"""
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Evidence comparison — {_e(report.candidate_address)}</title>
<style>{STYLE}</style></head><body>
<h1>Stage 2 evidence-comparison report</h1>
<p class="mono">Candidate {_e(report.candidate_address)}
 &middot; status: {_e(report.candidate_status)}</p>

{"".join(level_blocks)}

{"".join(render_service_outcome_html(o) for o in outcomes)}

<div class="caveat">
<strong>Read this before relying on the page above.</strong>
{_list(report.caveats, empty="")}
This document is investigative material for human review. It establishes no
authority to restrict any account and has not been checked by anyone merely
because it was generated.
</div>
</body></html>"""
