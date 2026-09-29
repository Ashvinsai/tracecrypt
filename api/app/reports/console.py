"""Server-rendered investigator console (local prototype).

One screen that reads already-saved trace/outcome/comparison artifacts and
presents the service outcome, the eight independent status axes, the
chronological transfers, a simple deterministic path, provenance, and the
known limitations -- without a model, a network call, or a database.

Rendering only: every value printed comes from the loaded saved artifact. The
functions here do not recompute an attribution and do not turn an error into
an empty success. Where a value is absent, the page says so.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import Any

from app.reports.fund_flow import (
    GRAPH_SCRIPT,
    GRAPH_STYLE,
    build_fund_flow,
    render_fund_flow_body,
)
from app.services.demo_presets import DemoView, Preset

MODE_LABELS = {
    "LIVE": "LIVE",
    "RECORDED_PUBLIC": "RECORDED PUBLIC",
    "SYNTHETIC": "SYNTHETIC",
}

CATEGORY_LABELS = {
    "supported_destination": "Supported destination",
    "strong_inference": "Strong inference (uncalibrated policy)",
    "candidate_lead": "Candidate lead",
    "unknown_or_blocked": "Unknown / blocked",
}

#: Category -> CSS modifier for the result card's left accent.
RESULT_CSS = {
    "supported_destination": "supported",
    "strong_inference": "strong_inference",
    "candidate_lead": "candidate_lead",
    "unknown_or_blocked": "unknown_or_blocked",
}

STATUS_AXES = (
    "execution_status",
    "coverage_status",
    "attribution_status",
    "case_flow_linkage",
    "acquisition_completeness",
    "verification_quality",
    "event_identity_quality",
    "ordering_quality",
)

#: The same eight independent axes, grouped for display only. Grouping never
#: merges them; each value is still shown verbatim and none becomes one score.
AXIS_GROUPS = (
    (
        "Observation quality",
        (
            "execution_status",
            "acquisition_completeness",
            "verification_quality",
            "event_identity_quality",
            "ordering_quality",
        ),
    ),
    ("Attribution", ("attribution_status",)),
    ("Case linkage", ("case_flow_linkage",)),
    ("Coverage", ("coverage_status",)),
)

STYLE = """
:root {
  color-scheme: light;
  --accent: #2563eb;
  --accent-ink: #ffffff;
  --ink: #14181d;
  --muted: #646c78;
  --line: #e2e6ec;
  --line-strong: #c4cad4;
  --panel: #ffffff;
  --bg: #f6f7f9;
  --surface-2: #f1f3f6;
  --head: #eceff3;
  --zebra: #fafbfd;
  --seed-bg: #eaf1ff;
  --green: #1f7a4d;
  --green-bg: #e4f3ea;
  --amber: #8a6410;
  --amber-bg: #f7efd8;
  --grey: #5a626e;
  --grey-bg: #eaecef;
  --red: #b23838;
  --red-bg: #f8e8e8;
  --shadow: 0 1px 2px rgba(16, 24, 40, .06), 0 1px 3px rgba(16, 24, 40, .04);
  --ring: rgba(37, 99, 235, .22);
  --ring-boundary: rgba(138, 100, 16, .24);
  /* Contour tint for the topographic background. */
  --topo: rgba(21, 43, 84, .055);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background-color: var(--bg);
  /* Contour-map texture, built from repeating radial gradients so the page
     carries no external image or script. Purely decorative: every contour
     sits behind opaque panels and is excluded from print and reduced motion. */
  background-image:
    repeating-radial-gradient(circle at 14% 12%, transparent 0 30px, var(--topo) 30px 31px),
    repeating-radial-gradient(circle at 87% 9%, transparent 0 34px, var(--topo) 34px 35px),
    repeating-radial-gradient(circle at 78% 84%, transparent 0 42px, var(--topo) 42px 43px),
    repeating-radial-gradient(circle at 22% 82%, transparent 0 38px, var(--topo) 38px 39px);
  background-attachment: fixed;
  color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
h1, h2, h3 { line-height: 1.25; }
a { color: var(--accent); }
a:focus-visible, button:focus-visible, input:focus-visible, summary:focus-visible,
[tabindex]:focus-visible {
  outline: 3px solid var(--accent); outline-offset: 2px; border-radius: 2px;
}
code, .mono, .addr { font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; }
.addr { font-size: 12.5px; overflow-wrap: anywhere; }
.claim { overflow-wrap: anywhere; }

.skip-link {
  position: absolute; left: -9999px; top: 0; z-index: 50;
  background: var(--ink); color: var(--panel); padding: 8px 12px;
  border-radius: 0 0 6px 0; font-size: 13px;
}
.skip-link:focus { left: 0; }

.topbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
  padding: 12px 20px; background: #0d0f12; color: #e9eaec;
  border-bottom: 1px solid #20242a;
  box-shadow: 0 1px 0 rgba(255, 255, 255, .03) inset;
}
.topbar h1 { font-size: 16px; margin: 0; letter-spacing: .01em; }
.topbar .spacer { flex: 1; }
.chip {
  display: inline-block; padding: 2px 9px; border-radius: 999px;
  border: 1px solid var(--line-strong); font-size: 11.5px; font-weight: 600;
  letter-spacing: .03em; white-space: nowrap; background: var(--grey-bg);
  color: var(--grey);
}
.topbar .chip { border-color: #4b515a; color: #c3c8cf; background: transparent; }
.chip.mode-LIVE {
  color: var(--green); background: var(--green-bg); border-color: var(--green); }
.chip.mode-RECORDED_PUBLIC {
  color: var(--amber); background: var(--amber-bg); border-color: var(--amber); }
.chip.mode-SYNTHETIC {
  color: var(--grey); background: var(--grey-bg); border-color: var(--line-strong); }
.chip.ep-known_service, .chip.ep-supported {
  color: var(--green); background: var(--green-bg); border-color: var(--green); }
.chip.ep-deposit_candidate, .chip.ep-candidate {
  color: var(--amber); background: var(--amber-bg); border-color: var(--amber); }
.chip.ep-unresolved, .chip.ep-boundary {
  color: var(--grey); background: var(--grey-bg); border-color: var(--line-strong); }
.chip.warn { color: var(--red); border-color: var(--red); background: var(--red-bg); }
.chip.st-available { color: var(--green); background: var(--green-bg); border-color: var(--green); }
.chip.st-partial { color: var(--amber); background: var(--amber-bg); border-color: var(--amber); }
.chip.st-not_built, .chip.st-not_configured { color: var(--grey); background: var(--grey-bg); }
.chip.st-blocked { color: var(--red); border-color: var(--red); background: var(--red-bg); }

.theme-toggle { background: transparent; border: 1px solid #4b515a; color: #c3c8cf;
  cursor: pointer; font: inherit; font-size: 11.5px; font-weight: 600;
  padding: 2px 9px; border-radius: 999px; }
.theme-toggle:hover { color: #fff; border-color: #9aa0aa; }
.sitenav { display: flex; flex-wrap: wrap; gap: 12px; margin-left: 4px; }
.sitenav a { color: #c3c8cf; text-decoration: none; font-size: 13px; font-weight: 600;
  padding: 2px 1px; border-bottom: 2px solid transparent; }
.sitenav a:hover { color: #fff; }
.sitenav a.active { color: #fff; border-bottom-color: #9aa0aa; }

.wrap { max-width: 1180px; margin: 0 auto; padding: 14px 20px 48px; }
.lede { color: var(--muted); font-size: 12.5px; margin: 0 0 12px; max-width: 96ch; }
.grid { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 16px; align-items: start; }
/* Grid items default to min-width:auto, which lets a wide table or a long
   token blow the track (and the whole page) open. Force them to shrink so the
   inner scroll containers and wraps do their job instead. */
.grid > * { min-width: 0; }
@media (max-width: 920px) {
  .grid { grid-template-columns: minmax(0, 1fr); }
  /* Single column: the investigation result comes first; inputs and demo
     examples follow, so a narrow screen is not a wall of sidebar. */
  .grid > aside { order: 2; }
  .grid > main { order: 1; }
}

section.card, .card {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 12px; padding: 16px 18px; margin-bottom: 12px;
  box-shadow: var(--shadow);
}
.card h2, .section-head h2, .section-h {
  font-size: 11.5px; text-transform: uppercase; letter-spacing: .09em;
  color: var(--muted); margin: 0 0 12px; border-bottom: 1px solid var(--line);
  padding-bottom: 7px;
}
.section-h { margin: 24px 0 10px; }
.card h3 { font-size: 13px; margin: 14px 0 6px; }
.card p { margin: 6px 0; }
.note { color: var(--muted); font-size: 12.5px; }
.empty { color: var(--muted); font-style: italic; }

label, .flabel { display: block; font-size: 12.5px; color: var(--muted); margin: 10px 0 3px; }
input[type=text] {
  width: 100%; padding: 8px 10px; border: 1px solid var(--line);
  border-radius: 6px; font: inherit; font-size: 13px; background: #fff; color: var(--ink);
}
.field-static {
  font-family: ui-monospace, Menlo, monospace; font-size: 12.5px;
  padding: 7px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 6px; word-break: break-all;
}
button, .btn {
  display: inline-block; padding: 8px 15px; border-radius: 8px;
  border: 1px solid var(--accent); background: var(--accent); color: var(--accent-ink);
  font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
  text-decoration: none;
}
button:hover, .btn:hover { filter: brightness(1.05); }
button.secondary, .btn.secondary {
  background: var(--panel); color: var(--ink); border-color: var(--line-strong);
}
button.copy {
  padding: 1px 7px; font-size: 11px; font-weight: 600; margin-left: 6px;
  background: var(--panel); color: var(--muted); border: 1px solid var(--line);
  cursor: pointer; vertical-align: middle;
}
button.copy.copied { color: var(--green); border-color: var(--green); }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.print-full { display: none; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.actions-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.actions-row .btn { font-size: 12.5px; padding: 7px 12px; }

.preset { display: block; border: 1px solid var(--line); border-radius: 8px;
  padding: 10px 12px; margin: 8px 0; text-decoration: none; color: var(--ink);
  background: var(--surface-2); }
.preset:hover { border-color: var(--accent); }
.preset.current { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.preset .ptitle { font-weight: 600; font-size: 13.5px; }
.preset .pdesc { color: var(--muted); font-size: 12.5px; margin-top: 4px; }

/* ---- primary result card ---- */
.result-card { border-left: 5px solid var(--grey); }
.result-card.supported { border-left-color: var(--green); }
.result-card.strong_inference, .result-card.candidate_lead { border-left-color: var(--amber); }
.result-card.unknown_or_blocked { border-left-color: var(--grey); }
.result-headline { font-size: 20px; font-weight: 700; margin: 0 0 3px;
  letter-spacing: -.01em; }
.result-line { color: var(--ink); font-size: 13.5px; margin: 4px 0; }
.result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 8px 16px; margin: 9px 0 2px; }
.result-fact .rk { display: block; font-size: 10.5px; text-transform: uppercase;
  letter-spacing: .05em; color: var(--muted); }
.result-fact .rv { display: block; font-size: 13px; font-weight: 600;
  word-break: break-word; }
.result-fact .rv .addr { font-weight: 500; }
.result-limit { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--line);
  font-size: 12.5px; }
.result-limit .rk { display: block; font-size: 10.5px; text-transform: uppercase;
  letter-spacing: .05em; color: var(--muted); margin-bottom: 2px; }

/* ---- tables ---- */
table { width: 100%; border-collapse: collapse; margin: 4px 0; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line);
  vertical-align: top; }
th { font-size: 10.5px; text-transform: uppercase; letter-spacing: .05em;
  color: var(--muted); position: sticky; top: 0; background: var(--head); z-index: 1; }
tbody tr:nth-child(even) { background: var(--zebra); }
tbody tr.selected { background: var(--seed-bg); }
tbody tr.selected td:first-child { box-shadow: inset 3px 0 0 var(--accent); }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.table-scroll { max-height: 460px; max-width: 100%; min-width: 0; overflow: auto;
  border: 1px solid var(--line); border-radius: 8px; }
.flag { color: var(--red); font-weight: 600; }
.row-locator { padding: 1px 7px; font-size: 11.5px; font-weight: 600;
  background: var(--panel); color: var(--muted); border: 1px solid var(--line);
  cursor: pointer; border-radius: 5px; }

dl.axes { display: grid; grid-template-columns: max-content minmax(0, 1fr);
  gap: 5px 16px; margin: 0; }
dl.axes dt { color: var(--muted); font-family: ui-monospace, Menlo, monospace;
  font-size: 12px; }
dl.axes dd { margin: 0; }
.axes-group { margin: 0 0 10px; }
.axes-group:last-child { margin-bottom: 0; }
.axes-group h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
  color: var(--muted); margin: 0 0 4px; font-weight: 600; }
dl.kv { display: grid; grid-template-columns: max-content minmax(0, 1fr);
  gap: 5px 16px; margin: 0; font-size: 13px; }
dl.kv dt { color: var(--muted); }
dl.kv dd { margin: 0; word-break: break-word; overflow-wrap: anywhere; }

/* ---- path ---- */
.path-list { margin-top: 4px; }
.path-row { border-top: 1px solid var(--line); padding: 9px 0; }
.path-row:first-of-type { border-top: 0; padding-top: 0; }
.path-head { font-size: 11.5px; color: var(--muted); margin-bottom: 5px;
  display: flex; flex-wrap: wrap; gap: 3px 10px; align-items: baseline; }
.path-head .bnum { color: var(--ink); font-weight: 600; }
.path-track { display: flex; flex-wrap: wrap; align-items: center; gap: 5px 7px;
  min-width: 0; }
.node { border: 1px solid var(--line-strong); border-radius: 8px; padding: 5px 9px;
  font-size: 12px; background: var(--panel); min-width: 0; max-width: 236px;
  transition: box-shadow .15s ease, border-color .15s ease; }
.node .nlabel { display: block; font-weight: 600; font-size: 11.5px;
  margin-bottom: 1px; }
.node .addr { display: block; word-break: break-all; overflow-wrap: anywhere; }
.node .nmeta, .node .ets { display: block; font-size: 10.5px; color: var(--muted);
  margin-top: 2px; }
.node .chip { display: inline-block; margin-top: 3px; font-size: 10.5px; padding: 1px 7px; }
.node.seed { border-color: var(--accent); background: var(--seed-bg); }
.node.known_service, .node.supported { border-color: var(--green); background: var(--green-bg); }
.node.deposit_candidate { border-color: var(--amber); background: var(--amber-bg); }
.node.unresolved, .node.boundary { border-color: var(--line-strong); background: var(--grey-bg); }
.edge { color: var(--muted); font-size: 11px; font-family: ui-monospace, Menlo, monospace;
  text-align: center; display: inline-flex; flex-direction: column; gap: 1px;
  max-width: 132px; min-width: 0; overflow-wrap: anywhere; }
.edge .amt { color: var(--ink); font-weight: 600; overflow-wrap: anywhere; }
.edge .amt .sym { white-space: nowrap; }
.edge .ets { font-size: 10px; color: var(--muted); }
.edge .eev { font-size: 10px; color: var(--muted); overflow-wrap: anywhere; }
.arrow { color: var(--line-strong); font-weight: 700; }
/* Selection: path node and its timeline row share one subtle accent treatment. */
.js-path-node.sel, .js-path-node.lit { border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--ring); }
.js-path-node.lit-boundary { box-shadow: 0 0 0 2px var(--ring-boundary); }
.js-path-node.pulse { animation: pop .32s ease; }
@keyframes pop {
  0% { transform: scale(1); } 50% { transform: scale(1.04); } 100% { transform: scale(1); }
}
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 8px 0 4px;
  font-size: 12px; color: var(--muted); align-items: center; }
