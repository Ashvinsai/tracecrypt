# TraceCrypt Unified v2

**Reported wallet → durable investigation job → verified chronological trace → nearest observed receiving VASP → investigator review, monitoring and evidence package.**

One FastAPI backend, one organization-scoped case database and one primary workspace. This release extends the combined project rather than shipping two disconnected applications. The original React research console, reviewed-label tools, historical evidence and optional shadow-model research remain available.

This is a working **investigative prototype**, not an asset-freezing service, an official NCRP/SAHYOG connector or a universal exchange-ownership database. Synthetic examples, saved public captures and LIVE acquisition are separated. No private keys, transaction signing, automatic legal requests or fabricated live results.

## Start the application and automatic worker

Use **Python 3.12 or 3.13**. Node.js is not needed for the supplied primary workspace.

### Windows / PowerShell

```powershell
cd TraceCrypt_Unified
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-runtime.txt
.\.venv\Scripts\python.exe launch.py --prepare --with-worker
```

### Linux / macOS

```bash
cd TraceCrypt_Unified
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
.venv/bin/python launch.py --prepare --with-worker
```

Python 3.13 may be substituted. Open **http://127.0.0.1:8010/workspace/**.

```text
Email:    investigator@example.test
Password: demo-password-change-me
```

The launcher creates a random session secret locally, applies migrations and seeds only SYNTHETIC mode. Repeating preparation preserves a complete existing demo fixture; it refuses a partial/conflicting fixture instead of silently overwriting it. The ZIP contains no generated `.env`, provider keys, application database or installed environment.

For later starts use `python launch.py --with-worker` in the same environment. Stop with Ctrl+C. Keep the demonstration bound to localhost; the launcher refuses production mode. The credentials above are public demo credentials, not suitable for a deployed system.

## Demonstrate the complete local workflow

Sign in, open **Complaint automation**, click **Fill synthetic example**, then **Submit & queue**. With `--with-worker`, the persistent job is picked up automatically. The dashboard refreshes every five seconds while visible. Open the completed saved result to inspect the graph, nearest observed VASP, exact transfers, attribution evidence, pattern indicators and limitations. Export the evidence ZIP and reopen the saved run from **Cases & saved runs**.

The example uses a fictional exchange. It is not evidence about a real service or wallet owner. A successful job means the software completed its bounded analysis, not that a real VASP was necessarily identified or money recovered.

For a manual trace, the fixture is:

```text
Network:        tron
Reported wallet: TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM
Token contract:  TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY
Seed event:     tron:tx_seed_multi:0
Incident start: 2026-08-01T00:00:00Z
Cutoff:         2027-01-01T00:00:00Z
```

Use **Monitoring & alerts** to create a watch on this same wallet/token starting 2026-08-01 UTC. Poll it once; a repeated poll deduplicates previously observed events. For unattended watch polling, run the server without `--with-worker` and start one worker separately:

```bash
python operations_worker.py --poll-watches --watch-interval 60
```

Use only one SQLite queue worker and one watch scheduler for the local database; do not simultaneously manually poll the same watch.

## Added in v2

| Capability | Delivered behavior |
|---|---|
| Complaint automation | Validated JSON intake and UI; organization/source-bound credentials; idempotent complaint references; supported-token fan-out; persistent case/job creation. |
| Durable jobs | Leases, conditional claims, retries, expiry recovery, cancellation, fenced result saves and recorded failures. SQLite local worker; PostgreSQL claim implementation retained for deployment validation. |
| VASP attribution | First accepted receiving service on each verified path; actual transfer-hop ranking; all equally near matches retained. Conflicting ownership/role labels stay unresolved. Sender ownership is never inferred from payment. |
| Investigation intelligence | Evidence-linked fan-in/out, rapid/repeated forwarding, peeling-like and cyclic-topology indicators; observed intermediary behavior and authorized cross-case address overlaps. |
| Event ledger and signals | Hash-checked per-investigation event observations, cursor API, organization/mode/network separation, deduplication, acknowledged review signals and actual queue metrics. This is not whole-chain indexing. |
| Cross-chain evidence | New bounded Ethereum→Base USDC CCTP V2 checker: both chain IDs, finality/receipts, exact message/nonce/domain/recipient/amount reconciliation and raw evidence export. Checked recipient continuation is explicitly queued by the investigator. |
| Actual optional ML | IsolationForest graph-anomaly ranking on a same-organization/network/token/mode cohort, disjoint chronological train/holdout wallets, minimum 25 eligible wallets, no fabricated scores or fraud probabilities. Original shadow router retained separately. |
| Evidence and workflow | Saved-run JSON/HTML/PDF/CSV export, checksum manifest, linked checked bridge evidence, draft-only information/preservation requests and the integrated dashboard. |
| Operational fixes | No idle queue writes; local SQLite WAL; read transactions released before provider I/O/PDF rendering; repeat preparation; incident-start propagation; source conflicts remain visible. |

