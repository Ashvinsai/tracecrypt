# TraceCrypt Unified

**A combined investigative prototype built from the full Crypto Attribution project and the useful TraceCrypt workflow, graph and analysis features.** One FastAPI backend, one case database, one evidence contract. The new primary workspace is `/workspace/`; the original React research console remains available at `/investigator` in non-production mode.

This is source code plus a runnable local demonstration, **not a hosted service, an exchange ownership database, a production-certified investigation platform, or an asset-freezing service**.

## Run locally

Use **Python 3.12 or 3.13**. No Node.js build is required for the supplied workspace or the retained prebuilt research console.

### Windows (PowerShell)

```powershell
cd TraceCrypt_Unified
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-runtime.txt
.\.venv\Scripts\python.exe launch.py --prepare
```

Python 3.13 can be used instead by replacing `-3.12` with `-3.13`.

### Linux / macOS

```bash
cd TraceCrypt_Unified
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
.venv/bin/python launch.py --prepare
```

Open **http://127.0.0.1:8010/workspace/**.

The first preparation applies three database migrations and creates an explicitly **SYNTHETIC** local demonstration. A random session secret is generated on your own machine in `api/.env`. No provider keys are supplied. Subsequent starts can use `python launch.py` in the activated environment; `--prepare` is idempotent for this demo.

Local demo account:

```text
Email:    investigator@example.test
Password: demo-password-change-me
```

Keep this demonstration bound to localhost. The launcher refuses production mode; `seed_demo.py` refuses production and every mode other than SYNTHETIC. Never reuse demo credentials or the synthetic database for real complaints.

### Reproduce the complete demonstration

Sign in. In **Trace workspace**, enter:

```text
Address:       TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM
Network:       TRON mainnet
Asset:         USDT-SYN · TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY
Case reference: choose a new reference, e.g. DEMO-MERGED-001
Case title:    Synthetic merged demonstration
Seed event:    tron:tx_seed_multi:0
Cutoff (UTC):  2027-01-01 00:00
```

Expand **Case and incident scope** for the final four fields. Select **Run & save investigation**. Inspect the graph, service boundaries, patterns, exact transfer ledger and limitations. Export the bundle, then reopen the same run in **Cases & saved runs**. The fictional Northwind Exchange label is deliberately marked fictional; it is not evidence about a real exchange.

Create a watch on the same address/contract with start time `2026-08-01 00:00 UTC`, then choose **Poll now**. Repeated polls deduplicate the same events. Create a second case and save another trace to demonstrate **Cross-case leads**. Address overlap is not an ownership assertion.

The read-only preset picker also opens the original synthetic and historical public examples without signing in. Historical captures are clearly labelled saved/recorded; opening one does not call a blockchain provider or create a case run.

## What was combined

| Area | Combined implementation |
|---|---|
| Core tracing | The full project's chronological, asset- and event-scoped engine, with strict positive-value, successful-execution and confirmed-finality continuation. Receipt verification now happens before real-provider path continuation. |
| Investigator workspace | New integrated static workspace drawing on TraceCrypt's graph/dashboard approach, connected to the same case and evidence APIs. Local vis-network library; no CDN dependency. Original React source and prebuilt console retained. |
| Pattern detection | Adapted/reimplemented fan-in, fan-out, rapid forwarding, repeated forwarding, peeling-like splits and bounded cyclic-topology checks. Integer base units, chronological checks and explicit innocent alternatives. These are rule-based leads, not ML probabilities. |
| Intermediaries | Observed receipt/forwarding summaries. No invented wallet age, zero balance, burner-wallet status, exchange ownership or common controller. |
| Cross-case analysis | Organization-scoped exact address intersections, separated by network and data mode. Known service/protocol endpoints excluded; repeated runs of one case are not multiple complaints. |
| Case persistence | New checksum-checked investigation snapshots. Reopening, reports, request drafts and exports use the saved result, not a fresh trace. |
| Evidence | Original evidence model, source provenance, reviewed label policies, chronological paths and reports retained. Exports add `intelligence.json` and `investigation.json` to the JSON/HTML/PDF/CSV bundle and SHA-256 manifest. CSV formula text is neutralized. |
| Monitoring | Original checkpointed, deduplicated watches/alerts retained; case-scoped manual poll endpoint and foreground polling command added. |
| Request drafting | Original information/preservation/restriction safeguards retained and attached to saved runs. Drafts only; no request is sent. |
| Cross-chain | Original CCTP Ethereum-to-Base code, command-line workflow and recorded evidence retained. Not a generic bridge/mixer deanonymization system. |
| AI/model work | Original evaluation, anomaly-ranking and optional CLM shadow-routing code retained. Deterministic policy remains authoritative. The new workspace's priority points are explicitly rule-based. |
| Operational boundaries | Authentication, organization-scoped cases, input validation, mode separation, redaction and bounded acquisition retained; additional same-origin mutation checks and saved-result integrity checks added. |

TraceCrypt's fixed-confidence sender ownership inference, incorrect haircut accounting, mock registry blending, fabricated indexing statistics, fake connected statuses and mock cross-chain matches were **not** carried into the operational path. Unknown victim-fund allocation remains unknown. The combined code does not assert that every outgoing transfer carries the victim's funds.

## Live configuration: explicit, separate and limited

Use a **separate database** for LIVE. Configure `api/.env` (see `api/.env.example`) with a strong random secret, `CFA_DATA_MODE=LIVE`, and `CFA_LABEL_SOURCE=reviewed_sets`. Do not migrate demo complaints or fictional labels into live work. The local launcher applies migrations but does **not** seed synthetic data when the process is LIVE.

