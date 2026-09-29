"""The local investigator console: HTML pages over already-saved artifacts.

Read-only and offline. These routes read an allow-listed set of preset
artifacts (see ``app.services.demo_presets``) and the existing readiness
report. They do not require a database session, contact a provider, or accept
an arbitrary path, so the demo works on a laptop with no chain access and no
seeded login.

This is a deliberately narrow local prototype surface: it exposes only saved,
labelled public/synthetic evidence, never case data or private investigative
labels, which is why it is not behind the case-authorization dependency every
API case route carries. A production console would sit behind that same
authorization; this one has no case data to protect.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.settings import REPO_ROOT, Settings, get_settings
from app.reports.console import (
    render_console_html,
    render_dashboard_html,
    render_fund_flow_html,
    render_landing_html,
)
from app.reports.evidence import render_evidence_html
from app.reports.fund_flow import build_fund_flow
from app.services.addresses import AddressValidationError, canonicalize
from app.services.demo_presets import (
    DemoView,
    PresetPathError,
    all_presets,
    find_preset_by_address,
    has_recorded_cctp_live_validation,
    load_anomaly_evaluation,
    load_evaluation_wallet_states,
    load_evaluation_wallets_view,
    load_preset,
    load_readiness,
    preset_by_id,
    summarize_presets,
)
from app.services.operational_status import capability_details, evm_network_states

router = APIRouter(prefix="/console", tags=["console"])

#: The overview and dashboard pages. Registered alongside the console, and
#: (like it) only in non-prod, because they read the same saved demo artifacts.
site_router = APIRouter(tags=["site"])
NEIGHBORHOOD_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
NEIGHBORHOOD_RUNS_DIR = REPO_ROOT / "var" / "vasp-neighborhood"


@site_router.get("/", response_class=HTMLResponse)
def site_landing() -> HTMLResponse:
    """The overview page explaining the prototype's key features."""

    return HTMLResponse(render_landing_html())


@site_router.get("/neighborhood/vasp/{run_id}", response_class=HTMLResponse)
def site_vasp_neighborhood(run_id: str) -> HTMLResponse:
    """A saved candidate-neighborhood report, separate from trace results."""
    if not NEIGHBORHOOD_RUN_ID.fullmatch(run_id):
        return _not_found("No saved candidate-neighborhood report exists for this run.")
    directory = (NEIGHBORHOOD_RUNS_DIR / run_id).resolve()
    if NEIGHBORHOOD_RUNS_DIR.resolve() not in directory.parents:
        return _not_found("No saved candidate-neighborhood report exists for this run.")
    report_path = directory / "report.json"
    manifest_path = directory / "manifest.json"
    if not report_path.is_file() or not manifest_path.is_file():
        return _not_found("No saved candidate-neighborhood report exists for this run.")
    try:
        report = json.loads(report_path.read_text())
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return _not_found("The saved candidate-neighborhood report is unreadable.")
    if not isinstance(report, dict) or report.get("report_type") != "vasp_candidate_neighborhood":
        return _not_found("The saved report is not a candidate-neighborhood report.")
    return HTMLResponse(_render_neighborhood_report(report, manifest))


