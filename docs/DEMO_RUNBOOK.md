# Demo runbook — local investigator console

A short, executable script for showing the read-only console. Everything below
runs offline against already-saved evidence. No live chain, no model, no login,
no Docker, no Redis.

**What the console is:** a local, read-only presentation of saved trace
results. It does not trace live, does not identify a person, does not assert
fraud, does not estimate a recovery, and does not execute or imply a freeze.

---

## 1. Start

On a fresh clone, prepare once (this is the only step that may need network):

```bash
make demo-prepare     # uv sync + npm ci + frontend build + synthetic artifacts
```

Then start the demo:

```bash
make demo
# or, equivalently:
./scripts/run_demo.sh
# or, two terminals:
#   make dev
#   make frontend-dev        # optional React dev server only
```

`make demo` serves the already-prepared workspace and never installs anything.
If `frontend/dist` is missing it rebuilds from an existing `frontend/node_modules`
(no network) or stops with a clear message telling you to run `make demo-prepare`.
It will not silently fall back to the legacy console.

The launcher prints the URLs and fails clearly if `uv` is missing.

## 2. Open

| Page | URL | Purpose |
|---|---|---|
| **Investigator** | `http://127.0.0.1:8010/investigator` | The main React workspace: graph, timeline, attribution, cross-chain, evidence, decision support |
| **Overview** | `http://127.0.0.1:8010/` | Key features, what it refuses to do, the how-it-works animation |
| **Demo (legacy)** | `http://127.0.0.1:8010/console` | Server-rendered console over saved results |
| **Fund flow** | `http://127.0.0.1:8010/graph` | Graph of one saved result's observed transfers (`?preset=<id>`) |
| **Dashboard** | `http://127.0.0.1:8010/dashboard` | Saved runs, outcomes on file, evaluation readiness |

Start on the **Investigator** workspace for the product walkthrough, then the
**Overview**/`/console` pages for the narrative, then **Dashboard**. The demo
defaults to port **8010** (not 8000) so it does not collide with an unrelated dev
server. Port override: `DEMO_PORT=9000 make demo`.

## 3. Two-to-three-minute sequence

Start on the **Overview** page for the pitch. Use the animated **How this works**
strip (Seed → Observe → Trace → Check provenance → Supported / Candidate /
Unknown); **Play / Step / Replay** controls it and **Esc** stops it. Reduced
motion preferences show the completed state without movement. The pages follow
the OS light/dark setting.

**Preset 1 — synthetic, limited** (default console view, or click
*"Synthetic: multi-hop path with unresolved branches"*):

1. Badge reads **SYNTHETIC**; say *every address and service name here is
   fictional.*
2. The chronological table starts at **hop 0** with the seed transfer (the
   case link) and continues through the onward transfers — the trace result
   carries the seed event itself, so the row is not reconstructed. The
   printable evidence report shows the same hop-0 row.
3. The summary reports several branch endings: one reaches an invented service
   label, one is only a **candidate**, and **two are unresolved**. The path
   view colours them differently (green / amber / grey).
4. Say: *unresolved is the honest result. An asset change, bridge, privacy
   mechanism, or opaque contract would look exactly like this, so the tracer
   assumes no continuation rather than inventing one.*

**Optional recorded example — public multi-hop TRON route** (shown only when
its successful replay, report, and export artifacts are present; click
*"Recorded: public TRON multi-hop route to an OKX boundary"*):

- Path: `TMqg…` → `TNRy…` → `TNtTc…` → `TYfxtk…` (three successful USDT-TRC20
  transfers, each receipt-verified and solidified). The page shows the forward
  tracer's complete branches, including unresolved branches, not just the OKX
  route.
- Describe it only as a **public multi-hop TRON transaction path**. It does not
  establish that the upstream addresses share an owner, are fraudulent, hold
  victim funds, or uniquely carry the same fungible units.
- The final OKX service-control assertion is supported only at
  **2026-08-10T15:59:54Z**. Its customer-deposit role and continuing control are
  not established; case-value allocation remains `allocation_unknown`.