The retained live adapters cover **TRON TRC20 token transfers** and **Ethereum, BSC and Base ERC20-style transfer logs**. Each EVM network needs its own RPC URL and has its chain ID checked. Native/internal-call transfers, Bitcoin, Solana, universal DeFi interpretation, mixers and arbitrary bridges are not implemented by this merged core. A missing provider, unsupported finality or unavailable label is not replaced by invented data.

Environment keys:

```dotenv
CFA_APP_ENV=dev
CFA_DATA_MODE=LIVE
CFA_SECRET_KEY=replace-with-at-least-32-random-characters
CFA_DATABASE_URL=sqlite+pysqlite:///../var/live.db
CFA_LABEL_SOURCE=reviewed_sets
CFA_TRON_API_KEY=your-own-key
CFA_ETHEREUM_RPC_URL=your-own-ethereum-mainnet-endpoint
CFA_BSC_RPC_URL=your-own-bsc-mainnet-endpoint
CFA_BASE_RPC_URL=your-own-base-mainnet-endpoint
```

Do not copy placeholder values as working credentials. Configure only the providers you intend to use. Register operators and explicitly sourced supported token metadata:

```bash
python launch.py --prepare-only
python manage.py create-operator --email investigator@your-agency.example --organization "Your unit" --slug your-unit
python manage.py register-token --network ethereum --contract YOUR_EXACT_CONTRACT --decimals YOUR_REVIEWED_DECIMALS --symbol YOUR_DISPLAY_SYMBOL --source "YOUR_REVIEWED_ISSUER_OR_CHAIN_SOURCE" --verify-evm
```

The password is prompted, not placed in shell history. The token command performs read-only EVM chain/bytecode/decimal checks when requested; it does not authenticate the issuer. `verified_at` remains unset for operator-sourced registration. Use checksum-valid TRON contracts and independently review issuer references. Token names are not identities.

The supplied real accepted service anchors remain narrowly scoped historical examples. A LIVE trace may end unresolved because the label set is small or outside its applicable time range. A large current exchange/deposit-address intelligence dataset is **not** supplied. Retained import/review commands are documented in the upstream materials under `docs/` and `docs/merge/UPSTREAM_README.md`.

### Monitoring

For the selected process data mode:

```bash
python manage.py poll-watches                 # one bounded pass
python manage.py poll-watches --interval 60   # visible foreground loop; Ctrl+C to stop
```

Run **one polling worker per database**; do not concurrently manually poll the same watch. This loop is not distributed scheduling, a durable queue, a mempool feed or a response-time guarantee. Provider delays, quotas and finality affect alert timing. The original `scripts/poll_watches.py` and notification-outbox flow remain available for its more detailed TRON recorded-capture workflow.

### Government and exchange integrations

NCRP intake examples remain local **mock complaint payloads**. SAHYOG/NCRP authorized production connectors and VASP submission credentials are **not configured**. The system generates investigator-reviewed request drafts, not sent requests, freezing orders or recovery guarantees. UI capability status states this explicitly.

## Development and validation

Complete upstream dependency installation (requires package-network access):

```bash
cd api
uv sync --group dev
uv run pytest
```

The old lock file is preserved as `docs/merge/upstream-uv.lock.reference`; it is not used as a false lock for changed dependency constraints. Generate a fresh lock in your connected development environment. The root runtime requirements use version ranges, not a reproducible deployment lock.

See **`validation/TEST_RESULTS.md`** for the exact executed tests, environment, exclusions, browser transport limitation and unverified components. Live providers, GPU model serving, production PostgreSQL/Redis operation, Windows installation and government connections were not executed during this merge. Local API, synthetic algorithms and evidence generation were exercised without substituting fake results.

The PDF exporter uses xhtml2pdf when installed; an actual WeasyPrint renderer is supported as a fallback. Missing both yields an explicit error, never a fake PDF. The tested local runtime used WeasyPrint. Both render the same escaped source report, now with wrapped tables and vertical provenance records.

## Important engineering limitations

This remains an investigative prototype. Database hashes detect mismatch against the stored digest, **not** independent authenticity or tampering by an administrator who can rewrite both. Public recorded bundles are historical supplied artifacts, not independently reauthenticated blockchain data. Model evaluation numbers in those bundles are original recorded results, not newly reproduced accuracy claims.

Before operational deployment, separately engineer independent evidence signing/storage, privacy/retention controls, audit access, secure reverse-proxy/session settings, login rate limiting, role/organization selection, backups, concurrency controls, provider-specific load testing and externally reviewed label coverage. The new CSRF-origin checks do not replace a full production security review. Do not expose the development server or demo credentials to the internet.

## Package layout

```text
launch.py / manage.py        Local launch, explicit setup and polling
workspace/                  New combined workspace + local graph vendor asset
api/app/                    Full retained backend + new merged modules
api/tests/test_unified_*     New merge regressions
api/migrations/              Existing migrations + saved-investigation migration
frontend/                   Original React source and prebuilt console
data/ / fixtures/ / var/     Supplied labels and synthetic/historical proof artifacts
scripts/                    Original tracing, import/review, CCTP, monitoring and model tools
docs/merge/                 Merge notes, archived upstream startup docs, license
validation/                 Executed test logs and limitations
```

Credentials, generated `.env` files, runtime databases, caches and installed dependencies are not included. The original public proof-of-reserves source archive is retained because existing provenance tests depend on it.
