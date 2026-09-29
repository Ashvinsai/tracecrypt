# Signal GUI redesign — verification record

These results were run for this GUI redesign. They do not replace the original v2 validation history or imply that unexecuted tests passed.

## Results

| Check | Actual outcome |
| --- | --- |
| JavaScript parse checks (`node --check`) for `app.js`, `operations.js`, `ui.js` | All 3 passed. |
| Read-only UI regressions | 3 passed. |
| Real-API UI workflow and responsive checks | 100 passed; 0 failed; 0 JavaScript page errors. |
| Existing documented backend subset | 790 passed; 1 deselected; 143.80 seconds. |
| Fresh archive extraction, asset bytes, local API and automatic worker | 14 passed. |
| Final source archive integrity | ZIP CRC and all manifest file hashes checked during packaging. |
| Actual screenshots | 7 Chromium screenshots captured; no JavaScript page errors. |

Raw records are in `validation/ui/results/`. Screenshots are in `docs/ui-redesign/screenshots/`.

## UI coverage

The desktop workflow checks exercised default overview metrics against the supplied API response; actual graph-node count; light/dark appearance controls; saved-evidence filtering and expansion; keyboard command search; guide dialogs; signed-out gating; node inspection; zoom and expanded graph view; keyboard evidence tabs; ordering-ambiguous events; exact uint256-scale decimal strings; actual JSON-download contents; saved-case export gating; invalid and valid sign-in; wallet quick-start without automatic submission; real manual case creation and tracing; the nearest-VASP summary; an authorized HTML report; actual PDF/CSV/JSON/manifest bundle output; a review-only request draft; saved-run reopening; watch creation, polling and alerts; durable complaint intake and processing; disabled live-only CCTP controls; unconfigured agency status; authorized case search; clearing stale results when selecting another case; and private-state/hidden-view cleanup after logout.

The responsive portion checked **9 views at 6 widths**: 1920, 1440, 1280, 1024, 768 and 390 pixels. Those 54 assertions are included in the 100 checks, not an additional 54. They check document-level horizontal overflow after logout, with public evidence selected in the trace view. Private lists were exercised with real data at desktop width. Wide evidence tables can scroll within their own panels. This is not a claim that every possible dataset was visually tested at every viewport.

Read-only regression records show the original mode/ambiguous-edge issues failing before correction, and the mobile layout issue before its correction. A further workflow regression captured stale evidence remaining after case selection before the state-transition fix. The final results pass those cases.

## Commands executed

From the extracted project root, with the environment's already installed Python packages:

```bash
node --check workspace/app.js
node --check workspace/operations.js
node --check workspace/ui.js
python launch.py --prepare --port 8010
python validation/ui/regression.py
python validation/ui/smoke.py http://127.0.0.1:8010 /mnt/data/tracecrypt_ui_smoke.json
python validation/run_checked_suite.py
```

The smoke run deliberately used the local server **without a companion worker**, so its explicit Process next action could verify the queue deterministically. It creates synthetic cases and watches in that disposable local database. No generated database or `.env` is included in the delivered archive.

A separate fresh extraction was then started with:

```bash
python launch.py --prepare --with-worker --port 8011
```

Its 14 checks verified initialization, exact delivery of all seven checked workspace assets, synthetic sign-in, complaint acceptance, automatic worker completion, saved-result integrity verification and a real evidence ZIP while the worker was running. The final rebuild adds documentation, screenshots and test logs; application assets are the same as those served during the fresh-extraction check.

To repeat UI tests locally, install Python Playwright in a development environment and supply an installed Chromium executable through `CHROMIUM_PATH` when it is not `/usr/bin/chromium`. Stop any automatic queue worker before running the smoke script, and use a disposable SYNTHETIC installation. Both UI scripts default to port 8010. The smoke script's default output is `ui-smoke-results.json` in the current folder; an explicit output path can be supplied as its second argument.

## Browser harness boundary

The environment's Chromium policy blocks direct URL navigation. The tests therefore load the actual HTML/CSS/JavaScript into an `about:blank` document. `validation/ui/browser_harness.py` relays its fetch calls to the real loopback FastAPI process through a single HTTP client session. **API responses are real, not mocked.** The harness rejects non-loopback base URLs and only relays the application's `/api/v1/` paths.

This exercises DOM rendering, application logic, actual API responses and evidence outputs. It **does not** validate native browser cookie/CORS enforcement, normal URL navigation or an unrestricted deployment. The harness captures download blobs and report URLs instead of invoking a blocked operating-system download dialog; it inspects the actual returned JSON/ZIP and requests the authorized HTML report. Appearance switching is tested; localStorage persistence is not tested in the opaque document origin. Clipboard permissions are not tested. The application includes a manual-copy fallback message.

## Backend subset exclusions

`validation/run_checked_suite.py` is the original documented 70-module subset. **19 upstream modules are excluded** as declared in `validation/excluded_modules.json`; they require unavailable development dependencies such as `respx` and/or PyCryptodome. One xhtml2pdf-specific failure-injection test remains deselected. The available existing PDF path produced the real evidence bundle. The new GUI checks verify bundle contents, not a new PDF layout or legal-admissibility audit.

This environment did not perform a clean internet-based dependency installation. It used the existing application fallbacks and installed packages. The unchanged runtime requirements remain the intended setup route for an ordinary machine.

## Observed test environment

Python 3.13.5; Node.js 22.16.0; Chromium 144.0.7559.96; Python Playwright 1.57.0; FastAPI 0.128.2; Uvicorn 0.48.0; SQLAlchemy 2.0.50; HTTPX 0.28.1; pytest 9.0.2; ReportLab 4.4.9. The bundled vis-network version is 10.1.2. These are observed versions, not new dependency pins or upgrades.

## Not verified

A clean Python 3.12/3.13 installation; Windows/macOS execution; Firefox/Safari; native browser transport/download permissions; a formal WCAG audit; large-graph or national-scale load; production penetration testing; new LIVE provider calls; actual NCRP, SAHYOG or VASP connections; model accuracy; legal authority; freezing or recovery. The separate React research console was retained, not rebuilt or included in the new UI browser checks.