## Configure genuine LIVE work separately

Use a **new database**, real operators, reviewed token metadata and reviewed labels. Never repurpose the synthetic database or copy fictional anchors into LIVE.

```dotenv
CFA_APP_ENV=dev
CFA_DATA_MODE=LIVE
CFA_ENGINE_VERSION=unified-2.0
CFA_SECRET_KEY=GENERATE_A_RANDOM_SECRET_NOT_THIS_PLACEHOLDER
CFA_DATABASE_URL=sqlite+pysqlite:///../var/live.db
CFA_LABEL_SOURCE=reviewed_sets
CFA_ETHEREUM_RPC_URL=YOUR_ETHEREUM_MAINNET_RPC
CFA_BSC_RPC_URL=YOUR_BSC_MAINNET_RPC
CFA_BASE_RPC_URL=YOUR_BASE_MAINNET_RPC
CFA_TRON_API_KEY=YOUR_TRONGRID_KEY
```

Put only needed real values in `api/.env`, protected on your machine. Use `python launch.py --prepare-only`; this does not seed LIVE. Create the operator and register reviewed exact token metadata:

```bash
python manage.py create-operator --email investigator@your-agency.example --organization "Your unit" --slug your-unit
python manage.py register-token --network ethereum --contract YOUR_EXACT_CONTRACT --decimals YOUR_REVIEWED_DECIMALS --symbol YOUR_DISPLAY_SYMBOL --source "YOUR_REVIEWED_SOURCE" --verify-evm
```

The password is prompted. RPC bytecode/decimal verification does not authenticate the token issuer. The supplied real accepted VASP anchors remain **two narrowly time-scoped historical OKX examples**. Unknown/new wallets may therefore remain unresolved. Expanded attribution needs independently sourced, reviewed and maintained labels; it cannot be generated by changing a UI badge.

Live adapter scope is TRON TRC20 and Ethereum/BSC/Base ERC20 transfer events with exact configured tokens. Native/internal transfers, Bitcoin, Solana, arbitrary swaps/bridges and privacy mechanisms are not implemented. A blank token field searches registered supported tokens, not every possible asset. A finality boundary/provider failure is not replaced by synthetic data.

The checked CCTP route requires a LIVE case, configured Ethereum and Base RPC endpoints, supported CCTP V2 evidence and registered Base USDC before recipient continuation. It does not independently verify Circle attestation signatures or consensus. More detail: [cross-chain and security notes](docs/completion/DEPLOYMENT_AND_SECURITY.md).

## Integration and verification

The new authenticated **application-owned** intake contract is `/api/v1/integrations/complaints`. A local administrator issues scoped, expiring credentials through `gateway_admin.py`. Official schemas, authorization, agreements and transport onboarding still need to come from the relevant agency. Calling a source `ncrp_gateway` does not establish a government connection.

- [Problem-statement coverage and remaining external requirements](docs/completion/PROBLEM_STATEMENT_COVERAGE.md)
- [Intake API, sample payload and credential setup](docs/completion/API_INTEGRATION.md)
- [Deployment, security and operational boundaries](docs/completion/DEPLOYMENT_AND_SECURITY.md)
- [Validation results and excluded checks](docs/completion/TEST_RESULTS.md)
- [v2 changes and source map](docs/completion/CHANGELOG-v2.md)

`schemas/` contains exported JSON/OpenAPI contracts. The running local API reference is `/docs`. Run `python validation/run_checked_suite.py` for the documented offline subset after installing development test dependencies; omitted modules are not reported as passing. The full upstream suite is `cd api && uv sync --group dev && uv run pytest`, requiring dependencies not available in the build environment.

Historical upstream documents and evidence retain their original dates and results. They are not new measurements for v2. The original instructions are archived under `docs/merge/`; this README takes precedence for the combined release. `PACKAGE_MANIFEST.json` hashes packaged files, not itself, and is a local consistency aid rather than an independent digital signature.
