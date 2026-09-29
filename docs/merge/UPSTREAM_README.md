# Crypto Fraud Attribution Triage

Read-only investigative triage for crypto fraud complaints. Follows supported
transaction activity to the first supported receiving VASP/service boundary,
explains every attribution, and packages the result for human review.

**What it does not do:** identify a person from an address, establish guilt,
guarantee recovery, execute freezes, or connect to any government system.

Current scope is TRON with one verified TRC-20 asset. The project now has a
bounded live-validation path; broad live coverage and additional networks are
still out of scope.

Read `START_HERE.md` first. `AGENTS.md` is binding for anyone editing this repo.

## Requirements
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node 22+

No database server, no Docker, no Redis. The prototype runs on SQLite; the same
models run on PostgreSQL by changing `CFA_DATABASE_URL` (D012), and
`docker-compose.yml` is kept for that case only.

## Run it

```bash
cp .env.example api/.env        # optional; the defaults work
make migrate                    # create ./var/cfa.db
make seed-demo                  # load the SYNTHETIC fixture + demo login
make test                       # run the suite
make trace-demo                 # run the stage-1 slice, write var/trace-report.html
make dev                        # API on http://localhost:8000
make frontend-dev               # UI on http://localhost:5173
```

Demo login: `investigator@example.test` / `demo-password-change-me` — a local
development account, created only by the seed script, never in production.

Without `make`, each target is one command; run `make help` to see them, or read
the `Makefile`, which is a short list of literal shell commands.

## Live TRON configuration

The private TronGrid API key is stored locally in `api/.env` under
`CFA_TRON_API_KEY`. The file is ignored by Git and should remain private. Do not
paste the key into source files, reports, logs, or commits.

The application defaults to `SYNTHETIC` mode. Set `CFA_DATA_MODE=LIVE` when
running a live validation:

```bash
cd api
CFA_DATA_MODE=LIVE uv run python ../scripts/validate_live.py \
  --address TXXXX \
  --contract TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t \
  --cutoff 2026-09-26T00:00:00Z
```

Live validation also requires an address and analysis window. Add
`--seed-event tron:<transaction-hash>:<event-index>` when the complaint names a
specific transfer.

## Quick demo

The fastest path is the read-only investigator console. It needs no database
migration, no login, no Docker, and no live provider — it renders already-saved
evidence.

```bash
make demo          # or: ./scripts/run_demo.sh
```

The prototype is three pages:

| Page | URL | What it is |
|---|---|---|
| Overview | <http://127.0.0.1:8010/> | What the prototype does and refuses to do, with a how-it-works animation |
| Demo | <http://127.0.0.1:8010/console> | The investigator console over saved results |
| Dashboard | <http://127.0.0.1:8010/dashboard> | Saved runs, outcomes, and evaluation readiness |

Pick the recorded OKX example for a supported result and the synthetic example
for an unresolved one; any other saved bundle under `var/live-validation/` is
discovered automatically. Full script, talking points, and fallbacks:
`docs/DEMO_RUNBOOK.md`.

The console is server-rendered by the existing FastAPI app (`/console`), reusing
the same trace/outcome/comparison contracts as the JSON API and the printable
reports. The React shell remains an optional API-health view and links to the
console. No model is trained or required.

## Layout

```
api/            FastAPI application, Alembic migrations, tests
  app/core/     settings, logging, auth, authorization, amounts, envelope
  app/models/   ORM models — the canonical data contracts
  app/adapters/ ChainAdapter interface, TronGrid adapter, fixture provider
  app/engine/   chronological tracer and the trace result contract
  app/reports/  deterministic evidence report
  app/services/ address canonicalization, label registry, fixture loading
frontend/       React + TypeScript shell
data/           anchors.csv — the only place an address-to-entity claim may live
fixtures/       SYNTHETIC captures (fictional addresses and service names)
docs/           five-stage plan, PRD, threat model, decisions, acceptance catalog
design/         schema and API contract
scripts/        demo seeding and the CLI trace demo
```

## The invariants that matter

These are not style preferences. Each one prevents a class of wrong answer in a
document that may end up in an investigation.

- **Address identity is `(network, canonical_address)`.** The same hex string is
  valid on every EVM chain, so a network is never inferred from syntax.
- **Asset identity is `(network, token_contract)`.** A ticker is display metadata.
- **Amounts are integers in base units.** `NUMERIC(78,0)` in Postgres, `int` in
  Python, **string** in JSON, never a JavaScript `Number`.
- **Event identity is chain-specific, never a transaction hash.** One transaction
  can carry many transfers; deduplicating by hash destroys evidence.
- **Four independent status axes:** execution, coverage, attribution, and
  case-flow linkage. There is no single confidence score, and no percentages.
- **A provider failure is a failure,** never an empty history.
- **Timestamps are timezone-aware UTC.** The tracer is chronological; a naive
  datetime is rejected rather than assumed.
- **Synthetic stays synthetic.** The fixture adapter refuses to serve a process
  that declares itself LIVE, and the loader refuses to write under LIVE.

## Evaluation corpus (a human step)

Real ML evaluation needs independently sourced, human-reviewed evaluation
wallets with saved windows. `bash scripts/review_evaluation_wizard.sh` walks a
person through registering, reviewing, and capturing one wallet, then
regenerates the readiness report. Only a human can vouch for a wallet's
independent source; the wizard never invents one. Until at least two distinct
materialized wallets exist, the anomaly ranker stays a synthetic-only
demonstration (see `docs/DECISIONS.md`).

## Status

The build order is `docs/FIVE_STAGE_PLAN.md`. Stages 1–2 are done, including a
bounded LIVE validation against TronGrid. Stage 3 has
the read-only service-outcome layer, the versioned strong-inference policy, and
a deterministic Isolation Forest ranker that currently runs only as a
synthetic pipeline demonstration. A Stage 4 read-only investigator console
prototype is in place. One accepted real evaluation wallet now has a saved
behavioral window, but real training and held-out evaluation still require a
second accepted materialized wallet and broader category coverage. Monitoring
also has a local pending-notification outbox; it does not send external
notifications.

`docs/ACCEPTANCE_CATALOG.md` lists every acceptance criterion and names the test
behind each one, or says plainly that none exists yet.
