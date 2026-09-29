"""Stage 4: printable rendering of a legal-process request draft.

Reuses ``app.reports.evidence``'s stylesheet and escaping helper so a request
draft looks like part of the same document family as the evidence report,
rather than a second, inconsistent template. Every value is escaped; nothing
here is a legal instrument.
"""

from __future__ import annotations

import html
from typing import Any

from app.reports.evidence import STYLE

#: Duplicated from evidence.py rather than importing its private (`_`-
#: prefixed) helpers across a module boundary; both are a few lines.


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _rows(headers: list[str], rows: list[list[str]], *, empty: str) -> str:
    if not rows:
        return f'<p class="empty">{_e(empty)}</p>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(cells) + "</tr>" for cells in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


_STATUS_LABELS = {
    "drafted": "DRAFT",
    "refused": "REFUSED -- NOT DRAFTED",
}


def render_request_draft_html(draft: dict[str, Any], *, request_id: str = "") -> str:
    status = draft["status"]
    mode_class = "mode" if status == "drafted" else "mode flag-banner"
    status_line = f"{_e(_STATUS_LABELS.get(status, status))} · {_e(draft['request_kind'])}"
    target = draft["target"]
    checklist_rows = [
        [
            f"<td>{_e(f['label'])}</td>",
            f"<td><span class='note'>[{_e(f['required_by'])}]</span> {_e(f['value'])}</td>",
            f"<td>{'yes' if f['provided'] else 'NO'}</td>",
        ]
        for f in draft["checklist"]
    ]

    refusal_block = ""
    if draft["refusal_reason"]:
        refusal_block = (
            "<div class='caveat'><strong>This draft was refused.</strong><br>"
            f"{_e(draft['refusal_reason'])}</div>"
        )

    tx_hashes = draft["identifiers"].get("observed_transaction_hashes", [])
    tx_rows = [[f"<td>{_e(h)}</td>"] for h in tx_hashes]

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Request draft -- {_e(draft['request_kind'])} -- {_e(target['address'])}</title>
<style>{STYLE}
.flag-banner {{ border-color: #7c4444; background: #f3e6e6; color: #7c4444; }}
</style></head><body>
<div class="{mode_class}">{status_line}</div>
<h1>Legal-process request draft</h1>
<p class="note">Generated {_e(draft['generated_at'])} · request {_e(request_id)}</p>

<div class="caveat">{_e(draft['draft_marker'])}</div>

{refusal_block}

<h2>Target</h2>
<dl>
<dt>Address</dt><dd>{_e(target['address'])}</dd>
<dt>Network</dt><dd>{_e(target['network_key'])}</dd>
<dt>Endpoint class</dt><dd>{_e(target['endpoint_class'])}</dd>
<dt>Attribution status</dt><dd>{_e(target['attribution_status'])}</dd>
<dt>Entity name</dt><dd>{_e(target['entity_name'] or 'no label')}</dd>
<dt>Address role</dt><dd>{_e(target['address_role'] or 'not established')}</dd>
<dt>Label review state</dt><dd>{_e(target['review_state'] or 'n/a')}</dd>
</dl>

<h2>Checklist</h2>
{
        _rows(
            ["Field", "Value", "Provided"],
            checklist_rows,
            empty="No checklist fields.",
        )
    }
<p class="note">Checklist reproduced from {_e(draft['checklist_source']['provider'])}'s own
published guide: {_e(draft['checklist_source']['source_reference'])}
(retrieved {_e(draft['checklist_source']['retrieved_at'])}).
{_e(draft['checklist_source']['submission_channel'])}</p>

<h2>Observed transaction identifiers</h2>
{
        _rows(
            ["Transaction hash"],
            tx_rows,
            empty="No transaction hashes recorded on this trace.",
        )
    }

<div class="caveat">
<strong>Read this before using the page above.</strong><br>
This tool creates no legal authority, sends nothing, and was not signed or
authorised by any officer. A human investigator must review every field above,
supply the missing legal-authority reference, and submit through the
provider's own channel after independent legal review.
</div>
</body></html>"""
