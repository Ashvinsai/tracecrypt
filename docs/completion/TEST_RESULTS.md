# v2 validation results

## Checked offline regression suite

**790 passed, 1 deselected across 70 selected test modules**, in 83.75 seconds in this environment. The final raw output is `validation/v2/checked-suite.log`; the exact selection is `tested_modules.txt`. Four new operations modules cover intake/queue, ML, cross-chain checks and nearest-service conflicts/ties. Existing modules cover retained tracing, reporting, evidence, auth and other behaviors.

The run used Python 3.13.5, installed packages already available in the environment, and bounded BLAS/OpenMP threading. It was not a new isolated dependency installation. `python validation/run_checked_suite.py` reruns this declared subset.

**19 upstream test modules were not executed** because `respx` and/or PyCryptodome were unavailable. They are enumerated individually in `validation/v2/excluded_modules.json`. One xhtml2pdf-specific PDF failure-injection test was deselected; the available WeasyPrint path generated the actual PDF. Excluded/deselected tests are not passing tests and these numbers are not a claim that the entire repository suite passed.

## What the added checks cover

Intake creation through trace worker, saved snapshot, VASP summary, indexed observations and review signals; identical complaint retries and changed-payload rejection; tenant/source-bound credential access and expiry/revocation; address/network/schema/body limits; incident-start propagation; provider timeouts and retries without fake saved results; lease recovery, exhaustion and stale-result fencing; cancellation; corrupt job/event/snapshot checks; idle workers performing no SQL writes.

ML tests fit a real IsolationForest on an explicitly synthetic cohort, enforce chronological disjoint holdout wallets and reject bad hashes, incomplete coverage, mixed modes and inadequate data. A persisted 30-wallet API cohort yields six held-out scores for its own organization and none for another organization. This is a functional test, not a fraud-accuracy evaluation.

CCTP tests use supplied recorded public evidence and mocked HTTP acquisition, with negative changes to identities, finality, nonce, recipients, domains, amounts, message evidence and endpoint chain ID. API tests cover tenant/mode checks, checksum rejection and idempotent recipient continuation. The historical capture did not contain a fresh Ethereum chain-ID response; the unit test supplies its explicit fixture context, while the mocked acquisition test checks both RPC calls. No new live provider verification was claimed.

Attribution tests preserve equally near observed service matches, use actual transfer-hop counts, keep same-conclusion independent sources usable and refuse arbitrary ownership/role selection when accepted labels conflict.

## Running application and browser check

The actual Uvicorn backend plus companion worker accepted a new synthetic complaint, automatically finished its persistent job, displayed its saved graph and nearest fictional receiving VASP, and exported its evidence ZIP. All exported manifest file hashes matched. Cases, monitoring, correlations, cross-chain, decision support and capability pages rendered. The ML panel correctly reported insufficient data for the single unique fixture wallet. A 390-pixel mobile viewport had a matching document width. **Zero JavaScript page errors** were captured.

The environment blocked system Chromium's direct navigation to localhost. Therefore the actual frontend was loaded into Chromium with an injected fetch bridge that relayed real HTTP requests to the running backend, using an HTTP client's cookies. This exercises frontend logic and real API/worker behavior, **not native browser cookie transport or an unrestricted localhost navigation**. Separate API tests cover authentication/authorization. The screenshots and JSON result are under `validation/v2/`.

An integration check initially found a SQLite read/write lock during export with the polling worker. The release fixes this through idle read-only queue probes, local WAL and releasing read transactions before provider/PDF work. The subsequent actual worker/export check succeeded. This is not multi-node load testing.

## PDF and evidence

The synthetic evidence report rendered in four pages. Checked text bounds stayed inside every page; representative page renders were inspected. The ZIP contains the saved JSON/HTML/PDF/CSV outputs, derived intelligence and investigation metadata, plus its checksum manifest. `pdf-check.json` records the layout result. The large synthetic integer-transfer test intentionally remains an exact artificial boundary-value amount, not a real loss or balance.

## Package startup

A fresh extraction startup check is recorded in `validation/v2/fresh-package-startup.log`. It checks migrations, first and repeated synthetic preparation, HTTP readiness, gateway submission/idempotency, automatic queue execution and saved evidence export using the environment's existing dependencies. It does not install packages from the internet. See that log for the completed results rather than inferring production deployment success.

## Not verified here

New live blockchain requests/provider quotas; real NCRP/SAHYOG or VASP connections; actual notices/freezing/recovery; current broad exchange labels; independent CCTP attestation signatures; GPU model serving; PostgreSQL migrations/parallel load/failover; Docker deployment; Windows/macOS execution; clean Python 3.12/3.13 dependency installation; security accreditation or legal admissibility; operational fraud accuracy, response-time SLA or national-scale indexing.

Historical logs under `validation/` and retained upstream evidence are earlier results, not v2 measurements. Use this file and `validation/v2/` for the release-specific checks.
