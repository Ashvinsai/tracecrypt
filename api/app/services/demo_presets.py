"""Server-side, allow-listed demo presets for the local investigator console.

This is a read-only presentation layer. It never contacts a network, never
reads the database, and never writes anything. Each preset names a fixed set
of already-saved artifacts under the repository's ``var/``/``data/`` trees;
the loader resolves those paths and refuses any path outside the repository
root, so the console cannot be pointed at an arbitrary file.

The console renders whatever the saved artifacts already say. It does not
recompute an attribution, promote a candidate, or invent a status: a preset
that has no Stage 3A outcome record simply has no outcome record, and the UI
shows the trace's own branch endings instead of a derived category.

Nothing here needs ML. The readiness summary reads the existing readiness
report output and repeats its "no model trained" statement rather than
implying a model exists.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.settings import REPO_ROOT


@dataclass(frozen=True)
class Preset:
    """One named, already-saved investigation result."""

    id: str
    title: str
    scenario: str
    data_mode: str
    address: str
    description: str
    trace: str
    manifest: str | None = None
    report: str | None = None
    outcome: str | None = None
    outcome_html: str | None = None
    comparison_json: str | None = None
    comparison_html: str | None = None
    behavioral_manifest: str | None = None
    behavioral_evidence: str | None = None
    required_artifacts: tuple[str, ...] = ()
    #: Human-readable scope note shown with the preset, never a verdict.
    scope_note: str = ""


PRESETS: tuple[Preset, ...] = (
    Preset(
        id="synthetic-multihop",
        title="Synthetic: multi-hop path with unresolved branches",
        scenario="limited",
        data_mode="SYNTHETIC",
        address="TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
        description=(
            "A fictional multi-hop walk that ends in a mix of outcomes: one "
            "branch reaches an invented service label, one is only a "
            "candidate, and two stop unresolved. Every address and service "
            "name here is deliberately fictional and must never be read as a "
            "fact about a real service."
        ),
        scope_note=(
            "Synthetic demonstration fixture. The unresolved branches are the "
            "honest part: an asset change, bridge, privacy mechanism, or "
            "opaque contract would look the same, so no continuation is "
            "assumed."
        ),
        trace="var/trace.json",
        report="var/trace-report.html",
    ),
    Preset(
        id="recorded-okx-direct",
        title="Recorded: 72.14 USDT transfer to an OKX disclosure address",
        scenario="supported",
        data_mode="RECORDED_PUBLIC",
        address="TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq",
        description=(
            "A receipt-verified 72.14 USDT-TRC20 seed transfer to an address "
            "named in OKX's own proof-of-reserves disclosure at the "
            "2026-08-10T15:59:54Z snapshot instant. The label is a dated "
            "service-control assertion, not evidence of who sent the transfer."
        ),
        scope_note=(
            "The OKX claim is scoped to a single snapshot instant, not an "
            "interval of continuing control. The sender's ownership and role "
            "remain unknown."
        ),
        trace="var/live-validation/20260920T090201Z-969305/trace.json",
        manifest="var/live-validation/20260920T090201Z-969305/manifest.json",
        report="var/live-validation/20260920T090201Z-969305/report.html",
        outcome="var/service-outcome/TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq/outcome.json",
        outcome_html="var/service-outcome/TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq/outcome.html",
        comparison_json=(
            "var/evidence-comparison/TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq/comparison.json"
        ),
        comparison_html=(
            "var/evidence-comparison/TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq/comparison.html"
        ),
        behavioral_manifest=(
            "var/collect-behavioral-evidence/20260920T165506Z-ee96cd/manifest.json"
        ),
        behavioral_evidence=(
            "var/collect-behavioral-evidence/20260920T165506Z-ee96cd/evidence.json"
        ),
    ),
)

PRESETS_BY_ID: dict[str, Preset] = {p.id: p for p in PRESETS}

LIVE_VALIDATION_DIR = "var/live-validation"


OPTIONAL_PRESETS: tuple[Preset, ...] = (
    Preset(
        id="recorded-tron-multihop",
        title="Recorded: public TRON multi-hop route to an OKX boundary",
        scenario="supported",
        data_mode="RECORDED_PUBLIC",
        address="TMqgVELUb5BxvA8LgMJnsQQWMg33Psvfqz",
        description=(
            "Public multi-hop TRON/TRC-20 validation route ending at a "
            "snapshot-supported OKX service boundary. Demonstrates chronological "
            "tracing; it does not assert criminality, common ownership, or unique "
            "fund ownership."
        ),
        scope_note=(
            "Upstream addresses are transaction participants only. The accepted "
            "OKX service-control claim applies at 2026-08-10T15:59:54Z only; "
            "ownership, deposit role, and case-value allocation remain unknown."
        ),
        trace="var/live-validation/20260926T103814Z-f75259/trace.json",
        manifest="var/live-validation/20260926T103814Z-f75259/manifest.json",
        report="var/live-validation/20260926T103814Z-f75259/report.html",
        required_artifacts=(
            "var/evidence-export/20260926T103814Z-f75259/manifest.json",
            "var/evidence-export/20260926T103814Z-f75259/evidence.json",
            "var/evidence-export/20260926T103814Z-f75259/evidence.html",
            "var/evidence-export/20260926T103814Z-f75259/evidence.pdf",
            "var/evidence-export/20260926T103814Z-f75259/transfers.csv",
            "var/evidence-export/20260926T103814Z-f75259/branch_endings.csv",
            "var/evidence-export/20260926T103814Z-f75259/labels.csv",
            "var/evidence-export/20260926T103814Z-f75259/limitations.csv",
        ),
    ),
)


def _available_optional_presets() -> tuple[Preset, ...]:
    def artifact_exists(relative: str | None) -> bool:
        path = _resolve(relative)
        return path is not None and path.is_file()

    return tuple(
        preset
        for preset in OPTIONAL_PRESETS
        if all(
            artifact_exists(path)
            for path in (
                preset.trace,
                preset.manifest,
                preset.report,
                *preset.required_artifacts,
            )
        )
    )


def _saved_preset(run_id: str, trace_path: Path, trace: dict[str, Any]) -> Preset | None:
    """Build a preset for a saved bundle discovered on disk.

    A saved bundle is always presented as RECORDED_PUBLIC, whatever mode the
    process was in when it captured the data. Presenting a file on disk under a
    LIVE badge would let recorded data masquerade as a live connection, which is
    exactly what the data-mode invariant forbids. The capture-time mode is kept
    in the description as a fact, not as a badge.
    """

    seed = trace.get("seed") or {}
    address = seed.get("address")
    if not isinstance(address, str) or not address:
        return None

    scope = trace.get("scope") or {}
    capture_mode = str(scope.get("data_mode") or "UNKNOWN")

    run_dir = trace_path.parent
    seed_outcome = REPO_ROOT / "var" / "service-outcome" / address
    seed_comparison = REPO_ROOT / "var" / "evidence-comparison" / address

    def _rel(path: Path) -> str | None:
        return str(path.relative_to(REPO_ROOT)) if path.is_file() else None

    return Preset(
        id=f"saved-{run_id}",
        title=f"Saved run {run_id}: {address[:10]}\u2026",
        scenario="saved",
        data_mode="RECORDED_PUBLIC",
        address=address,
        description=(
            f"A saved trace bundle captured under mode {capture_mode}, shown "
            "from disk. Not a live connection."
        ),
        scope_note=(
            f"Saved artifact from run {run_id}; capture-time mode was "
            f"{capture_mode}. The file is replayed, never re-fetched."
        ),
        trace=str(trace_path.relative_to(REPO_ROOT)),
        manifest=_rel(run_dir / "manifest.json"),
        report=_rel(run_dir / "report.html"),
        outcome=_rel(seed_outcome / "outcome.json"),
        outcome_html=_rel(seed_outcome / "outcome.html"),
        comparison_json=_rel(seed_comparison / "comparison.json"),
        comparison_html=_rel(seed_comparison / "comparison.html"),
    )


def discover_presets() -> tuple[Preset, ...]:
    """Saved bundles found on disk, excluding curated and available optional presets."""

    curated_paths = {p.trace for p in (*PRESETS, *_available_optional_presets())}
    found: list[Preset] = []
    root = REPO_ROOT / LIVE_VALIDATION_DIR
    if not root.is_dir():
        return ()
    for trace_path in sorted(root.glob("*/trace.json")):
        try:
            relative = str(trace_path.relative_to(REPO_ROOT))
        except ValueError:
            continue
        if relative in curated_paths:
            continue
        trace = _read_json(trace_path)
        if trace is None:
            continue
        preset = _saved_preset(trace_path.parent.name, trace_path, trace)
        if preset is not None:
            found.append(preset)
    return tuple(found)


def all_presets() -> tuple[Preset, ...]:
    """Curated presets first, available optional examples next, saved runs last."""

    return PRESETS + _available_optional_presets() + discover_presets()


def preset_by_id(preset_id: str) -> Preset | None:
    for preset in all_presets():
        if preset.id == preset_id:
            return preset
    return None


class PresetPathError(ValueError):
    """A preset named a path outside the repository root."""


def _resolve(relative: str | None) -> Path | None:
    if not relative:
        return None
    candidate = (REPO_ROOT / relative).resolve()
    if candidate != REPO_ROOT and REPO_ROOT not in candidate.parents:
        raise PresetPathError(f"preset path escapes the repository root: {relative!r}")
    return candidate


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass
class DemoView:
    """Everything the console needs to render one preset, plus its gaps.

    A missing artifact is recorded as a warning and, when the trace itself is
    missing, an ``error``. The console must show the gap, never an empty
    success.
    """

    preset: Preset
    trace: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    behavioral_manifest: dict[str, Any] | None = None
    behavioral_evidence: dict[str, Any] | None = None
    report_path: Path | None = None
    outcome_html_path: Path | None = None
    comparison_html_path: Path | None = None
    manifest_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def data_mode(self) -> str:
        """The mode this saved result is *presented* as.

        Always the preset's normalised mode: a saved bundle is RECORDED_PUBLIC
        regardless of the mode that captured it (``capture_data_mode`` keeps the
        original). Presenting a file on disk under a LIVE badge would let
        recorded data masquerade as a live connection.
        """

        return str(self.preset.data_mode)

    @property
    def capture_data_mode(self) -> str | None:
        """The mode recorded inside the saved trace, when it has one."""

        scope = (self.trace or {}).get("scope") or {}
        mode = scope.get("data_mode")
        return str(mode) if mode else None

    @property
    def has_outcome(self) -> bool:
        """A Stage 3A outcome is available, saved or renderable."""

        return self.outcome is not None or (
            self.outcome_html_path is not None and self.outcome_html_path.is_file()
        )

    @property
    def has_comparison(self) -> bool:
        return self.comparison is not None or (
            self.comparison_html_path is not None and self.comparison_html_path.is_file()
        )

    @property
    def has_report(self) -> bool:
        return self.report_path is not None and self.report_path.is_file()


def load_preset(preset: Preset | str) -> DemoView:
    """Load one preset from disk. Read-only; never raises for a missing file."""

    if isinstance(preset, str):
        try:
            preset = PRESETS_BY_ID[preset]
        except KeyError as exc:
            raise PresetPathError(f"unknown preset id: {preset!r}") from exc

    view = DemoView(preset=preset)
    view.trace = _read_json(_resolve(preset.trace))
    view.manifest = _read_json(_resolve(preset.manifest))
    view.outcome = _read_json(_resolve(preset.outcome))
    view.comparison = _read_json(_resolve(preset.comparison_json))
    view.behavioral_manifest = _read_json(_resolve(preset.behavioral_manifest))
    view.behavioral_evidence = _read_json(_resolve(preset.behavioral_evidence))

    view.report_path = _resolve(preset.report)
    view.outcome_html_path = _resolve(preset.outcome_html)
    view.comparison_html_path = _resolve(preset.comparison_html)
    view.manifest_path = _resolve(preset.manifest)

    if view.trace is None:
        view.error = (
            "No saved trace result was found for this preset. This prototype "
            "does not perform live tracing; run the offline build step that "
            "writes the saved artifacts first."
        )
    # Warn only when a preset *declares* an artifact and it is missing. A
    # trace-only preset (for example a synthetic fixture) has no Stage 2
    # comparison or Stage 3A outcome by design; that is a stated fact shown
    # neutrally in the report panel, not a warning. Missing configured
    # artifacts are the real anomalies and are reported loudly.
    if preset.outcome and view.outcome is None and not (
        view.outcome_html_path and view.outcome_html_path.is_file()
    ):
        view.warnings.append(f"Configured Stage 3A outcome is missing: {preset.outcome}")
    if (preset.comparison_json or preset.comparison_html) and not view.has_comparison:
        view.warnings.append("Configured Stage 2 comparison report is missing.")
    if preset.report and not view.has_report:
        view.warnings.append(
            f"Configured printable evidence report is missing: {preset.report}"
        )
    return view


def find_preset_by_address(address: str) -> Preset | None:
    """Match an entered address to a preset, exact and case-insensitive.

    No address is ever traced live by the console. An address with no saved
    result returns None; the caller must render that as "no saved result",
    never as "no activity".
    """

    needle = address.strip().lower()
    if not needle:
        return None
    for preset in all_presets():
        if preset.address.lower() == needle:
            return preset
    return None


# --------------------------------------------------------------------------
# Evaluation / ML readiness card (existing output only; no model is trained)
# --------------------------------------------------------------------------

READINESS_JSON = "var/evaluation-readiness/readiness.json"
#: The Stage 3C evaluation report written by scripts/anomaly_ranking.py
#: (--json-out). Kept separate from every trace/attribution artifact: it is a
#: model review-prioritization report, never evidence.
ANOMALY_EVALUATION_JSON = "var/anomaly-evaluation/report.json"
EVALUATION_WALLETS_CSV = "data/evaluation_wallets.csv"
EVALUATION_DATA_DIR = "data"
EVALUATION_EVIDENCE_ROOT = "var/collect-behavioral-evidence/by-wallet"


def load_evaluation_wallets_view() -> list[dict[str, Any]]:
    """One row per sourced evaluation wallet: category, review state, and
    whether a materializable evidence bundle exists. Read-only.

    Eligibility is checked directly against the filesystem by the existing
    ``domain_eligibility_for_wallet``; it is never inferred from acceptance or
    category, so a reviewer can see exactly why a wallet does or does not
    contribute a window.
    """

    registry = _resolve(EVALUATION_WALLETS_CSV)
    data_dir = _resolve(EVALUATION_DATA_DIR)
    evidence_root = _resolve(EVALUATION_EVIDENCE_ROOT)
    if (
        registry is None
        or data_dir is None
        or evidence_root is None
        or not registry.is_file()
    ):
        return []

    from app.services.evaluation_review import domain_eligibility_for_wallet
    from app.services.evaluation_wallets import load_evaluation_wallets

    rows: list[dict[str, Any]] = []
    for wallet in load_evaluation_wallets(registry):
        rows.append(
            {
                "network": wallet.network,
                "address": wallet.address,
                "control_category": wallet.control_category,
                "review_state": wallet.review_state,
                "data_mode": wallet.data_mode,
                "eligibility": domain_eligibility_for_wallet(
                    data_dir, evidence_root, wallet.network, wallet.address
                ),
            }
        )
    return rows


def has_recorded_successful_live_validation(*, network_key: str | None = None) -> bool:
    """Whether an intact bundle records a successful historical LIVE run.

    ``network_key`` narrows the search to one network's own bundles (e.g.
    ``"ethereum"``) -- a TRON bundle must never make an Ethereum-specific
    capability claim historical LIVE evidence it does not have, or vice versa.
    ``None`` keeps the original, network-agnostic behavior every existing
    caller relies on.
    """

    from app.services.operational_status import verify_manifest_hashes

    for manifest_path in (REPO_ROOT / LIVE_VALIDATION_DIR).glob("*/manifest.json"):
        manifest = _read_json(manifest_path)
        if not manifest:
            continue
        if (
            manifest.get("status") != "succeeded"
            or manifest.get("mode") != "live"
            or manifest.get("data_mode") != "LIVE"
        ):
            continue
        if network_key is not None and (manifest.get("query") or {}).get("network") != network_key:
            continue
        integrity = verify_manifest_hashes(manifest, manifest_path.parent)
        if integrity["checked"] > 0 and integrity["failed"] == 0 and integrity["missing"] == 0:
            return True
    return False


def has_recorded_cctp_live_validation() -> bool:
    """Whether an intact bundle records a successful historical CCTP V2 validation."""
    from app.services.operational_status import verify_manifest_hashes

    for manifest_path in (REPO_ROOT / LIVE_VALIDATION_DIR).glob("*/manifest.json"):
        manifest = _read_json(manifest_path)
        if not manifest:
            continue
        if (
            manifest.get("status") != "succeeded"
            or manifest.get("protocol") != "circle_cctp_v2"
        ):
            continue
        integrity = verify_manifest_hashes(manifest, manifest_path.parent)
        if integrity["checked"] > 0 and integrity["failed"] == 0 and integrity["missing"] == 0:
            return True
    return False


def load_readiness() -> dict[str, Any] | None:
    """Return the saved readiness report, or None if it has not been built."""

    return _read_json(_resolve(READINESS_JSON))


def load_anomaly_evaluation() -> dict[str, Any] | None:
    """Return the saved Stage 3C anomaly-evaluation report, or None.

    Read-only, allow-listed path. Nothing is fit or scored in the request path:
    the console only ever displays a report a CLI run already wrote.
    """

    return _read_json(_resolve(ANOMALY_EVALUATION_JSON))


def load_evaluation_wallet_states() -> dict[str, int]:
    """Count review states in the evaluation-wallet registry, read-only.

    Reads with ``csv.DictReader`` and never imports the writer service, so the
    console cannot accidentally migrate or rewrite the registry.
    """

    path = _resolve(EVALUATION_WALLETS_CSV)
    counts: dict[str, int] = {}
    if path is None or not path.is_file():
        return counts
    try:
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                state = (row.get("review_state") or "unknown").strip() or "unknown"
                counts[state] = counts.get(state, 0) + 1
    except OSError:
        return counts
    return counts


def summarize_presets() -> list[dict[str, Any]]:
    """One compact row per preset, for the dashboard. Read-only, no network.

    Counts come from the saved trace itself (including the seed transfer as a
    row), and the outcome category comes from the saved Stage 3A record when
    one exists. No category is invented for a preset that has none.
    """

    from app.services.operational_status import verify_manifest_hashes

    rows: list[dict[str, Any]] = []
    for preset in all_presets():
        view = load_preset(preset)
        trace = view.trace or {}
        seed = trace.get("seed") or {}
        endings = trace.get("branch_endings") or []
        transfers = trace.get("observed_transfers") or []
        outcome = view.outcome or {}
        seed_transfer = 1 if trace.get("seed_transfer") else 0
        base_dir = view.manifest_path.parent if view.manifest_path else None
        integrity = verify_manifest_hashes(view.manifest, base_dir)
        rows.append(
            {
                "integrity": integrity,
                "id": preset.id,
                "title": preset.title,
                "scenario": preset.scenario,
                "data_mode": view.data_mode,
                "address": preset.address,
                "network": seed.get("network_key"),
                "observed_transfers": len(transfers) + seed_transfer,
                "branch_endings": len(endings),
                "unresolved": sum(
                    1 for b in endings if b.get("endpoint_class") == "unresolved"
                ),
                "candidate": sum(
                    1 for b in endings if b.get("endpoint_class") == "deposit_candidate"
                ),
                "known_service": sum(
                    1 for b in endings if b.get("endpoint_class") == "known_service"
                ),
                "outcome_category": outcome.get("category"),
                "outcome_service": outcome.get("service_name"),
                "has_trace": view.trace is not None,
                "error": view.error,
            }
        )
    return rows