- The source LIVE bundle, offline `RECORDED_PUBLIC` replay, and evidence export
  are saved separately under `var/`; the replay and export badges remain
  **RECORDED PUBLIC**. Hash matches establish file consistency only.

**Preset 2 — recorded, supported** (available when its saved bundle is on
disk; click *"Recorded: 72.14 USDT transfer to an OKX disclosure address"*):

5. The top-bar badges read **RECORDED PUBLIC** and
   **LOCAL PROTOTYPE · READ ONLY**. Say: *this is saved public-disclosure data,
   not a live chain connection.*
6. **Result card:** *"Supported destination: OKX."* Say what that means: the
   observed path reached an **accepted OKX service-control address** inside the
   label's dated window. The card also shows the observed amount, data mode,
   execution/finality, and **one important limitation**.
7. **Path:** seed `TNtTcst…` → OKX address `TYfxtk…`. Use the **Play / Previous
   / Next / Replay** controls to walk the observed transfers in order; the
   matching timeline row highlights as it goes. The legend explains seed /
   supported boundary / candidate / unresolved without relying on colour alone.
   *Evidence layers* expands the separately saved behavioral evidence.
8. **Timeline:** one seed arrival transfer of **72.140000 USDT** (`72140000`
   base units), `receipt_verified`. It is shown from the saved branch arrival
   event, and its block time is joined from the separately saved behavioral
   acquisition for the same transaction — the page labels that source. The
   numbered button on each row highlights it on the path.
9. **Evidence & uncertainty:** three segments. *Evidence* is the source,
   reviewer, validity, and hashes; *Uncertainty* is the eight independent axes
   (`execution_status`, `coverage_status`, `attribution_status`,
   `case_flow_linkage`, `acquisition_completeness`, `verification_quality`,
   `event_identity_quality`, `ordering_quality`); *Limitations* is unknown
   ownership, allocation unknown, bounded coverage, and the recorded-vs-live
   caveat. Say: *these are separate facts; there is no single confidence
   score.*
10. **Actions:** **Evidence report**, **Outcome report**, **Comparison report**,
    **Download JSON**, and **Print / Save PDF**. Close the tabs to return.

Any additional saved bundles under `var/live-validation/*/` appear in the
sidebar automatically, always badged **RECORDED PUBLIC** with their capture
mode stated in the text (a saved bundle never wears a LIVE badge).

**Unknown input:**

14. In the address box type `TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv` (a valid TRON
    address with no saved preset) and click **View saved result**. The page says
    *no saved result matches*, not *no activity*. Then type `not-an-address`: it
    says *not a valid TRON address*. Say: *this prototype does not trace live,
    so it will not guess.*

**Readiness card:**

15. In the sidebar, expand *Experimental ML & evaluation readiness*. It reads
    **NOT_READY_FOR_REAL_EVALUATION** and **No anomaly model trained**, and
    lists each sourced wallet with its on-disk materializable-window status. The
    ML panel is badged **EXPERIMENTAL · SYNTHETIC DEMONSTRATION · NOT
    ATTRIBUTION · NOT FRAUD PROBABILITY**. Say: *the trace result does not
    depend on any model, and none has been trained.*

**Dashboard (optional, 30 seconds):**

16. Open `http://127.0.0.1:8010/dashboard`. The **Capabilities and status**
    card states, per feature, what is `available`, `partial`, `not built`, or
    `not configured` — the anomaly ranker and held-out evaluation are
    **partial** (the code exists and runs, but only on synthetic rows and no
    model is trained on real data), monitoring is **not built**, connectors are
    **not configured**. Say: *the gaps are stated, not hidden.*
17. The **ML review-prioritization (experimental)** card renders the saved
    Stage 3C evaluation: badge **SYNTHETIC DEMONSTRATION**, the predeclared
    rubric, review-worthy precision@k vs the random-ranking baseline, and the
    ranks of known operational confounders. Say: *this is review prioritization
    only — it is not an accuracy claim, does not measure guilt, and changes
    nothing about the trace result.* If no report is saved yet, generate one
    offline with
    `uv run python scripts/anomaly_ranking.py --json-out var/anomaly-evaluation/report.json`
    (SYNTHETIC rows only; no network).