def _render_neighborhood_report(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    anchor = report.get("anchor") or {}
    coverage = report.get("coverage") or {}

    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else "unknown"), quote=True)

    candidate_rows = []
    for candidate in report.get("candidates") or []:
        feature_rows = "".join(
            f"<li><code>{esc(key)}</code>: {esc(value)}</li>"
            for key, value in sorted((candidate.get("features") or {}).items())
        )
        refs = "".join(
            f"<li><code>{esc(ref)}</code></li>"
            for ref in candidate.get("evidence_references", [])
        )
        candidate_rows.append(
            "<section class='candidate'><h3>Candidate relationship: "
            f"{esc(candidate.get('relationship_type'))}</h3>"
            f"<p><strong>Address:</strong> <code>{esc(candidate.get('address'))}</code></p>"
            f"<p><strong>Review:</strong> {esc(candidate.get('review_status'))}; "
            f"human-reviewed: {esc(candidate.get('human_reviewed'))}</p>"
            f"<p>{esc(candidate.get('not_service_control_reason'))}</p>"
            f"<h4>Observed features</h4><ul>{feature_rows}</ul>"
            f"<h4>Evidence references</h4><ul>{refs}</ul></section>"
        )
    address_context = "".join(
        f"<li><code>{esc(row.get('address'))}</code> — "
        f"<code>{esc(row.get('event_reference'))}</code>: "
        f"{esc(row.get('reason'))}</li>"
        for row in report.get("address_only_context", [])
    )
    limitations = "".join(
        f"<li>{esc(item)}</li>" for item in report.get("limitations", [])
    )
    styles = (
        "body{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;"
        "padding:0 1rem;color:#20242a}"
        "section{border:1px solid #cbd0d6;border-radius:8px;padding:1rem;margin:1rem 0}"
        ".candidate{border-left:5px solid #b7791f;background:#fffaf0}"
        "code{overflow-wrap:anywhere}.mode{font-weight:700}"
    )
    empty_candidates = (
        "<p>No candidate met a reported relationship rule in this bounded "
        "observation window.</p>"
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Candidate neighborhood</title>"
        f"<style>{styles}</style></head><body>"
        "<p><a href='/dashboard'>Back to dashboard</a></p>"
        "<h1>VASP candidate neighborhood</h1>"
        "<p class='mode'>RECORDED PUBLIC · REPORT ONLY · POLICY "
        f"{esc(report.get('policy_version'))}</p>"
        "<section><h2>Reviewed service_control anchor</h2>"
        f"<p><strong>{esc(anchor.get('entity_name'))}</strong> — "
        f"<code>{esc(anchor.get('address'))}</code></p>"
        f"<p>Claim: {esc(anchor.get('assertion_type'))}; "
        f"review: {esc(anchor.get('review_state'))}; valid only from "
        f"{esc(anchor.get('valid_from'))} to {esc(anchor.get('valid_to'))}.</p>"
        f"<p>Source: {esc(anchor.get('source_reference'))}; source hash: "
        f"<code>{esc(anchor.get('source_hash'))}</code></p></section>"
        "<h2>Candidate relationships (not verified service ownership)</h2>"
        f"{''.join(candidate_rows) or empty_candidates}"
        "<h2>Address-only context outside anchor scope</h2>"
        f"<ul>{address_context or '<li>None recorded.</li>'}</ul>"
        "<h2>Coverage and limits</h2>"
        f"<p>Complete within scope: {esc(coverage.get('complete'))}; "
        f"requests: {esc(coverage.get('requests_used'))}/"
        f"{esc(coverage.get('max_requests'))}; addresses examined: "
        f"{esc(coverage.get('addresses_examined'))}/"
        f"{esc(coverage.get('address_limit'))}.</p>"
        f"<ul>{limitations or '<li>No additional limitations recorded.</li>'}</ul>"
        "<p><strong>Not established:</strong> wallet ownership, customer identity, "
        "common control, criminality, or unique victim-fund allocation. This is "
        "not a wallet ownership cluster.</p>"
        f"<p>Manifest mode: {esc(manifest.get('data_mode'))}; hash caveat: "
        f"{esc(manifest.get('caveat'))}</p></body></html>"
    )


