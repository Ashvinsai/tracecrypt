# START_HERE

Read-only investigative triage for crypto fraud complaints. The system follows
supported transaction activity from a seed address or transfer event to the
first supported receiving VASP/service boundary, explains why each attribution
was made, and packages the result for review.

**It does not** identify a person from an address, establish guilt, guarantee
recovery, execute freezes, or claim approved government connectivity.

## Order of reading
1. `AGENTS.md` — binding rules for anyone (human or assistant) editing this repo.
2. `docs/FIVE_STAGE_PLAN.md` — **the current build order.**
3. `docs/PRD.md` — what a trace result means; inputs, outputs, non-goals.
4. `design/SCHEMA_AND_API.md` — data contracts. Changing these is a decision, not a refactor.
5. `docs/ACCEPTANCE_CATALOG.md` — the specification, and which rows have a test that has actually run.
6. `docs/DECISIONS.md` — why the stack and the invariants are what they are.
7. `docs/BUILD_PLAYBOOK.md` — the superseded 20-phase plan, kept as a correctness reference.

## Build order

`docs/FIVE_STAGE_PLAN.md` replaced the 20-phase playbook on 2026-09-20 (D011).
The playbook remains useful for correctness detail and later production work.

| Stage | Title | State |
|---|---|---|
| — | Foundation (ex-phases 00–02): contracts, skeleton, data model | done |
| 1 | One real end-to-end result: TRON adapter, tracer, `/trace`, HTML evidence view | **live validation verified**; one bounded case is recorded below |
| 2 | Label acquisition and TRON resource-delegation evidence | **done for the current TRON pilot**; two accepted OKX claims and one candidate are on file |
| 3 | Useful inference and an Isolation Forest anomaly ranker | **partially started**; policy and synthetic ranker exist, real evaluation is not ready |
| 4 | Investigator console, monitoring, export | **in progress**; console, exports, drafts, mock intake, and offline monitoring exist |
| 5 | Frozen evaluation and publication | not started |

The foundation stage was built against the old playbook before the plan changed.
Its data model, contracts, and tests carry over unchanged; the queue, Redis, and
PostgreSQL requirement were dropped from the critical path (D012).

## Current state

The Stage 1 slice runs end to end: seed event → adapter → chronological tracer →
reviewed anchors → JSON result → printable evidence view. A bounded LIVE run
was verified on 2026-09-26 against TronGrid and reached the reviewed OKX service
boundary. The bundle is under
`var/live-validation/20260926T070828Z-c53a38/`; its offline replay also passed.
Receipt verification is copied into the trace/report (`success` and
`confirmed`), while the separate `receipts.json` remains the detailed source.

The live run used the reviewed registry in `data/verified_anchors.csv`, which
contains two accepted OKX service-control claims scoped to the snapshot instant
`2026-08-10T15:59:54Z`. The sending address remains a candidate, not an
ownership claim. Every anchor in `data/anchors.csv` is still fictional.

Future live runs still require:

1. A TronGrid API key (`CFA_TRON_API_KEY`), created in the TronGrid console.
   It is sent as the `TRON-PRO-API-KEY` header, grants API access only, and
   signs nothing.
2. One independently sourced TRON service anchor — address, source URL,
   disclosure date, and the role that source actually supports — imported and
   accepted in `data/verified_anchors.csv`. See `data/README.md`.

The Stage 1 gate is now met for this bounded example. It does not establish
general TRON coverage, continuous exchange control, or customer-deposit status.

Everything downstream of those two inputs is built and tested offline. With a
key and one accepted anchor, `make validate-live ARGS="--address … --contract …
--seed-event …"` writes an inspectable bundle to `var/live-validation/<run-id>/`,
and `make replay-validation RUN=…` replays it through the same pipeline.

Monitoring can write pending, hashed investigator notification packages with
`make poll-watches ARGS="--notification-out …"`; this is a local evidence
outbox only, not an external notification or agency connector.

## Run it

```bash
cd api && uv sync --all-groups
uv run alembic upgrade head
uv run python ../scripts/seed_demo.py
uv run pytest -q
```

No Docker required. See `README.md` for the rest.