.legend .k { display: inline-flex; align-items: center; gap: 5px; }
.legend .swatch {
  width: 12px; height: 12px; border-radius: 3px; border: 1px solid var(--line-strong); }
.swatch.seed { background: var(--seed-bg); border-color: var(--accent); }
.swatch.known_service { background: var(--green-bg); border-color: var(--green); }
.swatch.deposit_candidate { background: var(--amber-bg); border-color: var(--amber); }
.swatch.unresolved { background: var(--grey-bg); border-color: var(--line-strong); }
.replay-controls {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 10px; }
.replay-caption { font-size: 12.5px; color: var(--muted); min-height: 1.3em; margin-top: 8px; }
.replay-caption b { color: var(--ink); }

/* ---- evidence layers drawer ---- */
details.layers { margin: 12px 0 0; border-top: 1px solid var(--line); padding-top: 8px; }
details > summary { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--accent); }
details pre { background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px;
  padding: 10px; font-size: 12px; overflow: auto; white-space: pre-wrap;
  word-break: break-word; }

/* ---- tabs ---- */
.tabs { margin-top: 4px; }
.tablist { display: inline-flex; flex-wrap: wrap; gap: 2px; padding: 3px;
  background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; }
.tab {
  background: transparent; color: var(--muted); border: 0; border-radius: 6px;
  padding: 6px 12px; font-size: 13px; font-weight: 600; cursor: pointer;
}
.tab[aria-selected="true"] { background: var(--panel); color: var(--ink);
  box-shadow: var(--shadow); }
.tabpanel { margin-top: 12px; }
.tabpanel[hidden] { display: none; }

ul.tight { margin: 6px 0; padding-left: 20px; }
ul.tight li { margin: 3px 0; overflow-wrap: anywhere; }

.caveat { border: 1px solid var(--line-strong); border-radius: 8px; padding: 12px 14px;
  font-size: 12.5px; background: var(--surface-2); margin-top: 8px; }
.no-model { font-weight: 700; color: var(--red); }
.readiness-status { font-weight: 700; }
.print-only { display: none; }
.footer { color: var(--muted); font-size: 12px; margin-top: 28px;
  border-top: 1px solid var(--line); padding-top: 12px; }

/* ---- how-it-works walkthrough ---- */
.walk-steps { list-style: none; margin: 10px 0; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
.walk-step { position: relative; border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 10px; background: var(--surface-2);
  transition: opacity .3s ease, border-color .3s ease; }
.walk-step .wnum { display: inline-block; width: 18px; height: 18px; border-radius: 50%;
  background: var(--line); color: var(--ink); font-size: 11px; font-weight: 700;
  text-align: center; line-height: 18px; margin-right: 6px; }
.walk-step .wt { font-weight: 600; font-size: 12.5px; }
.walk-step .wd { color: var(--muted); font-size: 11.5px; margin-top: 3px; }
.walk-steps.dim .walk-step { opacity: .45; }
.walk-step.active { opacity: 1; border-color: var(--accent); }
.walk-step.done { opacity: 1; border-color: var(--green); }
.walk-step.done .wnum { background: var(--green); color: #fff; }
.walk-step.result { grid-column: 1 / -1; background: var(--panel); }
.walk-steps.dim .walk-step.active, .walk-steps.dim .walk-step.done { opacity: 1; }
.walk-controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 6px; }
.walk-dots { display: inline-flex; gap: 5px; margin-left: 4px; }
.walk-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line); }
.walk-dot.on { background: var(--accent); }
.walk-caption { margin-top: 8px; font-size: 12.5px; color: var(--muted); min-height: 1.3em; }
.walk-caption b { color: var(--ink); }

/* ---- landing ---- */
.hero { padding: 26px 0 8px; }
.hero h2 { font-size: 29px; margin: 0 0 10px; letter-spacing: -.02em; }
.hero p { font-size: 15.5px; color: var(--muted); max-width: 72ch; }
.cta-row { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 4px; }
.feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 14px; margin-top: 6px; }
.feature { border: 1px solid var(--line); border-radius: 10px; padding: 15px 17px;
  background: var(--panel); transition: border-color .15s ease, transform .15s ease; }
.feature:hover { border-color: var(--line-strong); transform: translateY(-1px); }
.feature h3 { margin: 0 0 6px; font-size: 14px; }
.feature p { margin: 0; color: var(--muted); font-size: 13px; }
.notlist { list-style: none; margin: 6px 0; padding: 0; }
.notlist li { padding: 5px 0 5px 22px; position: relative; font-size: 13.5px; }
.notlist li::before { content: "✕"; position: absolute; left: 0; color: var(--red);
  font-weight: 700; }

/* ---- dashboard ---- */
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin: 10px 0; }
.tile { border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px;
  background: var(--panel); }
.tile .big { font-size: 26px; font-weight: 700; line-height: 1.15;
  letter-spacing: -.02em; }
.tile .lbl { color: var(--muted); font-size: 11px; text-transform: uppercase;
  letter-spacing: .07em; }
.mode-key { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 12px; }