@site_router.get("/dashboard", response_class=HTMLResponse)
def site_dashboard(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """Status overview over saved runs, readiness, and the evaluation registry."""

    presets = summarize_presets()
    readiness = load_readiness()
    anomaly_evaluation = load_anomaly_evaluation()
    capabilities = capability_details(
        readiness=readiness,
        saved_run_count=len([p for p in presets if p.get("has_trace")]),
        live_key_configured=bool(settings.tron_api_key),
        configured_data_mode=settings.data_mode.value,
        anomaly_evaluation=anomaly_evaluation,
        evm_networks=evm_network_states(settings),
        cctp_historical_recorded=has_recorded_cctp_live_validation(),
    )
    neighborhood_ids = (
        "20260926T143630Z-aab422",
        "20260926T142326Z-8ac99c",
    )
    neighborhood_links = [
        f"<li><a href='/neighborhood/vasp/{run_id}'>"
        f"Open saved candidate-neighborhood report {run_id}</a></li>"
        for run_id in neighborhood_ids
        if (NEIGHBORHOOD_RUNS_DIR / run_id / "report.json").is_file()
        and (NEIGHBORHOOD_RUNS_DIR / run_id / "manifest.json").is_file()
    ]
    neighborhood_card = ""
    if neighborhood_links:
        neighborhood_card = (
            "<section class='card'><h2>Candidate neighborhoods</h2><ul>"
            + "".join(neighborhood_links)
            + "</ul><p class='note'>Candidate observations only; not wallet ownership clusters "
            "or verified service-control claims.</p></section>"
        )
    dashboard_html = render_dashboard_html(
        presets_summary=presets,
        capabilities=capabilities,
        readiness=readiness,
        wallet_states=load_evaluation_wallet_states(),
        wallet_rows=load_evaluation_wallets_view(),
        anomaly_evaluation=anomaly_evaluation,
        extra_content=neighborhood_card,
    )
    return HTMLResponse(dashboard_html)


@site_router.get("/graph", response_class=HTMLResponse)
def site_fund_flow(preset: str | None = Query(default=None)) -> HTMLResponse:
    """Fund-flow graph of one saved result's observed transfers."""

    presets = all_presets()
    if preset:
        view = _view_or_404(preset)
        if view is None:
            return HTMLResponse(
                render_fund_flow_html(
                    view=None,
                    presets=presets,
                    message=f"Unknown preset {preset!r}. Pick one of the saved examples.",
                ),
                status_code=404,
            )
    else:
        view = load_preset(presets[0])
    return HTMLResponse(render_fund_flow_html(view=view, presets=presets))


_MISSING_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not found \u2014 Crypto Attribution Triage</title>
<style>
body { font: 15px/1.5 system-ui, sans-serif; margin: 0; background: #f2f2f3; color: #1b1d21; }
.box { max-width: 640px; margin: 60px auto; background: #fff; border: 1px solid #d6d8dc;
       border-radius: 8px; padding: 24px; }
h1 { font-size: 18px; margin-top: 0; }
p.note { color: #5a5e66; font-size: 13px; }
a { color: #4a5568; }
</style></head><body><div class="box">
<h1>No saved result here</h1>
<p>%s</p>
<p class="note"><strong>What this does not mean:</strong> a missing saved
artifact is not a finding about the case; it only says this report was not
stored for this preset.</p>
<p><a href="/console">\u2190 Back to the console</a></p>
</div></body></html>"""


def _not_found(message: str) -> HTMLResponse:
    return HTMLResponse(_MISSING_PAGE % html.escape(message), status_code=404)


def _view_or_404(preset_id: str) -> DemoView | None:
    preset = preset_by_id(preset_id)
    if preset is None:
        return None
    try:
        return load_preset(preset)
    except PresetPathError:
        return None


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def console_index(
    request: Request,
    preset: str | None = Query(default=None),
    address: str | None = Query(default=None),
) -> HTMLResponse:
    """The main investigator screen."""

    message: str | None = None
    message_kind = "info"
    view: DemoView | None

    if address and address.strip():
        raw = address.strip()
        try:
            canonical = canonicalize("tron", raw).canonical
        except AddressValidationError as exc:
            # A malformed address is a different fact from "not on file".
            view = None
            message = (
                f"{raw!r} is not a valid TRON address: {exc}. "
                "No lookup was performed, and this says nothing about whether "
                "the address was ever used. Check the address and try again."
            )
            message_kind = "warn"
        else:
            match = find_preset_by_address(canonical) or find_preset_by_address(raw)
            if match is None:
                view = None
                message = (
                    f"No saved result matches {canonical}. This does not mean "
                    "there was no activity: it means no evidence for this "
                    "address was saved. This read-only prototype does not trace "
                    "live, so it cannot look the address up now. Pick a saved "
                    "demo example instead."
                )
                message_kind = "warn"
            else:
                view = load_preset(match)
    elif preset:
        view = _view_or_404(preset)
        if view is None:
            message = f"Unknown preset {preset!r}. Pick one of the saved demo examples."
            message_kind = "warn"
    else:
        view = load_preset(all_presets()[0])

    return HTMLResponse(
        render_console_html(
            view=view,
            presets=all_presets(),
            readiness=load_readiness(),
            wallet_states=load_evaluation_wallet_states(),
            wallet_rows=load_evaluation_wallets_view(),
            anomaly_evaluation=load_anomaly_evaluation(),
            address_query=address or "",
            message=message,
            message_kind=message_kind,
        )
    )


@router.get("/evidence/{preset_id}", response_class=HTMLResponse)
def console_evidence(preset_id: str, request: Request) -> HTMLResponse:
    """The saved deterministic evidence report, or one rendered from the trace."""

    view = _view_or_404(preset_id)
    if view is None or view.trace is None:
        return _not_found("No saved trace result exists for this preset.")
    if view.report_path is not None and view.report_path.is_file():
        return HTMLResponse(view.report_path.read_text())
    try:
        return HTMLResponse(render_evidence_html(view.trace, request_id=f"console-{preset_id}"))
    except (KeyError, TypeError, ValueError):
        # An older saved trace can predate a newer report field. Say so rather
        # than turning the gap into a server error or an empty page.
        return _not_found(
            "This saved trace uses an older schema that the printable report "
            "cannot render field-for-field. The console summary above is still "
            "drawn from the saved result."
        )


@router.get("/comparison/{preset_id}", response_class=HTMLResponse)
def console_comparison(preset_id: str) -> HTMLResponse:
    """The saved Stage 2 comparison report."""

    view = _view_or_404(preset_id)
    if view is None:
        return _not_found("Unknown preset.")
    path: Path | None = view.comparison_html_path
    if path is not None and path.is_file():
        return HTMLResponse(path.read_text())
    return _not_found("No saved comparison report exists for this preset.")


@router.get("/outcome/{preset_id}", response_class=HTMLResponse)
def console_outcome(preset_id: str) -> HTMLResponse:
    """The saved Stage 3A service-outcome report."""

    view = _view_or_404(preset_id)
    if view is None:
        return _not_found("Unknown preset.")
    path: Path | None = view.outcome_html_path
    if path is not None and path.is_file():
        return HTMLResponse(path.read_text())
    return _not_found("No saved service-outcome report exists for this preset.")


@router.get("/trace/{preset_id}")
def console_trace(preset_id: str) -> JSONResponse:
    """The saved trace result, exactly as written, for offline reuse."""

    view = _view_or_404(preset_id)
    if view is None or view.trace is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "no saved trace result"}},
            status_code=404,
        )
    return JSONResponse(view.trace)


@router.get("/graph/{preset_id}")
def console_graph(preset_id: str) -> JSONResponse:
    """The fund-flow graph model (nodes, edges, branches) for one saved result."""

    view = _view_or_404(preset_id)
    if view is None or view.trace is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "no saved trace result"}},
            status_code=404,
        )
    return JSONResponse({"data_mode": view.data_mode, **build_fund_flow(view.trace).to_json()})


@router.get("/behavioral/{preset_id}")
def console_behavioral(preset_id: str) -> JSONResponse:
    """The saved behavioral-evidence bundle, exactly as written, for transparency."""

    view = _view_or_404(preset_id)
    if view is None or view.behavioral_evidence is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "no saved behavioral bundle"}},
            status_code=404,
        )
    return JSONResponse(view.behavioral_evidence)
