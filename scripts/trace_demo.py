"""Run the Stage 1 slice from the command line and write the evidence report.

SYNTHETIC only. This is the demo path, not a live trace.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.adapters.base import AssetRef  # noqa: E402
from app.core.settings import DataMode, get_settings  # noqa: E402
from app.models.enums import CaseFlowLinkage  # noqa: E402
from app.reports.evidence import render_evidence_html  # noqa: E402
from app.services.trace_service import run_trace  # noqa: E402

VICTIM = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
CONTRACT = "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY"
SEED_EVENT = "tron:tx_seed_multi:0"
OUT_DIR = REPO_ROOT / "var"


async def main() -> int:
    settings = get_settings()
    if settings.data_mode is DataMode.LIVE:
        print("this demo is SYNTHETIC only; CFA_DATA_MODE=LIVE is refused", file=sys.stderr)
        return 1

    result = await run_trace(
        settings,
        seed_address=VICTIM,
        asset=AssetRef("tron", CONTRACT, 6, "USDT-SYN"),
        seed_event_reference=SEED_EVENT,
        analysis_cutoff=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
        case_flow_linkage=CaseFlowLinkage.established,
    )
    payload = result.to_json()

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "trace.json").write_text(json.dumps(payload, indent=2))
    (OUT_DIR / "trace-report.html").write_text(render_evidence_html(payload, request_id="cli"))

    print(f"data mode         {payload['scope']['data_mode']}")
    print(f"coverage          {payload['scope']['coverage_status']}")
    print(f"observed transfers {len(payload['observed_transfers'])}")
    for ending in payload["branch_endings"]:
        name = ending["label"]["entity_name"] if ending["label"] else "-"
        print(
            f"  {ending['endpoint_class']:<18} {ending['address']:<36} "
            f"{ending['observed_amount_display'] or '':>14}  {name}"
        )
    print(f"\nwrote {OUT_DIR / 'trace.json'}")
    print(f"wrote {OUT_DIR / 'trace-report.html'}  (open in a browser, print to PDF)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