/* ---- automatic dark mode ---- */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --accent: #7fb0ff; --accent-ink: #0a0d11;
    --ink: #e7eaee; --muted: #98a1ab; --line: #262b31; --line-strong: #3b414a;
    --panel: #14171b; --bg: #0a0c0f; --surface-2: #1a1f24;
    --green: #86cfa5; --green-bg: #11241a; --amber: #e0c078;
    --amber-bg: #2a2211; --grey: #9aa3ad; --grey-bg: #1d2126;
    --red: #e09a9a; --red-bg: #2b191b; --seed-bg: #172232;
    --head: #171a1f; --zebra: #0e1114; --shadow: none;
    --ring: rgba(127, 176, 255, .30); --ring-boundary: rgba(224, 192, 120, .28);
    --topo: rgba(255, 255, 255, .04);
  }
  :root:not([data-theme="light"]) .skip-link { background: #e6e7e8; color: #141516; }
  :root:not([data-theme="light"]) input[type=text] { background: var(--panel); color: var(--ink); }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --accent: #7fb0ff; --accent-ink: #0a0d11;
  --ink: #e7eaee; --muted: #98a1ab; --line: #262b31; --line-strong: #3b414a;
  --panel: #14171b; --bg: #0a0c0f; --surface-2: #1a1f24;
  --green: #86cfa5; --green-bg: #11241a; --amber: #e0c078;
  --amber-bg: #2a2211; --grey: #9aa3ad; --grey-bg: #1d2126;
  --red: #e09a9a; --red-bg: #2b191b; --seed-bg: #172232;
  --head: #171a1f; --zebra: #0e1114; --shadow: none;
  --ring: rgba(127, 176, 255, .30); --ring-boundary: rgba(224, 192, 120, .28);
  --topo: rgba(255, 255, 255, .04);
}
:root[data-theme="dark"] .skip-link { background: #e6e7e8; color: #141516; }
:root[data-theme="dark"] input[type=text] { background: var(--panel); color: var(--ink); }
:root[data-theme="light"] { color-scheme: light; }

@media (max-width: 700px) {
  .wrap { padding: 12px 14px 44px; }
  .topbar { padding: 10px 14px; }
  .path-track { flex-direction: column; align-items: stretch; gap: 4px; }
  .path-track .arrow { transform: rotate(90deg); align-self: center; }
  .path-track .edge { text-align: left; align-items: flex-start; max-width: none; }
  .node { max-width: 100%; }
  .result-headline { font-size: 17px; }
  .tablist { display: flex; width: 100%; }
  .tab { flex: 1 1 auto; text-align: center; }
}

@media print {
  body { background: #fff; }
  .topbar { background: #fff; color: #000; border-bottom: 2px solid #000; }
  .topbar .chip, .topbar .theme-toggle { border-color: #000; color: #000; }
  .sitenav, .no-print { display: none !important; }
  .card, .result-card { break-inside: avoid; box-shadow: none; }
  .print-only { display: block; margin-bottom: 10px; font-weight: 600; }
  .wrap { max-width: none; padding: 0; }
  .tabpanel[hidden] { display: block !important; }
  .tablist { display: none; }
  a[href]::after { content: " (" attr(href) ")"; font-size: 11px; color: #333; }
  /* Screen-only controls and live status have no meaning on paper. */
  .replay-caption, .theme-toggle, #health { display: none !important; }
  /* Keep print independent of any on-screen JS selection/animation state. */
  .js-path-node.sel, .js-path-node.lit, .js-path-node.lit-boundary {
    box-shadow: none !important; }
  tbody tr.selected { background: transparent !important; }
  tbody tr.selected td:first-child { box-shadow: none !important; }
  .node { max-width: none; }
  .addr { word-break: break-all; }
  .print-full { display: inline; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
"""

#: Applied in <head> before paint so a chosen theme never flashes the OS one.
_THEME_INIT = (
    "(function(){try{var t=localStorage.getItem('cfa-theme');"
    "if(t==='light'||t==='dark'){document.documentElement.setAttribute('data-theme',t);}"
    "}catch(e){}})();"
)

_SCRIPT = """
(function () {
  // Theme: Auto -> Light -> Dark, remembered locally.
  var root = document.documentElement;
  function themeLabel(mode) { return "Theme: " + mode.charAt(0).toUpperCase() + mode.slice(1); }
  function applyTheme(mode) {
    if (mode === "light" || mode === "dark") { root.setAttribute("data-theme", mode); }
    else { root.removeAttribute("data-theme"); }
    try { localStorage.setItem("cfa-theme", mode); } catch (e) {}
    document.querySelectorAll(".theme-toggle").forEach(function (btn) {
      btn.textContent = themeLabel(mode);
      btn.setAttribute("aria-label", themeLabel(mode) + ". Click to change.");
    });
  }
  function currentTheme() {
    try { return localStorage.getItem("cfa-theme") || "auto"; } catch (e) { return "auto"; }
  }
  applyTheme(currentTheme());
  document.querySelectorAll(".theme-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var order = ["auto", "light", "dark"];
      var next = order[(order.indexOf(currentTheme()) + 1) % order.length];
      applyTheme(next);
    });
  });

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return Promise.reject(new Error("clipboard unavailable"));
  }
  var copyStatus = document.getElementById("copy-status");
  document.querySelectorAll("button.copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var value = btn.getAttribute("data-copy") || "";
      var what = btn.getAttribute("data-label") || "value";
      copyText(value).then(function () {
        btn.textContent = "Copied";
        btn.classList.add("copied");
        if (copyStatus) { copyStatus.textContent = "Copied " + what + " to the clipboard."; }
        setTimeout(function () {
          btn.textContent = "copy";
          btn.classList.remove("copied");
        }, 1400);
      }).catch(function () {
        btn.textContent = "copy failed";
        if (copyStatus) { copyStatus.textContent = "Could not copy " + what + "."; }
      });
    });
  });
  document.querySelectorAll("button.print").forEach(function (btn) {
    btn.addEventListener("click", function () { window.print(); });
  });
  var health = document.getElementById("health");
  if (health) {
    fetch("/healthz").then(function (r) { return r.json(); }).then(function (d) {
      health.textContent = "API " + (d.status || "unknown");
    }).catch(function () { health.textContent = "API unreachable"; });
  }

  // Evidence & uncertainty segmented control. Panels stay in the DOM; only
  // visibility changes, so all evidence remains reachable and printable.
  document.querySelectorAll("[data-tabs]").forEach(function (box) {
    var tabs = Array.prototype.slice.call(box.querySelectorAll("[role=tab]"));
    if (!tabs.length) { return; }
    var panels = tabs.map(function (t) {
      return document.getElementById(t.getAttribute("aria-controls") || "");
    });
    function select(index, moveFocus) {
      tabs.forEach(function (tab, i) {
        var on = i === index;
        tab.setAttribute("aria-selected", on ? "true" : "false");
        tab.setAttribute("tabindex", on ? "0" : "-1");
        if (panels[i]) { panels[i].hidden = !on; }
      });
      if (moveFocus && tabs[index]) { tabs[index].focus(); }
    }
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { select(i, false); });
      tab.addEventListener("keydown", function (e) {
        if (e.key === "ArrowRight" || e.key === "ArrowDown") {
          select((i + 1) % tabs.length, true); e.preventDefault();
        } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
          select((i - 1 + tabs.length) % tabs.length, true); e.preventDefault();
        } else if (e.key === "Home") { select(0, true); e.preventDefault(); }
        else if (e.key === "End") { select(tabs.length - 1, true); e.preventDefault(); }
      });
    });
    select(0, false);
  });

  // How-it-works walkthrough: play/pause, step, replay. Autoplays on load
  // unless the visitor asked for reduced motion, in which case the final state
  // is shown and nothing moves.
  var walkSteps = Array.prototype.slice.call(document.querySelectorAll(".walk-step"));
  var walkPlay = document.querySelector(".js-walk-play");
  var walkStep = document.querySelector(".js-walk-step");
  var walkReset = document.querySelector(".js-walk-reset");
  var walkCaption = document.getElementById("walk-caption");
  var walkDots = document.querySelector(".walk-dots");
  var walkList = document.getElementById("walk-steps");
  if (walkSteps.length && walkPlay && walkList) {
    var wi = 0;
    var wtimer = null;
    var dotEls = [];
    if (walkDots) {
      walkSteps.forEach(function () {
        var d = document.createElement("span");
        d.className = "walk-dot";
        walkDots.appendChild(d);
        dotEls.push(d);
      });
    }
    function walkStop() {
      if (wtimer) { clearInterval(wtimer); wtimer = null; }
      walkPlay.textContent = "Play";
      walkPlay.setAttribute("aria-label", "Play walkthrough");
    }
    function walkPaint() {
      walkSteps.forEach(function (s, i) {
        s.classList.toggle("done", i < wi);
        s.classList.toggle("active", i === wi);
      });
      dotEls.forEach(function (d, i) { d.classList.toggle("on", i <= wi); });
      if (walkCaption && walkSteps[wi]) {
        var c = walkSteps[wi].getAttribute("data-caption") || "";
        walkCaption.textContent = (wi + 1) + "/" + walkSteps.length + " - " + c;
      }
    }
    function walkStart() {
      walkStop();
      walkPlay.textContent = "Pause";
      walkPlay.setAttribute("aria-label", "Pause walkthrough");
      // ~14s total for five steps: slow enough to read, short enough to sit
      // through, and interruptible at any moment with Play/Pause.
      wtimer = setInterval(function () {
        if (wi >= walkSteps.length - 1) { walkStop(); } else { wi++; walkPaint(); }
      }, 2800);
    }
    function walkPlayPause() {
      if (wtimer) { walkStop(); return; }
      walkList.classList.add("dim");
      if (wi >= walkSteps.length - 1) { wi = 0; }
      walkPaint();
      if (reducedMotion()) { wi = walkSteps.length - 1; walkPaint(); return; }
      walkStart();
    }
    walkPlay.addEventListener("click", walkPlayPause);
    if (walkStep) {
      walkStep.addEventListener("click", function () {
        walkStop();
        walkList.classList.add("dim");
        wi = Math.min(wi + 1, walkSteps.length - 1);
        walkPaint();
      });
    }
    if (walkReset) {
      walkReset.addEventListener("click", function () {
        walkStop();
        walkList.classList.add("dim");
        wi = 0;
        walkPaint();
      });
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { walkStop(); }
    });
    walkList.classList.add("dim");
    wi = 0;
    walkPaint();
    if (!reducedMotion()) { walkPlayPause(); }
  }

  // Replay the observed path in chronological order, synchronized with the
  // chronological table. Observed transfers (nodes that carry a table row)
  // light as transfers; terminal boundaries light as boundaries, never as an
  // observed transfer. Auto-play pauses briefly at every branch endpoint and
  // stops at a supported service boundary.
  var pathNodes = Array.prototype.slice.call(document.querySelectorAll(".js-path-node"));
  var replayPlay = document.querySelector(".js-replay-play");
  if (pathNodes.length && replayPlay) {
    var timelineRows = {};
    document.querySelectorAll(".js-timeline-row").forEach(function (row) {
      var key = row.getAttribute("data-row");
      if (key) { timelineRows[key] = row; }
    });
    var caption = document.getElementById("replay-caption");
    var pi = -1;
    var ptimer = null;

    function nodeRow(node) { return node.getAttribute("data-row"); }
    function isObserved(node) { return !!nodeRow(node); }
    function isTerminal(node) {
      var kind = node.getAttribute("data-kind") || "";
      return kind === "known_service" || kind === "supported" ||
        kind === "deposit_candidate" || kind === "unresolved" || kind === "boundary";
    }
    function isSupported(node) {
      var kind = node.getAttribute("data-kind") || "";
      return kind === "known_service" || kind === "supported";
    }
    // One shared selection: a path node and its timeline row always match.
    function setSelected(key) {
      document.querySelectorAll(".js-timeline-row.selected").forEach(function (row) {
        row.classList.remove("selected");
        row.removeAttribute("aria-current");
      });
      pathNodes.forEach(function (node) {
        node.classList.remove("sel");
        node.removeAttribute("aria-current");
      });
      if (!key) { return []; }
      var matched = pathNodes.filter(function (n) { return nodeRow(n) === key; });
      matched.forEach(function (n) {
        n.classList.add("sel");
        n.setAttribute("aria-current", "true");
      });
      var row = timelineRows[key];
      if (row) {
        row.classList.add("selected");
        row.setAttribute("aria-current", "true");
      }
      return matched;
    }
    function clearSelection() { setSelected(null); }
    function light(index) {
      pathNodes.forEach(function (node, i) {
        var on = i <= index;
        node.classList.toggle("lit", on && isObserved(node));
        node.classList.toggle("lit-boundary", on && !isObserved(node));
        node.classList.toggle("pulse", i === index);
      });
    }
    function paint(detail) {
      if (!caption) { return; }
      if (pi < 0) { caption.textContent = "Not started."; return; }
      var node = pathNodes[pi];
      var label = node.getAttribute("data-label") || node.getAttribute("data-kind") || "";
      var what = isObserved(node) ? "Observed transfer" : "Boundary";
      caption.textContent = (pi + 1) + "/" + pathNodes.length + " - " + what +
        ": " + label + (detail ? " - " + detail : "");
    }
    function stop(message) {
      if (ptimer) { clearTimeout(ptimer); ptimer = null; }
      replayPlay.textContent = "Play";
      replayPlay.setAttribute("aria-label", "Play path replay");
      if (message && caption) { caption.textContent = message; }
    }
    function goTo(index, detail) {
      pi = index;
      light(index);
      if (pi >= 0) {
        setSelected(nodeRow(pathNodes[pi]));
        var node = pathNodes[pi];
        if (node.scrollIntoView && isObserved(node)) {
          node.scrollIntoView({ block: "nearest" });
        }
      }
      paint(detail);
    }
    function finish() {
      // Clear the transient highlight so the page returns to a neutral state;
      // the caption records that the replay completed.
      light(-1);
      clearSelection();
      stop("Replay complete - " + pathNodes.length + "/" + pathNodes.length + ".");
    }
    function next(autoplay) {
      if (pi >= pathNodes.length - 1) { finish(); return; }
      var target = pi + 1;
      goTo(target);
      if (autoplay) {
        if (isTerminal(pathNodes[target]) && isSupported(pathNodes[target])) {
          stop("Paused at a supported service boundary (" + (target + 1) +
            "/" + pathNodes.length + ").");
          return;
        }
        // Pause longer at each branch endpoint, shorter between transfers.
        var delay = isTerminal(pathNodes[target]) ? 1100 : 520;
        ptimer = setTimeout(function () { next(true); }, delay);
      }
    }
    function reset() {
      stop();
      pi = -1;
      light(-1);
      clearSelection();
      paint();
    }
    replayPlay.addEventListener("click", function () {
      if (ptimer) { stop("Paused."); return; }
      if (pi >= pathNodes.length - 1) { reset(); }
      if (reducedMotion()) { pi = pathNodes.length - 1; finish(); return; }
      replayPlay.textContent = "Pause";
      replayPlay.setAttribute("aria-label", "Pause path replay");
      next(true);
    });
    var prevBtn = document.querySelector(".js-replay-prev");
    if (prevBtn) {
      prevBtn.addEventListener("click", function () {
        stop();
        if (pi <= 0) { reset(); } else { goTo(pi - 1); }
      });
    }
    var nextBtn = document.querySelector(".js-replay-next");
    if (nextBtn) {
      nextBtn.addEventListener("click", function () { stop(); next(false); });
    }
    var resetBtn = document.querySelector(".js-replay-reset");
    if (resetBtn) {
      resetBtn.addEventListener("click", function () { reset(); });
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        stop("Replay paused.");
        pathNodes.forEach(function (n) { n.classList.remove("pulse"); });
        clearSelection();
      }
    });

    // Graph <-> timeline synchronization. A table row's locate control
    // highlights the matching path node(s), and a path node highlights its row.
    // Selection is a subtle accent shared by both, never a large shadow.
    document.querySelectorAll(".js-focus-row").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.getAttribute("data-row");
        stop();
        var matched = setSelected(key);
        pathNodes.forEach(function (n) { n.classList.remove("pulse"); });
        if (!matched.length) { return; }
        matched.forEach(function (n) { n.classList.add("pulse"); });
        pi = pathNodes.indexOf(matched[matched.length - 1]);
        if (caption) {
          caption.textContent = "Selected from the timeline - row " + key +
            (isObserved(matched[0]) ? " (observed transfer)." : " (boundary).");
        }
      });
    });
    pathNodes.forEach(function (node) {
      if (node.getAttribute("data-row")) { node.setAttribute("tabindex", "0"); }
      function selectNode() {
        var key = nodeRow(node);
        if (!key) { return; }
        stop();
        setSelected(key);
      }
      node.addEventListener("click", selectNode);
      node.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
          selectNode();
        }
      });
    });
    paint();
  }
})();
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _attr(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _short(value: Any, keep: int = 16) -> str:
    """Middle-truncate so the head and tail of an identifier stay readable."""

    text = "" if value is None else str(value)
    if len(text) <= keep:
        return text
    head = max(4, keep - 6)
    return text[:head] + "\u2026" + text[-5:]


def _copyable(value: Any, *, keep: int = 16, label: str = "value") -> str:
    """A short identifier plus an accessible copy button for the full value.

    The button always copies the complete raw string, never the shortened
    display, and the full value is repeated in a print-only span so a printed
    page is as readable as the screen."""

    if value is None or value == "":
        return "<span class='empty'>\u2014</span>"
    full = str(value)
    short = html.escape(_short(full, keep))
    print_full = (
        f"<span class='print-full addr'>{html.escape(full)}</span>"
        if len(full) > keep
        else ""
    )
    return (
        f"<span class='addr' title='{_attr(full)}'>{short}</span>{print_full}"
        f"<button class='copy no-print' type='button' data-copy='{_attr(full)}' "
        f"data-label='{_attr(label)}' aria-label='Copy full {_attr(label)}'>"
        f"copy</button>"
    )


def _truncated(value: Any, keep: int = 18) -> str:
    """A shortened identifier with the full value in a title and print span.
    Used for secondary tables where a copy button per row would be noise."""

    if value is None or value == "":
        return "<span class='empty'>\u2014</span>"
    full = str(value)
    short = html.escape(_short(full, keep))
    if len(full) <= keep:
        return f"<span class='addr'>{short}</span>"
    return f"<span class='addr' title='{_attr(full)}'>{short}</span>"


def _mode_chip(mode: str) -> str:
    label = MODE_LABELS.get(mode, mode or "UNKNOWN")
    return f"<span class='chip mode-{_attr(mode)}'>{_e(label)}</span>"


def _chip(text: str, css: str = "") -> str:
    return f"<span class='chip {_attr(css)}'>{_e(text)}</span>"


def _list(items: Sequence[str], *, empty: str) -> str:
    if not items:
        return f"<p class='empty'>{_e(empty)}</p>"
    return "<ul class='tight'>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return f"{count} {singular}"
    return f"{count} {plural or singular + 's'}"


# --------------------------------------------------------------------------
# Section builders
# --------------------------------------------------------------------------


def _input_card(view: DemoView | None, address_query: str) -> str:
    seed = (view.trace or {}).get("seed") if view and view.trace else {}
    asset = (seed or {}).get("asset") or {}
    contract = asset.get("token_contract") or "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    symbol = asset.get("display_symbol") or "USDT"
    current = view.preset.address if view else address_query
    return f"""
    <div class="card">
      <h2>Investigation input</h2>
      <form method="get" action="/console">
        <div class="flabel">Network</div>
        <div class="field-static">tron (TRON mainnet) &mdash; the only supported network</div>
        <div class="flabel">Asset</div>
        <div class="field-static">{_e(symbol)} &middot; verified contract
          <span class="addr">{_e(contract)}</span></div>
        <label for="address">Address</label>
        <input type="text" id="address" name="address" value="{_attr(current)}"
          autocomplete="off" spellcheck="false" autocapitalize="off"
          aria-describedby="address-hint" placeholder="T\u2026" />
        <p class="note" id="address-hint">TRON address (starts with T, 34
          characters). Saved results only &mdash; this never performs a live
          lookup.</p>
        <div class="actions">
          <button type="submit">View saved result</button>
        </div>
      </form>
      <p class="note">This local prototype is read-only and does not trace live.
        Entering an address opens the matching saved result; it never sends a
        provider request, and it never asks for a seed phrase or private key.</p>
    </div>"""


def _preset_card(presets: Sequence[Preset], view: DemoView | None) -> str:
    current_id = view.preset.id if view else None
    blocks = []
    for preset in presets:
        classes = "preset current" if preset.id == current_id else "preset"
        blocks.append(
            f"<a class='{classes}' href='/console?preset={_attr(preset.id)}'>"
            f"<div class='ptitle'>{_e(preset.title)}</div>"
            f"<div class='pdesc'>{_e(preset.description)}</div>"
            f"<div style='margin-top:6px'>{_mode_chip(preset.data_mode)} "
            f"{_chip(preset.scenario)}</div></a>"
        )
    return f"""
    <div class="card">
      <h2>Demo examples</h2>
      {''.join(blocks)}
      <p class="note">One supported/recorded result and one synthetic result
        with unresolved branches. Neither identifies a person.</p>
    </div>"""


def _readiness_card(
    readiness: Mapping[str, Any] | None,
    wallet_states: Mapping[str, int] | None,
    wallet_rows: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    if not readiness:
        return """
        <div class="card">
          <h2>Experimental ML readiness</h2>
          <p class="empty">Not available for this preset: no readiness report is
            saved.</p>
          <p class="note">This is an absent optional artifact, not a failed
            evaluation, and it does not affect the trace result above.</p>
        </div>"""
    no_model = readiness.get("no_model_trained_in_this_report", True)
    no_model_line = (
        "<p class='no-model'>No anomaly model trained</p>"
        if no_model
        else "<p class='no-model'>Model metrics require review</p>"
    )
    states = ""
    if wallet_states:
        states = " &middot; ".join(
            f"{_e(k)}: {_e(v)}" for k, v in sorted(wallet_states.items())
        )
    reasons = readiness.get("status_reasons") or []
    blockers = readiness.get("unresolved_blockers") or []
    wallet_table = ""
    if wallet_rows:
        body = "".join(
            "<tr>"
            f"<td>{_copyable(row.get('address'), keep=14, label='address')}</td>"
            f"<td>{_e(row.get('control_category'))}</td>"
            f"<td>{_e(row.get('review_state'))}</td>"
            f"<td>{_e(row.get('data_mode'))}</td>"
            f"<td>{_e(row.get('eligibility'))}</td>"
            "</tr>"
            for row in wallet_rows
        )
        wallet_table = (
            "<h3>Sourced evaluation wallets</h3>"
            "<div class='table-scroll'><table><thead><tr>"
            "<th>Address</th><th>Category</th><th>Review</th><th>Mode</th>"
            "<th>Materializable window</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>"
            "<p class='note'>Acceptance and a saved evidence bundle are "
            "separate facts; eligibility is checked on disk, not inferred.</p>"
        )
    return f"""
    <div class="card">
      <h2>Experimental ML readiness</h2>
      {no_model_line}
      <p class="readiness-status">Status: {_e(readiness.get('status', 'UNKNOWN'))}</p>
      <dl class="kv">
        <dt>Real evaluation wallets (registry)</dt>
        <dd>{_e(readiness.get('real_wallet_count', 0))}</dd>
        <dt>Accepted registry records</dt>
        <dd>{_e(readiness.get('accepted_real_registry_record_count', 0))}</dd>
        <dt>Materialized real windows</dt>
        <dd>{_e(readiness.get('materialized_window_count_real', 0))}</dd>
        <dt>Distinct materialized real wallets</dt>
        <dd>{_e(readiness.get('materialized_distinct_wallet_count_real', 0))}</dd>
        <dt>Related-wallet grouping supplied</dt>
        <dd>{_e(readiness.get('related_wallet_grouping_supplied', False))}</dd>
        <dt>Wallet-level split feasible</dt>
        <dd>{_e(readiness.get('model_dataset_split_feasible', False))}</dd>
        <dt>Group-level split feasible</dt>
        <dd>{_e(readiness.get('group_held_out_split_feasible', False))}</dd>
      </dl>
      <p class="note">A materialized window count is not a wallet count: windows
        are repeated observations, so N windows can come from far fewer wallets.</p>
      {f"<p class='note'>Registry review states: {states}</p>" if states else ""}
      {_list(reasons, empty="No stated reasons.")}
      {_list(blockers, empty="") if blockers else ""}
      {wallet_table}
      <p class="note">This card reports facts only. The trace result above does
        not depend on any model, and none has been trained.</p>
    </div>"""


def _fmt_metric(value: Any) -> str:
    if value is None:
        return "<span class='empty'>not computable</span>"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return _e(value)


def _anomaly_evaluation_card(evaluation: Mapping[str, Any] | None) -> str:
    """The Stage 3C model review-prioritization result, rendered SEPARATELY
    from every attribution artifact. It is a synthetic-only demonstration
    until a real corpus exists, and it changes nothing about the evidence."""

    header = "<h2>ML review-prioritization (experimental)</h2>"
    ml_flags = (
        "<p class='ml-flags'>"
        f"{_chip('EXPERIMENTAL', 'warn')} "
        f"{_chip('SYNTHETIC DEMONSTRATION', 'warn')} "
        f"{_chip('NOT ATTRIBUTION', 'st-not_built')} "
        f"{_chip('NOT FRAUD PROBABILITY', 'st-not_built')}"
        "</p>"
    )
    if not evaluation:
        return f"""
    <div class="card">
      {header}
      {ml_flags}
      <p class="empty">Not available for this preset: no anomaly evaluation
        report is saved.</p>
      <p class="note">This is an absent optional report, not an evaluation
        result. It is separate from the evidence and changes nothing about it.
        To save a report, run
        <code>scripts/anomaly_ranking.py --json-out
        var/anomaly-evaluation/report.json</code>. It runs on SYNTHETIC
        demonstration rows only; no model has been trained on real data.</p>
    </div>"""

    detail = evaluation.get("evaluation") or {}
    metrics = detail.get("metrics") or {}
    kind = str(evaluation.get("evaluation_kind") or "unknown")
    chip = (
        _chip("SYNTHETIC DEMONSTRATION", "warn")
        if kind == "pipeline_demonstration"
        else _chip("HELD-OUT EVALUATION", "st-partial")
    )

    conf_ranks = detail.get("confounder_ranks") or []
    conf_html = (
        ", ".join(f"{_e(r.get('wallet_id'))} \u2192 #{_e(r.get('rank'))}" for r in conf_ranks)
        or "none in the split"
    )

    top_rows = "".join(
        "<tr>"
        f"<td class='num'>{_e(s.get('rank'))}</td>"
        f"<td>{_e(s.get('wallet_id'))}</td>"
        f"<td class='num'>{_fmt_metric(s.get('score'))}</td>"
        f"<td>{_e(s.get('data_mode'))}</td>"
        f"<td class='num'>{_e(len(s.get('imputed_features') or []))}</td>"
        "</tr>"
        for s in (detail.get("top_k") or [])
    )
    top_table = (
        "<h3>Top-ranked rows</h3><div class='table-scroll'><table><thead><tr>"
        "<th>Rank</th><th>Wallet id</th><th>Score</th><th>Mode</th>"
        "<th>Imputed</th></tr></thead>"
        f"<tbody>{top_rows}</tbody></table></div>"
        "<p class='note'>Wallet ids are pseudonymous digests, not addresses. "
        "Scores are a review-prioritization ordering, not a probability. Raw "
        "observed feature values travel with each score in the saved JSON; they "
        "are observations, not a model explanation.</p>"
        if top_rows
        else ""
    )

    notes = detail.get("notes") or []
    conf_counts = (
        f"{_e(metrics.get('confounders_in_top_k'))} of "
        f"{_e(metrics.get('labeled_in_top_k'))} labeled"
    )
    label_counts = " / ".join(
        _e(detail.get(key))
        for key in ("labeled_row_count", "unlabeled_excluded", "outside_rubric_excluded")
    )
    return f"""
    <div class="card">
      {header}
      {ml_flags}
      {chip}
      <p class="note">Reported separately from the evidence above. This ranks
        observations for analyst attention only &mdash; it is not an accuracy
        claim, does not measure criminal guilt, and changes nothing about the
        trace result.</p>
      <dl class="kv">
        <dt>Evaluation kind</dt><dd>{_e(kind)}</dd>
        <dt>Rubric</dt><dd>{_e(detail.get('rubric_id'))}</dd>
        <dt>Split</dt><dd>{_e(detail.get('split_description'))}</dd>
        <dt>k</dt><dd>{_e(metrics.get('at_k'))}</dd>
        <dt>Review-worthy precision@k</dt>
        <dd>{_fmt_metric(metrics.get('review_worthy_precision_at_k'))}</dd>
        <dt>Random-ranking baseline</dt>
        <dd>{_fmt_metric(metrics.get('random_ranking_baseline_precision_at_k'))}</dd>
        <dt>Confounders in top-k</dt><dd>{conf_counts}</dd>
        <dt>Known confounder ranks</dt><dd>{conf_html}</dd>
        <dt>Labeled / unlabeled / outside rubric</dt><dd>{label_counts}</dd>
      </dl>
      {top_table}
      {_list(notes, empty="")}
      <p class="note">No model has been trained on real data, so no
        real-corpus metric is reported. A high-ranked confounder is a false
        positive to inspect, not a finding.</p>
    </div>"""


def _walk_result_line(view: DemoView) -> str:
    """One plain-text result line for the walkthrough's terminal step."""

    outcome = view.outcome
    trace = view.trace or {}
    endings = trace.get("branch_endings") or []
    if outcome:
        category = str(outcome.get("category", "unknown_or_blocked"))
        service = outcome.get("service_name")
        label = CATEGORY_LABELS.get(category, category)
        if service and category in ("supported_destination", "strong_inference", "candidate_lead"):
            return f"{label}: {service}"
        return label
    known = [b for b in endings if b.get("endpoint_class") == "known_service"]
    unresolved = sum(1 for b in endings if b.get("endpoint_class") == "unresolved")
    if known:
        return (
            f"{_plural(len(known), 'branch', 'branches')} reached a labelled "
            "service boundary"
        )
    if endings:
        return f"No labelled boundary; {_plural(unresolved, 'unresolved ending')}"
    return "No branch ending recorded"


def _walkthrough_card(view: DemoView | None, *, with_result: bool = True) -> str:
    """A short, honest animation of how a saved result becomes an outcome.

    Generic by design: it explains the pipeline, not a specific case, and it
    says plainly that it opens saved evidence rather than tracing live. When a
    real result is selected, the last step is that result, so the walkthrough
    ends with closure instead of a loop.
    """

    if with_result and (view is None or view.trace is None):
        return ""

    # Five steps at most: seed, observe, trace, check provenance, verdict.
    steps: list[tuple[str, str]] = [
        ("Seed", "Start from the complaint's seed transfer. No live call is made."),
        ("Observe", "Walk the saved transfers forward in time, in order."),
        ("Trace", "Keep every branch: service boundary, candidate, or unresolved."),
        (
            "Check provenance",
            "Match a terminal address to a dated, reviewed service label, if one exists.",
        ),
    ]
    result_text = _walk_result_line(view) if (with_result and view is not None) else (
        "Supported / Candidate / Unknown"
    )
    verdict_detail = (
        "The verdict is reported with provenance, status axes, and limitations."
        if view is None
        else f"Result: {result_text}. Provenance, status axes, and limits follow."
    )
    steps.append(("Supported / Candidate / Unknown", verdict_detail))
    items = []
    for number, (title, detail) in enumerate(steps, start=1):
        items.append(
            f"<li class='walk-step{' result' if number == len(steps) else ''}' "
            f"data-step='{number}' data-caption='{_attr(detail)}'>"
            f"<span class='wnum'>{number}</span>"
            f"<span class='wt'>{_e(title)}</span>"
            f"<div class='wd'>{_e(detail)}</div></li>"
        )
    return f"""
    <section class="card walk no-print" aria-labelledby="walk-h">
      <h2 id="walk-h">How this works</h2>
      <ol class="walk-steps" id="walk-steps">{''.join(items)}</ol>
      <div class="walk-controls">
        <button type="button" class="js-walk-play" aria-label="Play walkthrough">Play</button>
        <button type="button" class="secondary js-walk-step"
          aria-label="Next step">Step</button>
        <button type="button" class="secondary js-walk-reset"
          aria-label="Replay walkthrough">Replay</button>
        <span class="walk-dots" aria-hidden="true"></span>
      </div>
      <p class="walk-caption" id="walk-caption" aria-live="polite"></p>
    </section>"""


def _result_card(view: DemoView) -> str:
    """The compact headline result: outcome, destination, amount, mode,
    execution/finality, and one important limitation. No confidence score and
    no risk meter ever appears here."""

    outcome = view.outcome
    trace = view.trace or {}
    endings = trace.get("branch_endings") or []
    rows = _effective_transfer_rows(view)
    known = [b for b in endings if b.get("endpoint_class") == "known_service"]

    if outcome:
        category = str(outcome.get("category", "unknown_or_blocked"))
        service = outcome.get("service_name")
        head = CATEGORY_LABELS.get(category, category)
        if service and category in ("supported_destination", "strong_inference", "candidate_lead"):
            if category == "supported_destination":
                head = f"Supported destination: {_e(service)}"
            elif category == "strong_inference":
                head = f"Strong inference (uncalibrated): {_e(service)}"
            else:
                head = f"Candidate lead: {_e(service)} (not an accepted destination)"
        if category == "supported_destination":
            conclusion = (
                f"Path reached an accepted {_e(service)} service-control address "
                "inside the label's dated window."
            )
        elif category == "candidate_lead":
            conclusion = (
                "A candidate lead: traceable evidence, but the stated limits keep "
                "it below a supported destination."
            )
        elif category == "strong_inference":
            conclusion = (
                "Matched the uncalibrated strong-inference policy; engineering "
                "judgment, not a validated probability."
            )
        else:
            conclusion = (
                "No accepted label reaches this claim, or a blocking condition "
                "applies. Not an assertion that nothing happened."
            )
        unknown_items = [str(u) for u in (outcome.get("unresolved") or [])]
        reasons = outcome.get("reason_codes") or []
        claim_id = outcome.get("claim_id")
    else:
        category = ""
        if known:
            names = ", ".join(
                str((b.get("label") or {}).get("entity_name") or b.get("address"))
                for b in known
            )
            head = (
                f"{_plural(len(known), 'branch', 'branches')} reached a labelled "
                "service boundary"
            )
            conclusion = (
                f"Labelled {_plural(len(known), 'endpoint')}: {names}. No Stage 3A "
                "outcome record is saved, so no outcome category is asserted."
            )
        else:
            head = "No branch reached a labelled service boundary"
            conclusion = (
                "Every observed branch ended unresolved, at a boundary, or at a "
                "candidate. A limit of the observed scope, not a finding."
            )
        unknown_items = []
        reasons = []
        claim_id = None

    observed = rows[0] if rows else {}
    amount = observed.get("amount")
    asset = observed.get("asset") or "USDT"
    amount_text = (
        f"{_e(amount)} {_e(asset)}" if amount else "<span class='empty'>not recorded</span>"
    )
    execution = (
        outcome.get("execution_status") if outcome else observed.get("status")
    )
    finality = observed.get("status") if observed else None
    execution_text = _e(execution or "\u2014")
    if finality and str(finality) not in str(execution_text):
        execution_text += f" <span class='note'>{_e(finality)}</span>"

    limitation = unknown_items[0] if unknown_items else str(view.preset.scope_note)
    reason_chips = " ".join(_chip(str(r), "warn") for r in reasons)
    claim_line = f"<p class='note mono claim'>claim {_e(claim_id)}</p>" if claim_id else ""
    mode_warning = (
        "<p class='note'><strong>RECORDED PUBLIC</strong> \u2014 these are saved "
        "public-disclosure observations, not a live chain connection.</p>"
        if view.data_mode == "RECORDED_PUBLIC"
        else ""
    )
    synthetic_warning = (
        "<p class='note'><strong>SYNTHETIC</strong> \u2014 every address and service "
        "name is fictional. This demonstrates the method, not a real case.</p>"
        if view.data_mode == "SYNTHETIC"
        else ""
    )
    return f"""
    <section class="card result-card {_attr(RESULT_CSS.get(category, ''))}"
      aria-labelledby="result-h">
      <h2 id="result-h">Result</h2>
      <p class="result-headline">{head}</p>
      <p class="result-line">{_e(conclusion)}</p>
      <div class="result-grid">
        <div class="result-fact"><span class="rk">Observed amount</span>
          <span class="rv">{amount_text}</span></div>
        <div class="result-fact"><span class="rk">Data mode</span>
          <span class="rv">{_mode_chip(view.data_mode)}</span></div>
        <div class="result-fact"><span class="rk">Execution / finality</span>
          <span class="rv">{execution_text}</span></div>
      </div>
      {f"<p style='margin-top:6px'>{reason_chips}</p>" if reason_chips else ""}
      {claim_line}
      <div class="result-limit"><span class="rk">One important limitation</span>
        {_e(limitation)}</div>
      {mode_warning}
      {synthetic_warning}
    </section>"""


def _uncertainty_panel(view: DemoView) -> str:
    """The independent status axes, grouped logically for scanning but never
    collapsed into one score."""

    outcome = view.outcome
    scope = (view.trace or {}).get("scope") or {}

    def _group(title: str, axes: Sequence[str], values: Mapping[str, Any]) -> str:
        rows = "".join(
            f"<dt>{_e(axis)}</dt><dd>{_e(values.get(axis, '\u2014'))}</dd>"
            for axis in axes
        )
        return (
            f"<div class='axes-group'><h3>{_e(title)}</h3>"
            f"<dl class='axes'>{rows}</dl></div>"
        )

    values: Mapping[str, Any]
    if outcome:
        values = outcome
        missing_note = ""
    else:
        # No Stage 3A outcome record: show only the axes the saved trace records.
        values = {
            "coverage_status": scope.get("coverage_status", "\u2014"),
            "case_flow_linkage": scope.get("case_flow_linkage", "\u2014"),
        }
        missing_note = (
            "<p class='note'>No Stage 3A outcome record is saved, so the other "
            "axes are recorded per branch below rather than as a single result. "
            "They are not invented here.</p>"
        )
    groups = "".join(
        _group(title, axes, values)
        for title, axes in AXIS_GROUPS
        if any(axis in values for axis in axes)
    )
    return (
        groups
        + "<p class='note'>These axes are copied through unchanged. They are "
        "independent facts and are never collapsed into one confidence score.</p>"
        + missing_note
    )


def _effective_transfer_rows(view: DemoView) -> list[dict[str, Any]]:
    """The rows the chronological table shows: recorded transfers, or the
    branch arrival events when the saved result has no onward transfer rows."""

    trace = view.trace or {}
    seed = trace.get("seed") or {}
    transfers = list(trace.get("observed_transfers") or [])
    symbol = (seed.get("asset") or {}).get("display_symbol") or "USDT"

    # The separately saved behavioral acquisition stores a block time for the
    # same transaction. Join on tx_hash only, for display, and footnote it.
    seed_times: dict[str, str] = {}
    for row in (view.behavioral_evidence or {}).get("rows") or []:
        tx = row.get("tx_hash")
        when = row.get("block_time")
        if tx and when:
            seed_times.setdefault(str(tx), str(when))

    def _event_tx(event: Any) -> str | None:
        parts = str(event).split(":")
        return parts[1] if len(parts) > 1 and parts[1] else None

    def _observed_row(t: Mapping[str, Any], *, status: str, seed_row: bool) -> dict[str, Any]:
        return {
            "hop": t.get("hop_depth"),
            "time": t.get("block_time"),
            "time_source": None,
            "from": t.get("from_address"),
            "to": t.get("to_address"),
            "amount": t.get("amount_display"),
            "base": t.get("amount_base_units"),
            "asset": (t.get("asset") or {}).get("display_symbol") or symbol,
            "event": t.get("event_reference"),
            "tx": t.get("tx_hash"),
            "status": status,
            "ambiguous": bool(t.get("ordering_ambiguous")),
            "derived": False,
            "seed_row": seed_row,
        }

    rows: list[dict[str, Any]] = []
    seed_transfer = trace.get("seed_transfer")
    if isinstance(seed_transfer, Mapping):
        rows.append(
            _observed_row(
                seed_transfer,
                status=(
                    "seed transfer (case link) / "
                    f"{seed_transfer.get('execution_status')} / "
                    f"{seed_transfer.get('confirmation_state')}"
                ),
                seed_row=True,
            )
        )
    for t in transfers:
        rows.append(
            _observed_row(
                t,
                status=f"{t.get('execution_status')} / {t.get('confirmation_state')}",
                seed_row=False,
            )
        )
    if not rows:
        # Older saved results did not carry the seed transfer. Fall back to the
        # branch's saved arrival event and join its time from the separate
        # behavioral acquisition when present; both facts are labelled.
        for b in trace.get("branch_endings") or []:
            event = b.get("arrival_event_reference")
            if not event:
                continue
            tx = _event_tx(event)
            when = seed_times.get(tx) if tx else None
            rows.append(
                {
                    "hop": b.get("hop_depth"),
                    "time": when,
                    "time_source": (
                        "read from the separately saved behavioral acquisition "
                        "for the same transaction"
                    )
                    if when
                    else None,
                    "from": seed.get("address"),
                    "to": b.get("address"),
                    "amount": b.get("observed_amount_display"),
                    "base": b.get("observed_amount_base_units"),
                    "asset": symbol,
                    "event": event,
                    "tx": tx,
                    "status": "seed arrival event (from branch ending)",
                    "ambiguous": False,
                    "derived": True,
                }
            )
    return rows


def _timeline_section(view: DemoView) -> str:
    """The authoritative chronological table of observed transfers. Selecting a
    row highlights the matching path node, and vice versa; this table is also
    the accessible, print-safe representation of the replay animation."""

    rows = _effective_transfer_rows(view)

    if not rows:
        return """
        <section class="card" id="timeline" aria-labelledby="timeline-h">
          <h2 id="timeline-h">Timeline</h2>
          <p class="empty">No transfer row was recorded in this saved trace
            result. That is not the same as no activity.</p>
        </section>"""

    body = []
    for i, r in enumerate(rows, start=1):
        status = _e(r["status"])
        if r["ambiguous"]:
            status += " <span class='flag'>ordering ambiguous</span>"
        if r["time"]:
            source = r.get("time_source")
            time_cell = _e(r["time"])
            if source:
                time_cell += f"<br><span class='note'>{_e(source)}</span>"
        else:
            time_cell = "<span class='empty'>not stored</span>"
        body.append(
            f"<tr class='js-timeline-row' data-row='{i}' tabindex='-1'>"
            f"<td class='num'><button type='button' class='row-locator "
            f"js-focus-row no-print' data-row='{i}' "
            f"aria-label='Highlight row {i} on the path'>{i}</button></td>"
            f"<td class='num'>{_e(r['hop'])}</td>"
            f"<td>{time_cell}</td>"
            f"<td>{_copyable(r['from'], keep=18, label='from address')}</td>"
            f"<td>{_copyable(r['to'], keep=18, label='to address')}</td>"
            f"<td class='num'>{_e(r['amount'])} {_e(r['asset'])}"
            f"<br><span class='note'>base units {_e(r['base'])}</span></td>"
            f"<td>{_copyable(r['event'], keep=28, label='event reference')}</td>"
            f"<td>{status}</td>"
            "</tr>"
        )
    seed_note = ""
    if any(r.get("seed_row") for r in rows):
        seed_note = (
            "<p class='note'>Hop 0 is the seed transfer that links the case to "
            "the path, shown from the trace result's own saved event.</p>"
        )
    derived_note = ""
    if any(r["derived"] for r in rows):
        if any(r["derived"] and r["time"] for r in rows):
            derived_note = (
                "<p class='note'>The seed transfer is shown from the saved "
                "branch arrival event; the trace result does not store its own "
                "transfer row. Its block time is read from the separately "
                "saved behavioral acquisition for the same transaction.</p>"
            )
        else:
            derived_note = (
                "<p class='note'>The seed transfer is shown from the saved "
                "branch arrival event; the trace result does not store its own "
                "transfer row, and no saved acquisition supplies its block "
                "time.</p>"
            )
    return f"""
    <section class="card" id="timeline" aria-labelledby="timeline-h">
      <h2 id="timeline-h">Timeline</h2>
      <p class="note">Chronological transfers, authoritative and printable. Use
        the row number to highlight it on the path, or replay the path in the
        section above.</p>
      <div class="table-scroll">
        <table>
          <thead><tr>
            <th>#</th><th>Hop</th><th>Time (UTC)</th><th>From</th><th>To</th>
            <th>Amount</th><th>Event / tx reference</th><th>Execution / finality</th>
          </tr></thead>
          <tbody>{''.join(body)}</tbody>
        </table>
      </div>
      {seed_note}
      {derived_note}
      <p class="note">Exact amounts are integer base units serialized as
        strings; the decimal display is not used for any arithmetic.</p>
    </section>"""


def _evidence_layers(view: DemoView) -> str:
    """The one small Evidence layers control. Resource and behavioral evidence
    is saved separately and stays collapsed here; it is never animated as an
    observed transfer."""

    behavioral = _behavioral_card(view)
    inner = behavioral or (
        "<p class='empty'>Not recorded for this preset: no separate behavioral "
        "acquisition is saved. That means no such capture was taken, not that "
        "there was no activity.</p>"
    )
    return (
        "<details class='layers no-print'><summary>Evidence layers</summary>"
        "<p class='note'>Resource relationships and behavioral features are "
        "secondary evidence, saved separately from the trace. They are shown "
        "only here and are never treated as observed transfers.</p>"
        f"{inner}</details>"
    )


def _path_section(view: DemoView) -> str:
    """The main visual: seed, observed transfers, intermediate wallets, and the
    supported/candidate/unresolved boundary of each branch. Resource and
    behavioral layers stay behind the one small Evidence layers control."""

    trace = view.trace or {}
    seed = trace.get("seed") or {}
    endings = trace.get("branch_endings") or []
    if not endings:
        return f"""
        <section class="card" id="path" aria-labelledby="path-h">
          <h2 id="path-h">Path</h2>
          <p class="empty">No branch ending was recorded in this saved result.</p>
          {_evidence_layers(view)}
        </section>"""

    by_event = {
        t.get("event_reference"): t for t in (trace.get("observed_transfers") or [])
    }
    effective_rows = _effective_transfer_rows(view)
    row_by_event = {
        row.get("event"): i
        for i, row in enumerate(effective_rows, start=1)
        if row.get("event")
    }
    time_by_event = {
        row.get("event"): row.get("time")
        for row in effective_rows
        if row.get("event") and row.get("time")
    }
    amount_by_event = {
        row.get("event"): (row.get("amount"), row.get("asset"))
        for row in effective_rows
        if row.get("event") and row.get("amount")
    }
    seed_addr = seed.get("address")
    seed_event = seed.get("event_reference") or (trace.get("seed_transfer") or {}).get(
        "event_reference"
    )
    order = 0

    def _next_order() -> int:
        nonlocal order
        order += 1
        return order

    def _attrs(kind: str, row: Any, label: str) -> str:
        row_attr = f" data-row='{_attr(row)}'" if row else ""
        return (
            f"data-order='{_next_order()}' data-kind='{_attr(kind)}'"
            f"{row_attr} data-label='{_attr(label)}'"
        )

    def _time(event: Any) -> str:
        when = time_by_event.get(event) or ((by_event.get(event) or {}).get("block_time"))
        return f"<span class='ets'>{_e(when)}</span>" if when else ""

    def _edge(event: Any, amount: Any = None, symbol: Any = None) -> str:
        # A path edge is a visual summary; the exact amount lives in the
        # Timeline. Middle-truncate a very long display so it cannot wrap into
        # a tall digit column, and keep the full value in the title.
        amt = ""
        if amount not in (None, ""):
            full = f"{amount} {symbol}"
            amt = (
                f"<span class='amt' title='{_attr(full)}'>"
                f"{_e(_short(str(amount), 16))}"
                f"<span class='sym'> {_e(symbol)}</span></span>"
            )
        return (
            "<span class='edge js-path-edge'>"
            f"{amt}{_time(event)}"
            f"<span class='eev'>{_e(_short(event, 18))}</span>"
            "</span>"
        )

    blocks = []
    for i, b in enumerate(endings, start=1):
        path = b.get("branch_path") or []
        seed_row = row_by_event.get(seed_event)
        nodes = [
            f"<span class='node seed js-path-node' {_attrs('seed', seed_row, 'seed')}>"
            "<span class='nlabel'>seed / case link</span>"
            f"<span class='addr' title='{_attr(seed_addr)}'>"
            f"{_e(_short(seed_addr, 20))}</span>"
            f"{_time(seed_event)}"
            "</span>"
        ]
        for event in path:
            t = by_event.get(event)
            if t and t.get("to_address"):
                amount = t.get("amount_display")
                symbol = (t.get("asset") or {}).get("display_symbol") or "USDT"
                addr = t.get("to_address")
                nodes.append(
                    _edge(event, amount, symbol)
                    + "<span class='arrow'>\u2192</span>"
                    + f"<span class='node js-path-node' "
                    f"{_attrs('observed', row_by_event.get(event), _short(addr, 20))}>"
                    "<span class='nlabel'>wallet</span>"
                    f"<span class='addr' title='{_attr(addr)}'>"
                    f"{_e(_short(addr, 20))}</span>"
                    f"{_time(event)}"
                    "</span>"
                )
            else:
                pair = amount_by_event.get(event)
                amount, symbol = pair if pair else (None, None)
                nodes.append(_edge(event, amount, symbol) + "<span class='arrow'>\u2192</span>")
        entity = (b.get("label") or {}).get("entity_name")
        endpoint = b.get("endpoint_class", "unresolved")
        address = b.get("address")
        arrival = b.get("arrival_event_reference") or seed_event
        label = entity or _short(address, 20)
        terminal = (
            f"<span class='node {_attr(endpoint)} js-path-node' "
            f"{_attrs(str(endpoint), row_by_event.get(arrival), str(label))}>"
            f"<span class='nlabel'>{_e(entity) if entity else 'boundary'}</span>"
            f"<span class='addr' title='{_attr(address)}'>"
            f"{_e(_short(address, 20))}</span>"
            + _time(arrival)
            + f"<span>{_chip(str(endpoint), 'ep-' + str(endpoint))}</span>"
            + "</span>"
        )
        nodes.append(terminal)
        note = b.get("note")
        blocks.append(
            "<div class='path-row'>"
            f"<div class='path-head'><span class='bnum'>Branch {i}</span>"
            f"<span>hop {_e(b.get('hop_depth'))}</span>"
            f"<span>{_e(b.get('attribution_status'))}</span>"
            f"<span>case amount {_e(b.get('case_amount_basis'))}</span></div>"
            f"<div class='path-track'>{''.join(nodes)}</div>"
            + (f"<p class='note'>{_e(note)}</p>" if note else "")
            + "</div>"
        )
    return f"""
    <section class="card" id="path" aria-labelledby="path-h">
      <h2 id="path-h">Path</h2>
      <div class="legend">
        <span class="k"><span class="swatch seed"></span>seed / case link</span>
        <span class="k"><span class="swatch known_service"></span>supported service boundary</span>
        <span class="k"><span class="swatch deposit_candidate"></span>candidate lead</span>
        <span class="k"><span class="swatch unresolved"></span>unresolved / boundary</span>
      </div>
      {''.join(blocks)}
      <div class="replay-controls no-print">
        <button type="button" class="js-replay-play js-replay-paths"
          aria-label="Play path replay">Play</button>
        <button type="button" class="secondary js-replay-prev"
          aria-label="Previous transfer">Previous</button>
        <button type="button" class="secondary js-replay-next"
          aria-label="Next transfer">Next</button>
        <button type="button" class="secondary js-replay-reset"
          aria-label="Replay path from the start">Replay</button>
      </div>
      <p class="replay-caption" id="replay-caption" aria-live="polite">Not started.</p>
      <p class="note">A path is a sequence of observed transfers, not ownership
        of fungible units. A candidate is a lead, not a verified boundary.</p>
      <p class="no-print"><a class="btn secondary"
        href="/graph?preset={_attr(view.preset.id)}">Open as a fund-flow graph</a></p>
      {_evidence_layers(view)}
    </section>"""


def _provenance_panel(view: DemoView) -> str:
    trace = view.trace or {}
    scope = trace.get("scope") or {}
    manifest = view.manifest or {}
    snapshot = scope.get("label_snapshot") or {}

    label_blocks = []
    for b in trace.get("branch_endings") or []:
        label = b.get("label")
        if not label:
            continue
        methodology = label.get("methodology") or ""
        label_blocks.append(
            "<div class='path-row'>"
            f"<div class='path-head'>{_e(label.get('entity_name'))} &middot; "
            f"{_copyable(b.get('address'), keep=20, label='address')}</div>"
            "<dl class='kv'>"
            f"<dt>Source</dt><dd>{_e(label.get('source_reference'))}</dd>"
            f"<dt>Retrieved</dt><dd>{_e(label.get('retrieval_date'))}</dd>"
            f"<dt>Reviewer</dt><dd>{_e(label.get('review_state'))} "
            f"&middot; {_e(label.get('reviewed_by') or 'not recorded')} "
            f"&middot; {_e(label.get('reviewed_at') or 'not reviewed')}</dd>"
            f"<dt>Valid window</dt><dd>{_e(label.get('valid_from'))} \u2192 "
            f"{_e(label.get('valid_to') or 'open')}</dd>"
            f"<dt>Last verified</dt><dd>{_e(label.get('last_verified_at'))}</dd>"
            f"<dt>Source hash</dt><dd>"
            f"{_copyable(label.get('source_hash'), keep=12, label='source hash')}</dd>"
            f"<dt>Review reference</dt><dd>"
            f"{_copyable(label.get('review_reference'), keep=24, label='review reference')}"
            "</dd>"
            f"<dt>Assertion</dt><dd>{_e(label.get('assertion_type'))} "
            f"(address_role: {_e(label.get('address_role'))})</dd>"
            f"<dt>Label set</dt><dd>{_e(label.get('label_set_version'))}</dd>"
            f"<dt>Original document</dt><dd>{_e(label.get('original_reference') or '\u2014')}</dd>"
            f"<dt>Original member</dt><dd>{_e(label.get('original_member') or '\u2014')} "
            f"&middot; {_e(label.get('original_row_locator') or '')}</dd>"
            f"<dt>Original hash</dt><dd>"
            f"{_copyable(label.get('original_hash'), keep=12, label='original hash')}</dd>"
            "</dl>"
            + (
                f"<details><summary>Full methodology (saved, unedited)</summary>"
                f"<pre>{_e(methodology)}</pre></details>"
                if methodology
                else ""
            )
            + "</div>"
        )

    files = snapshot.get("files") or []
    file_rows = "".join(
        f"<li>{_e(f.get('name'))}: {_e(f.get('rows_loaded'))} rows, sha256 "
        f"{_copyable(f.get('sha256'), keep=12, label='sha256')}</li>"
        for f in files
    )
    manifest_files = manifest.get("files") or {}
    manifest_items = "".join(
        f"<li class='addr'>{_e(name)} &middot; {_e(digest)}</li>"
        for name, digest in sorted(manifest_files.items())
    )

    if not label_blocks:
        label_blocks.append(
            "<p class='empty'>No entity attribution was recorded in this saved result.</p>"
        )

    return f"""
      <p class="note"><strong>What the source supports:</strong> a dated
        claim of service control over a listed address. <strong>What it does
        not support:</strong> that any intermediary on the path belongs to the
        service, or that the seed address belongs to the service.</p>
      {''.join(label_blocks)}
      <h3>Label sets read at run time</h3>
      <p class="note">Source: {_e(snapshot.get('source', 'unspecified'))} &middot;
        {_e(snapshot.get('accepted_service_claims', 0))} accepted service claim(s).</p>
      {"<ul class='tight'>" + file_rows + "</ul>" if file_rows else ""}
      <h3>Run metadata</h3>
      <dl class="kv">
        <dt>Engine</dt><dd>{_e(scope.get('engine_version'))}</dd>
        <dt>Run started</dt><dd>{_e(scope.get('started_at'))}</dd>
        <dt>Run finished</dt><dd>{_e(scope.get('finished_at'))}</dd>
        <dt>Analysis cutoff</dt><dd>{_e(scope.get('analysis_cutoff'))}</dd>
      </dl>
      {"" if not manifest else "<h3>Saved bundle</h3><dl class='kv'>"
        f"<dt>Data mode at capture</dt><dd>{_e(manifest.get('data_mode'))}</dd>"
        f"<dt>Capture kind</dt><dd>{_e(manifest.get('mode'))}</dd>"
        f"<dt>Provider exchanges</dt><dd>{_e(manifest.get('provider_exchanges'))}</dd>"
        f"<dt>Run id</dt><dd>"
        f"{_copyable(manifest.get('run_id'), keep=18, label='run id')}</dd>"
        "</dl>"
        + (f"<details><summary>Bundle file hashes</summary><ul class='tight'>"
           f"{manifest_items}</ul></details>" if manifest_items else "")
        + (f"<p class='note'>{_e(manifest.get('caveat'))}</p>"
           if manifest.get('caveat') else "")}"""


def _limitations_panel(view: DemoView) -> str:
    trace = view.trace or {}
    limitations = trace.get("limitations") or []
    outcome = view.outcome or {}
    unresolved = outcome.get("unresolved") or []
    comparison = view.comparison or {}
    caveats = comparison.get("caveats") or []

    items: list[str] = []
    for lim in limitations:
        items.append(f"{lim.get('code')}: {lim.get('message')}")
    items += [str(u) for u in unresolved]
    items += [str(c) for c in caveats]
    if view.preset.scope_note:
        items.append(view.preset.scope_note)
    items.append(
        "Unknown ownership: an observed path establishes a sequence of "
        "transfers, not ownership of fungible units."
    )
    items.append(
        "Allocation unknown: a case-associated amount stays allocation_unknown "
        "unless the existing code proves otherwise."
    )
    items.append(
        "Bounded coverage: 'complete' always means complete within the declared "
        "scope, not complete knowledge of a chain."
    )
    if view.data_mode == "RECORDED_PUBLIC":
        items.append("Recorded, not live: recorded public data is not live chain data.")
    if view.data_mode == "SYNTHETIC":
        items.append("This synthetic fixture is not evidence about any real service.")

    return _list(items, empty="No limitations were recorded for this run.")


def _behavioral_card(view: DemoView) -> str:
    manifest = view.behavioral_manifest
    if not manifest:
        return ""
    query = manifest.get("query") or {}
    config = manifest.get("configuration") or {}
    caveat = manifest.get("caveat") or ""
    counts = manifest.get("direction_counts") or {}
    evidence = view.behavioral_evidence or {}
    rows = evidence.get("rows") or []
    symbol = "USDT"

    # A bounded preview, collapsed by default; the full bundle is one link
    # away rather than inlined into every page load.
    preview = rows[:15]
    row_html = []
    for r in preview:
        row_html.append(
            "<tr>"
            f"<td>{_e(r.get('direction') or '')}</td>"
            f"<td>{_e(r.get('block_time'))}</td>"
            f"<td>{_truncated(r.get('counterparty_address'), 18)}</td>"
            f"<td class='num'>{_e(r.get('amount_base_units'))}</td>"
            f"<td>{_truncated(r.get('tx_hash'), 20)}</td>"
            f"<td>{_e(r.get('execution_status'))} / {_e(r.get('confirmation_state'))}"
            + (" <span class='flag'>ordering ambiguous</span>"
               if str(r.get("ordering_ambiguous")).lower() == "true" else "")
            + "</td>"
            f"<td>{_e(r.get('coverage_status'))}</td>"
            "</tr>"
        )
    bundle_link = (
        f"<a href='/console/behavioral/{_attr(view.preset.id)}' target='_blank' "
        "rel='noopener'>Open the saved bundle (JSON)</a>"
    )
    if rows:
        remaining = len(rows) - len(preview)
        stored_rows = (
            f"<details><summary>Show first {len(preview)} of {len(rows)} saved "
            "rows</summary><div class='table-scroll'><table><thead><tr>"
            "<th>Dir</th><th>Time (UTC)</th><th>Counterparty</th>"
            "<th>Amount (base units)</th><th>Tx</th><th>Exec / finality</th>"
            "<th>Coverage</th></tr></thead><tbody>"
            + "".join(row_html)
            + "</tbody></table></div>"
            + (
                f"<p class='note'>{remaining} more row(s) are in the saved "
                f"bundle. {bundle_link}.</p>"
                if remaining
                else f"<p class='note'>{bundle_link}.</p>"
            )
            + "</details>"
        )
    else:
        stored_rows = "<p class='empty'>No rows were saved in this bundle.</p>"
    return f"""
    <div class="card">
      <h2>Supporting behavioral acquisition (separate)</h2>
      <p class="note">A separate, saved acquisition. It was captured under
        mode <strong>{_e(config.get('data_mode'))}</strong> and is shown from
        disk &mdash; it is not a live connection. It does not establish OKX
        ownership, customer-deposit status, fraud, common control, or any
        strong inference.</p>
      <dl class="kv">
        <dt>Run id</dt><dd>{_copyable(manifest.get('run_id'), keep=18, label='run id')}</dd>
        <dt>Rows found</dt><dd>{_e(manifest.get('rows_found'))}</dd>
        <dt>Incoming / outgoing</dt>
        <dd>{_e(counts.get('incoming', 0))} / {_e(counts.get('outgoing', 0))}</dd>
        <dt>Window</dt><dd>{_e(query.get('analysis_start'))} \u2192
          {_e(query.get('analysis_cutoff'))}</dd>
        <dt>Requests used</dt><dd>{_e(manifest.get('requests_used'))}</dd>
        <dt>Truncated by request budget</dt>
        <dd>{_e(manifest.get('truncated_by_request_budget'))}</dd>
      </dl>
      {stored_rows}
      {f"<p class='note'>{_e(caveat)}</p>" if caveat else ""}
      <p class="note">Asset shown as {_e(symbol)} base units; exact integers,
        never parsed into a JavaScript number.</p>
    </div>"""


def _actions_section(view: DemoView) -> str:
    """A small final action row. Every saved report, the raw JSON, and the
    browser print/PDF path stay available; nothing moves behind hover."""

    pid = view.preset.id
    links = [
        f"<a class='btn' href='/console/evidence/{_attr(pid)}' target='_blank' "
        "rel='noopener'>Evidence report</a>"
    ]
    if view.has_comparison:
        links.append(
            f"<a class='btn secondary' href='/console/comparison/{_attr(pid)}' "
            "target='_blank' rel='noopener'>Comparison report</a>"
        )
    if view.has_outcome:
        links.append(
            f"<a class='btn secondary' href='/console/outcome/{_attr(pid)}' "
            "target='_blank' rel='noopener'>Outcome report</a>"
        )
    links.append(
        f"<a class='btn secondary' href='/console/trace/{_attr(pid)}' target='_blank' "
        "rel='noopener' download>Download JSON</a>"
    )
    links.append(
        "<button class='secondary print' type='button'>Print / Save PDF</button>"
    )
    missing = []
    if not view.has_outcome:
        missing.append("a Stage 3A service-outcome record")
    if not view.has_comparison:
        missing.append("a Stage 2 comparison report")
    note = ""
    if missing:
        note = (
            "<p class='note'>Not recorded for this preset: no "
            + " and no ".join(missing)
            + ". That is expected for a trace-only or synthetic fixture; the "
            "summary is drawn from the trace's own branch endings.</p>"
        )
    return f"""
    <section class="card no-print" id="actions" aria-labelledby="actions-h">
      <h2 id="actions-h">Actions</h2>
      <div class="actions-row">{''.join(links)}</div>
      <p class="note">Reports are deterministic HTML built from the same saved
        result and print to PDF from any browser.</p>
      {note}
    </section>"""


def _evidence_uncertainty_section(view: DemoView) -> str:
    """One compact section, three segmented panels. All panels stay in the DOM
    so provenance, every status axis, and every limitation remain reachable,
    searchable, and printable; only visibility changes."""

    return f"""
    <section class="card" id="evidence" aria-labelledby="evidence-h">
      <h2 id="evidence-h">Evidence &amp; uncertainty</h2>
      <div class="tabs" data-tabs>
        <div class="tablist" role="tablist"
          aria-label="Evidence, uncertainty, and limitations">
          <button type="button" class="tab" role="tab" id="tab-evidence"
            aria-controls="panel-evidence" aria-selected="true">Evidence</button>
          <button type="button" class="tab" role="tab" id="tab-uncertainty"
            aria-controls="panel-uncertainty" aria-selected="false"
            tabindex="-1">Uncertainty</button>
          <button type="button" class="tab" role="tab" id="tab-limitations"
            aria-controls="panel-limitations" aria-selected="false"
            tabindex="-1">Limitations</button>
        </div>
        <div class="tabpanel" id="panel-evidence" role="tabpanel"
          aria-labelledby="tab-evidence">{_provenance_panel(view)}</div>
        <div class="tabpanel" id="panel-uncertainty" role="tabpanel"
          aria-labelledby="tab-uncertainty">{_uncertainty_panel(view)}</div>
        <div class="tabpanel" id="panel-limitations" role="tabpanel"
          aria-labelledby="tab-limitations">{_limitations_panel(view)}</div>
      </div>
    </section>"""


# --------------------------------------------------------------------------
# Shared site shell, landing page, dashboard
# --------------------------------------------------------------------------


def _nav(active: str) -> str:
    items = (
        ("/", "Overview"),
        ("/console", "Demo"),
        ("/graph", "Fund flow"),
        ("/dashboard", "Dashboard"),
    )
    links = []
    for href, label in items:
        is_active = active == href
        cls = "nav-link active" if is_active else "nav-link"
        current = " aria-current='page'" if is_active else ""
        links.append(f"<a class='{cls}' href='{_attr(href)}'{current}>{_e(label)}</a>")
    return "<nav class='sitenav' aria-label='Sections'>" + "".join(links) + "</nav>"


def _site_footer() -> str:
    return (
        "<div class=\"footer\" role=\"contentinfo\"><p>Read-only local prototype."
        " No model is required for any result, and none has been trained."
        " Recorded and synthetic examples are labelled as such. This is"
        " investigative material for human review, not a legal instrument, and"
        " it establishes no authority to restrict any account.</p></div>"
    )


def _page_shell(*, title: str, active: str, mode_chip: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>{_THEME_INIT}</script>
<title>{_e(title)}</title>
<style>{STYLE}</style></head>
<body>
<a class="skip-link" href="#result">Skip to content</a>
<p id="copy-status" class="sr-only" role="status" aria-live="polite"></p>
<div class="topbar" role="banner">
  <h1>{_e(title)}</h1>
  {mode_chip}
  <span class="chip">LOCAL PROTOTYPE &middot; READ ONLY</span>
  <span class="spacer"></span>
  {_nav(active)}
  <button class="theme-toggle" type="button">Theme: Auto</button>
  <span class="chip" id="health">API checking\u2026</span>
</div>
<div class="wrap">
{body}
  {_site_footer()}
</div>
<script>{_SCRIPT}</script>
</body></html>"""


_LANDING_FEATURES = (
    (
        "Chronological tracing",
        "Follows transfers forward in time, carrying event and path state, "
        "instead of a lifetime shortest path.",
    ),
    (
        "Service outcomes, not guesses",
        "Each claim is classified as supported destination, strong inference, "
        "candidate lead, or unknown/blocked, with reason codes.",
    ),
    (
        "Evidence with provenance",
        "Every label carries its source, hash, reviewer, and dated validity "
        "window; nothing is asserted without it.",
    ),
    (
        "Eight independent axes",
        "Execution, coverage, attribution, case linkage, acquisition, "
        "verification, event identity, and ordering, never one score.",
    ),
    (
        "Data-mode honesty",
        "LIVE, RECORDED PUBLIC, and SYNTHETIC stay visible; a saved file never "
        "wears a LIVE badge.",
    ),
    (
        "Limitations first",
        "Unknown ownership, allocation_unknown, partial acquisition, and "
        "unverified ordering stay on screen.",
    ),
    (
        "Deterministic reports",
        "The same saved result renders both the screen and a printable-to-PDF "
        "evidence report.",
    ),
    (
        "Read-only and privacy-preserving",
        "It does not identify a person, assert fraud, estimate a recovery, or "
        "execute a freeze.",
    ),
)

_LANDING_NOT = (
    "Identify a person from an address.",
    "Assert fraud or guilt.",
    "Estimate recoverable money.",
    "Execute or imply a freeze.",
    "Turn a candidate into a verified service label, or behavioural "
    "resemblance into ownership.",
    "Present recorded data as live, or invent a service, transaction, or "
    "probability.",
)


def render_landing_html() -> str:
    """The overview page: what the prototype is for and what it refuses to do."""

    cards = "".join(
        f"<div class='feature'><h3>{_e(title)}</h3><p>{_e(detail)}</p></div>"
        for title, detail in _LANDING_FEATURES
    )
    nots = "".join(f"<li>{_e(item)}</li>" for item in _LANDING_NOT)
    body = f"""
  <div class="hero">
    <h2>Turn a transfer into reviewable evidence &mdash; without overclaiming.</h2>
    <p>An evidence-first triage prototype for TRON / USDT-TRC20. It follows
      supported activity to a receiving service boundary, explains exactly what
      is known, and keeps what is unknown visible.</p>
    <div class="cta-row">
      <a class="btn" href="/console">Open the recorded demo</a>
      <a class="btn secondary" href="/dashboard">View the dashboard</a>
    </div>
  </div>
  {_walkthrough_card(None, with_result=False)}
  <div class="card"><h2>Key features</h2>
    <div class="feature-grid">{cards}</div>
  </div>
  <div class="card"><h2>What it will not do</h2>
    <ul class="notlist">{nots}</ul>
  </div>
  <div class="card"><h2>Run it</h2>
    <p class="note">Start the local prototype with <code>make demo</code>, then
      open <code>/console</code> for the demo and <code>/dashboard</code> for
      status. Everything is offline, read-only, and deterministic.</p>
  </div>"""
    return _page_shell(
        title="Crypto Attribution Triage",
        active="/",
        mode_chip=_chip("EVIDENCE-FIRST"),
        body=body,
    )


def render_fund_flow_html(
    *,
    view: DemoView | None,
    presets: Sequence[Preset],
    message: str | None = None,
) -> str:
    """The fund-flow graph page for one saved preset. Pure function of its inputs."""

    graph = build_fund_flow(view.trace) if view is not None and view.trace else None
    if view is None:
        mode_chip = _chip("NO RESULT SELECTED", "warn")
        mode_note = ""
    else:
        mode_chip = _mode_chip(view.data_mode)
        capture = view.capture_data_mode
        mode_note = f"Presented as {view.data_mode}"
        if capture and capture != view.data_mode:
            mode_note += f" (captured as {capture})"
        mode_note += ": saved evidence, not a live trace."
    links = [
        (f"/graph?preset={p.id}", p.title, view is not None and p.id == view.preset.id)
        for p in presets
    ]
    body = (
        f"<style>{GRAPH_STYLE}</style>"
        + render_fund_flow_body(
            graph=graph,
            trace=view.trace if view is not None else None,
            preset_links=links,
            mode_note=mode_note,
            message=message or (view.error if view is not None else None),
        )
        + f"<script>{GRAPH_SCRIPT}</script>"
    )
    return _page_shell(
        title="Crypto Attribution Triage",
        active="/graph",
        mode_chip=mode_chip,
        body=body,
    )


def _tile(value: Any, label: str) -> str:
    return (
        f"<div class='tile'><div class='big'>{_e(value)}</div>"
        f"<div class='lbl'>{_e(label)}</div></div>"
    )


def _capability_card(capabilities: Sequence[Mapping[str, Any]] | None) -> str:
    if not capabilities:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{_e(cap.get('label'))}</td>"
        f"<td>{_chip(str(cap.get('status')), 'st-' + str(cap.get('status')))}</td>"
        f"<td>{_e(cap.get('detail'))}</td>"
        "</tr>"
        for cap in capabilities
    )
    return f"""
  <div class="card"><h2>Capabilities and status</h2>
    <div class="table-scroll"><table><thead><tr>
      <th>Capability</th><th>Status</th><th>Basis</th>
    </tr></thead><tbody>{rows}</tbody></table></div>
    <p class="note">Statuses are derived from the code and the saved readiness
      report, not from a roadmap. <strong>Blocked</strong> means a dependency
      does not exist yet; <strong>not built</strong> means no code path exists.
      No metric is shown for a model that has not been trained.</p>
  </div>"""


def _integrity_card(presets_summary: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for row in presets_summary:
        integrity = row.get("integrity") or {}
        if not integrity.get("available"):
            continue
        passed = integrity.get("failed", 0) == 0 and integrity.get("missing", 0) == 0
        verdict = (
            _chip("all match", "st-available")
            if passed
            else _chip("check failed", "st-blocked")
        )
        rows.append(
            "<tr>"
            f"<td><a href='/console?preset={_attr(row.get('id'))}'>"
            f"{_e(row.get('title'))}</a></td>"
            f"<td class='num'>{_e(integrity.get('checked'))}</td>"
            f"<td class='num'>{_e(integrity.get('ok'))}</td>"
            f"<td class='num'>{_e(integrity.get('failed'))}</td>"
            f"<td class='num'>{_e(integrity.get('missing'))}</td>"
            f"<td>{verdict}</td>"
            "</tr>"
        )
    if not rows:
        return """
  <div class="card"><h2>Saved-bundle integrity</h2>
    <p class="empty">Not available: no saved bundle with a hash manifest is
      present on this checkout.</p>
    <p class="note">This is an absent optional bundle, not a failed integrity
      check.</p>
  </div>"""
    return f"""
  <div class="card"><h2>Saved-bundle integrity</h2>
    <div class="table-scroll"><table><thead><tr>
      <th>Saved run</th><th>Files</th><th>Match</th><th>Mismatch</th>
      <th>Missing</th><th>Verdict</th>
    </tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <p class="note">Each manifest file's SHA-256 is re-computed and compared to
      the digest recorded at run time. A match shows the files are unchanged
      since the run; it is not proof that the attribution is correct.</p>
  </div>"""


def render_dashboard_html(
    *,
    presets_summary: Sequence[Mapping[str, Any]],
    capabilities: Sequence[Mapping[str, Any]] | None = None,
    readiness: Mapping[str, Any] | None = None,
    wallet_states: Mapping[str, int] | None = None,
    wallet_rows: Sequence[Mapping[str, Any]] | None = None,
    anomaly_evaluation: Mapping[str, Any] | None = None,
    extra_content: str = "",
) -> str:
    """Status overview over the saved runs, readiness, and evaluation registry."""

    total = len(presets_summary)
    by_mode: dict[str, int] = {}
    by_category: dict[str, int] = {}
    total_transfers = 0
    total_unresolved = 0
    for row in presets_summary:
        mode = str(row.get("data_mode") or "UNKNOWN")
        by_mode[mode] = by_mode.get(mode, 0) + 1
        category = str(row.get("outcome_category") or "not_recorded")
        by_category[category] = by_category.get(category, 0) + 1
        total_transfers += int(row.get("observed_transfers") or 0)
        total_unresolved += int(row.get("unresolved") or 0)

    tiles = "".join(
        [
            _tile(total, "Saved runs"),
            _tile(by_mode.get("RECORDED_PUBLIC", 0), "Recorded public"),
            _tile(by_mode.get("SYNTHETIC", 0), "Synthetic"),
            _tile(total_transfers, "Observed transfers"),
            _tile(total_unresolved, "Unresolved endings"),
        ]
    )
    mode_key = " ".join(
        f"{_mode_chip(m)} <span class='note'>{_e(n)}</span>"
        for m, n in sorted(by_mode.items())
    )
    category_rows = "".join(
        f"<li>{_e(CATEGORY_LABELS.get(cat, cat))}: <b>{_e(count)}</b></li>"
        for cat, count in sorted(by_category.items())
    )

    run_rows = []
    for row in presets_summary:
        mode = str(row.get("data_mode") or "UNKNOWN")
        category_value = row.get("outcome_category")
        service = row.get("outcome_service")
        if category_value:
            outcome_text = CATEGORY_LABELS.get(str(category_value), str(category_value))
            if service:
                outcome_text = f"{outcome_text}: {service}"
        else:
            outcome_text = "Not recorded"
        run_rows.append(
            "<tr>"
            f"<td><a href='/console?preset={_attr(row.get('id'))}'>"
            f"{_e(row.get('title'))}</a></td>"
            f"<td>{_mode_chip(mode)}</td>"
            f"<td>{_copyable(row.get('address'), keep=18)}</td>"
            f"<td class='num'>{_e(row.get('observed_transfers'))}</td>"
            f"<td class='num'>{_e(row.get('branch_endings'))}</td>"
            f"<td class='num'>{_e(row.get('unresolved'))}</td>"
            f"<td>{_e(outcome_text)}</td>"
            "</tr>"
        )
    runs_table = (
        "<div class='table-scroll'><table><thead><tr>"
        "<th>Saved run</th><th>Mode</th><th>Seed</th><th>Transfers</th>"
        "<th>Branches</th><th>Unresolved</th><th>Outcome</th>"
        "</tr></thead><tbody>"
        + "".join(run_rows)
        + "</tbody></table></div>"
    )

    body = f"""
  <div class="hero">
    <h2>Status overview</h2>
    <p>What saved runs exist, what they concluded, and how ready the
      experimental evaluation corpus is. Every figure is read from disk; none is
      a model metric.</p>
  </div>
  <section class="card" aria-labelledby="dash-saved-h">
    <h2 id="dash-saved-h">Saved evidence</h2>
    <div class="tiles">{tiles}</div>
    <h3>Data modes</h3>
    <div class="mode-key">{mode_key}</div>
    <p class="note">LIVE, RECORDED PUBLIC, and SYNTHETIC are never mixed. A saved
      file is always shown as RECORDED PUBLIC, whatever mode captured it.</p>
    <h3>Saved runs</h3>
    {runs_table}
    <p class="note">Open any row to see its full result in the demo console. The
      dashboard never duplicates the investigator view.</p>
    <h3>Outcomes on file</h3>
    <ul class="tight">{category_rows}</ul>
    <p class="note">Categories are per claim and are never collapsed into one
      confidence score. "Not recorded" means no Stage 3A record is saved for
      that run.</p>
    {_limitations_card_common()}
  </section>
  <section aria-labelledby="dash-ready-h">
    <h2 class="section-h" id="dash-ready-h">Evaluation readiness</h2>
    {_readiness_card(readiness, wallet_states, wallet_rows)}
    {_anomaly_evaluation_card(anomaly_evaluation)}
  </section>
  {_capability_card(capabilities)}
  {_integrity_card(presets_summary)}
  {extra_content}"""
    return _page_shell(
        title="Crypto Attribution Triage",
        active="/dashboard",
        mode_chip=_chip("DASHBOARD"),
        body=body,
    )


def _limitations_card_common() -> str:
    """A dashboard-safe limitations card with no preset-specific claims."""

    items = (
        "An observed path establishes a sequence of transfers, not ownership "
        "of fungible units; a case-associated amount stays allocation_unknown.",
        "No anomaly model has been trained, and none is required for the "
        "results shown.",
        "Recorded public data is not live chain data.",
        "Synthetic fixtures are not evidence about any real service.",
        "A candidate is a lead, not a verified service label.",
    )
    return f"""
    <h3>Standing limitations</h3>{_list(items, empty="")}"""


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------


def render_console_html(
    *,
    view: DemoView | None,
    presets: Sequence[Preset],
    readiness: Mapping[str, Any] | None = None,
    wallet_states: Mapping[str, int] | None = None,
    wallet_rows: Sequence[Mapping[str, Any]] | None = None,
    anomaly_evaluation: Mapping[str, Any] | None = None,
    address_query: str = "",
    message: str | None = None,
    message_kind: str = "info",
) -> str:
    """Render the whole console page. Pure function of its inputs."""

    mode_chip = _mode_chip(view.data_mode) if view else _chip("NO RESULT SELECTED", "warn")
    title = "Crypto Attribution Triage"

    if view is not None and view.error:
        main = (
            "<div class='card'><h2>No saved result</h2>"
            f"<p>{_e(view.error)}</p>"
            "<p class='note'><strong>What this does not mean:</strong> it is not "
            "a statement that the address had no activity. This read-only "
            "prototype only opens evidence that was already saved.</p>"
            "<p class='note'><strong>Next step:</strong> pick a demo example "
            "from the sidebar, or enter an address that has a saved result.</p>"
            "</div>"
        )
    elif view is not None and view.trace is not None:
        # Five primary sections, in reading order: Result, Path, Timeline,
        # Evidence & uncertainty, Actions.
        main = (
            _result_card(view)
            + _path_section(view)
            + _timeline_section(view)
            + _evidence_uncertainty_section(view)
            + _actions_section(view)
        )
    else:
        main = (
            "<div class='card'><h2>Start here</h2>"
            "<p>Choose a demo example, or enter an address that has a saved "
            "result. This prototype opens already-saved evidence; it does not "
            "trace live and it does not identify a person.</p></div>"
        )

    alert = ""
    if message:
        alert = (
            f"<div class='card' style='border-left:5px solid "
            f"{'#7c4444' if message_kind == 'warn' else '#4a5568'}'>"
            f"<p style='margin:0'>{_e(message)}</p></div>"
        )

    warnings = ""
    if view is not None and view.warnings:
        warnings = (
            "<div class='card' style='border-left:5px solid #6a5c3f'>"
            + _list(view.warnings, empty="")
            + "</div>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>{_THEME_INIT}</script>
<title>{_e(title)}</title>
<style>{STYLE}</style></head>
<body>
<a class="skip-link" href="#result">Skip to result</a>
<p id="copy-status" class="sr-only" role="status" aria-live="polite"></p>
<div class="topbar" role="banner">
  <h1>{_e(title)}</h1>
  {mode_chip}
  <span class="chip">LOCAL PROTOTYPE &middot; READ ONLY</span>
  <span class="spacer"></span>
  {_nav("/console")}
  <button class="theme-toggle" type="button">Theme: Auto</button>
  <span class="chip" id="health">API checking\u2026</span>
</div>
<div class="wrap">
  <p class="lede">Evidence-first triage over saved results: what is known, what
    is inferred, what remains unknown. It never identifies a person, asserts
    fraud, estimates a recovery, or executes a freeze.</p>
  {alert}
  <div class="print-only">
    {_e(title)} &middot; {_e(view.preset.title) if view else "no preset"} &middot;
    mode {_e(view.data_mode) if view else "none"}
  </div>
  <div class="grid">
    <aside class="no-print" aria-label="Inputs and demo examples">
      {_input_card(view, address_query)}
      {_preset_card(presets, view)}
      <details class="layers">
        <summary>Experimental ML &amp; evaluation readiness</summary>
        <p class="note">Kept out of the investigation flow. No model affects any
          result above, and no model has been trained on real data.</p>
        {_readiness_card(readiness, wallet_states, wallet_rows)}
        {_anomaly_evaluation_card(anomaly_evaluation)}
      </details>
    </aside>
    <main id="result" aria-label="Investigation result">
      {warnings}
      {main}
    </main>
  </div>
  <div class="footer" role="contentinfo">
    <p>Read-only local prototype. No model is required for the result above,
      and none has been trained. Recorded and synthetic examples are labelled
      as such. This page is investigative material for human review, not a
      legal instrument, and it establishes no authority to restrict any
      account.</p>
  </div>
</div>
<script>{_SCRIPT}</script>
</body></html>"""