18. The **Saved-bundle integrity** card re-hashes each saved bundle's manifest
    and shows **all match**. Say: *a match shows the files are unchanged since
    the run; it is not proof the attribution is correct.*

## 4. Observed vs inferred (say this out loud)

- **Observed:** the transfer amount, the sender and receiver addresses, the
  event reference, the execution/finality receipts, the OKX disclosure row.
- **Inferred / derived:** the outcome *category* (`supported_destination`) is a
  display classification over those facts, not new evidence.
- **Unknown:** who controls the sending address; the address role; the
  allocation of any case value (`allocation_unknown`).
- In the optional multi-hop example, the transfers are observed public events;
  the path does not prove common control, criminality, victim-fund ownership,
  or unique continuation of fungible units. The OKX label applies only at its
  reviewed snapshot instant.

## Optional candidate-neighborhood discovery

Two bounded public discovery reports are saved under `var/vasp-neighborhood/`:
one LIVE capture and its `RECORDED_PUBLIC` replay around the accepted `TYfxtk…`
OKX anchor, plus a LIVE zero-candidate report around `TLaGj…`. The first finds
its existing one-event sender
`TNtTcst…` only as an **unreviewed `deposit_candidate`**, supported by that
single snapshot-time transfer; the second has **zero candidates**. These are
address-specific research leads, not wallet clusters or verified service
ownership. The saved reports appear as links in the dashboard and are viewed separately
at `/neighborhood/vasp/<run-id>`; they are not trace presets and do not change a
trace result. The successful discovery report can be replayed offline with
`CFA_DATA_MODE=RECORDED_PUBLIC` using
`scripts/discover_vasp_neighborhood.py --replay <saved-run>`; its manifest hashes
the report and recorded raw provider exchanges.
- In the optional multi-hop example, the transfers are observed public events;
  the path does not prove common control, criminality, victim-fund ownership,
  or unique continuation of fungible units. The OKX label applies only at its
  reviewed snapshot instant.

## 5. Fallbacks

- **No internet / provider down:** the demo never calls a provider. Nothing to
  do.
- **Frontend build fails:** irrelevant. The console is server-rendered by the
  FastAPI app; the React shell is optional and only links to it.
- **Fresh clone:** `var/` is gitignored. `make demo` builds the synthetic
  trace and report offline when either file is missing, then the console opens
  on the synthetic preset. To rebuild manually, run `make trace-demo` from the
  repository root. Optional recorded presets appear only when their required
  evidence artifacts are present; the launcher never fetches or regenerates
  them. The direct OKX example uses
  `var/live-validation/20260920T090201Z-969305/`. The multi-hop example requires
  the successful replay bundle `var/live-validation/20260926T103814Z-f75259/`
  and export package `var/evidence-export/20260926T103814Z-f75259/`.
- **Login/database errors:** the console routes do not use the database and do
  not require a session. If a *different* page is opened, use `/console`.

## 6. Open / print the evidence report

- From the console: **Open evidence report**, **Open comparison report**,
  **Open outcome report** (each opens a deterministic HTML page), and
  **Print / Save PDF** (browser print to PDF).
- **Download saved trace (JSON)** exports the exact saved result.
- **Print / Save PDF** prints the result only; the sidebar is hidden in print.
- Direct URLs:
  `/console/evidence/recorded-okx-direct`,
  `/console/comparison/recorded-okx-direct`,
  `/console/outcome/recorded-okx-direct`,
  `/console/trace/recorded-okx-direct`.

## 7. Honest statements this demo must keep true

- The prototype is **read-only**.
- **No person is identified**; no address is tied to a human.
- **No automatic freeze** or asset restriction is executed or implied.
- **No ML model is required** for the attribution shown, and none is trained.
- **Recorded** and **synthetic** examples are labelled as such, visibly.
- Recoverable amounts are never estimated; case-value allocation stays
  `allocation_unknown`.
