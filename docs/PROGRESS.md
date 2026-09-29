# Project progress

Last updated: 2026-09-26. This is a living status snapshot, not a plan — see
`FIVE_STAGE_PLAN.md` for the plan itself and `DECISIONS.md`/
`REQUIREMENTS_MATRIX.md` for earlier, now-superseded 20-phase planning
artifacts (pre-pivot; kept for history, not current status).

## What this project is

A local, read-only TRON/TRC-20 fraud-attribution investigation prototype.
It never identifies a person, never asserts fraud, never estimates a
recovery amount, and never executes a freeze. Its job is to collect
evidence, preserve exactly what is and isn't known about it, and present
that evidence — never a verdict — to a human investigator.

Stack: Python 3.12, FastAPI, SQLite by default (PostgreSQL still supported
via the same SQLAlchemy models), local raw-response JSON bundles for
provenance, CSV-based label/evidence files as the source of truth. This
replaced an earlier, heavier 20-phase plan (Postgres/Redis/React) after a
pivot on 2026-09-19 (`bac04d3`) to a five-stage plan that front-loads one
real, correctly-interpreted result over infrastructure.

## The five stages, and where each one stands

| Stage | What it is | Status |
|---|---|---|
| **1 — One real end-to-end result** | TRON adapter, chronological forward tracer, CSV label registry, one trace from a real transfer to a sourced service label, HTML evidence report | **Done** |
| **2 — Label acquisition & TRON-specific evidence** | OKX anchor import, candidate discovery, resource-delegation evidence, TRX-funding evidence, behavioral/sweep evidence, four-level comparison report, quality-axis separation, confounder-dataset interface | **Done** (this session's work; see below) |
| **3 — Useful inference + modest real ML** | Service-outcome categories, strong-inference policy, Isolation Forest anomaly ranking | **Partially started (3A + 3B + 3C-fit).** 3A: the read-only service-outcome layer and a documented, versioned, uncalibrated strong-inference policy v1. 3B: an evaluation-corpus ingestion/materialization workflow and a model-readiness report (no model). 3C: a deterministic Isolation Forest ranker (scikit-learn) that fits, scores, and runs a held-out precision@k evaluation against a predeclared rubric + random baseline — but only on SYNTHETIC demonstration rows, since no accepted-and-materialized real windows exist. The ranker is surfaced in the console as a separate **partial** capability. **No model has been trained on real data, and no real held-out evaluation has been run.** |
| **4 — Investigator workflow, monitoring, export** | Console UI, new-event monitoring, PDF/CSV export, draft legal requests, mock complaint adapter | **In progress.** Read-only console prototype done (see "Stage 4 prototype" below); PDF/CSV/JSON evidence export bundle with a checksum manifest done (see "Stage 4 — evidence export bundle" below); draft legal-request generation (information/preservation/asset-restriction, with a structural pooled-wallet refusal rule) done (see "Stage 4 — legal-request drafts" below); mock complaint queue done (see "Stage 4 — mock complaint queue" below); checkpointed new-event monitoring done offline (see "Stage 4 — checkpointed new-event monitoring" below). **The Stage 4 monitoring gate (one supported new event produces one alert) is met on SYNTHETIC/RECORDED_PUBLIC data; no live poll has been run.** |
| **5 — Publish evidence of value** | Frozen thresholds, holdout evaluation, precision/coverage reporting | **Not started** |

## Stage 1 — what was built

- `api/app/adapters/tron.py` — `TronGridAdapter`: paginated TRC-20 transfer
  history, receipt/finality verification (solidified vs. head), event-index
  resolution with graceful fallback to a content-derived reference when the
  chain can't supply ordering (`ordering_ambiguous`).
- `api/app/adapters/base.py` — the `ChainAdapter` contract every provider
  (live, recorded, fixture) implements identically.
- `api/app/engine/tracer.py` — `ChronologicalTracer`: bounded forward walk
  over states (not a global visited-address set), day-one correctness tests
  encoded as real assertions (failed/approval events never extend a path,
  separate transfers in one tx stay separate, pagination dedups without
  merging, etc.).
- `api/app/services/labels.py` — CSV-backed `LabelRegistry`.
- `api/app/reports/evidence.py` — deterministic, escaped, printable-to-PDF
  HTML evidence report; no LLM-composed facts, every number reproduced
  verbatim from the trace result.
- Dialect-aware SQLAlchemy types (`api/app/db/base.py`) so the same models
  run on SQLite (dev/test) and PostgreSQL (production) without behavior
  drift: `BaseUnits` (exact integer, never float), `UtcDateTime`,
  `JSONColumn`.

## Stage 2 — what was built (the bulk of this project's actual work)

### A. Anchor and candidate acquisition
- `api/app/services/anchor_import.py` — imports a dated, sourced
  service-control disclosure (OKX proof-of-reserves) into
  `data/anchors.csv`, with signature verification, snapshot-instant
  resolution from the chain, and a `data/review_log.csv` decision trail.
  A human reviewer (`api/app/services/candidate_review.py`) is the only
  path from `unreviewed` to `accepted` in `data/verified_anchors.csv`.
- `api/app/services/collect_candidates.py` — bounded, recorded search for
  senders to an accepted anchor within its dated validity window; writes
  `data/deposit_candidates.csv` as unreviewed leads, never verified
  addresses.
- **Real accepted anchors on file:** `TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv`
  and `TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir`, both OKX, both scoped to the
  single dated instant `2026-08-10T15:59:54Z` (a reserve snapshot, not a
  continuous-control claim).
- **Real candidate on file:** `TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq` —
  sender of a 72,140,000-base-unit (72.14 USDT) TRC-20 transfer to the
  second anchor at that exact instant. Still `review_state=unreviewed`,
  `address_role=unknown` — a lead, never promoted.

### B. Resource-delegation & TRX-funding evidence
- `api/app/services/collect_resource_evidence.py` — bounded collector for
  Stake 2.0 delegation (current-state index/detail *and* genuinely
  historical Delegate/UnDelegate operations, kept as separate
  `temporal_status` facts) and native TRX funding. Three relationship
  types (`token_transfer`, `resource_delegation`, `trx_funding`) are never
  merged and never imply common ownership.
- `api/app/services/resource_evidence_report.py` /
  `api/app/services/features.py` — deterministic counting and feature
  extraction from the persisted CSV only.
- **A real counting bug was found and fixed here**: a hand-written summary
  once reported 12 historical delegation operations against 15 total rows;
  the actual, code-verified split is 10 historical (6 delegate, 4
  undelegate) + 4 current-state + 1 token transfer = 15. Fixed by adding
  an explicit `operation_type` field (`delegate`/`undelegate`/
  `current_index`/`current_detail`) instead of relying on text parsing,
  plus a reconciliation test that would fail if categories ever stop
  summing to the total.
- **Real resource evidence on file** (`data/resource_evidence.csv`, 15
  rows): 10 historical Delegate/UnDelegate operations with
  `TLvg8p7dE6txHh3MBZW6zhfEHVeo99kor5` between 14:54–14:55 UTC on
  2026-08-10; current-state delegation from that same provider and from
  `TTz9gYGZnAuDpqaQ77VFoBYt937bReAQo4`; 0 TRX funding (collection was
  truncated by the 20-request budget, so this is "unknown", not
  "confirmed zero").

### C. Behavioral/sweep evidence
- `api/app/services/collect_behavioral_evidence.py` — bounded, paginated
  TRC-20 history in both directions for one candidate/token, reusing the
  Stage 1 adapter. Approvals and failed/reverted transfers are excluded
  before they ever become a row; multi-transfer transactions keep distinct
  identities even without paid event-index enrichment.
- **A real truncation-flag bug was found and fixed here**: when a page
  landed exactly on the configured `event_limit` with a genuine
  continuation cursor still present, the collector reported
  `truncated_by_event_limit: false` — a false "complete" signal. Root
  cause, fix, and two regression tests (exact-boundary-with-cursor vs.
  exact-boundary-with-no-cursor) are in
  `api/tests/test_collect_behavioral_evidence.py`. The buggy run
  (`var/collect-behavioral-evidence/20260920T162301Z-adfb1e/`) was kept
  untouched as the historical record; a corrected re-run
  (`20260920T165506Z-ee96cd/`) reproduced all 200 of its rows byte-for-byte
  plus 35 genuinely new ones, and is now `complete_within_scope` in both
  directions.
- `api/app/services/behavioral_features.py` — deterministic features from
  saved rows only: observed incoming/outgoing counts and amounts, distinct
  counterparties, outgoing concentration (toward the accepted anchor, and
  the maximum by count/by amount to any single counterparty), repeated
  forwarding, nearest-preceding-receipt timing pairs (never an arbitrary
  earlier receipt), and a post-outflow residue that is explicitly not a
  wallet balance and not victim-associated value.
- **Real behavioral evidence on file** (236 rows: 1 incoming, 235
  outgoing, window 13:59:54–16:59:54 UTC on 2026-08-10): one 750,000-USDT
  incoming transfer, followed by 235 outgoing transfers totalling
  ~745,297.3 USDT to 210 distinct counterparties (one counterparty alone
  received ~33.5% of the outgoing amount). This is a fan-out pattern —
  reported as behavioral evidence only; the codebase explicitly refuses to
  read it as ownership, fraud, or common control.

### D. Four-level Stage 2 comparison report
- `api/app/services/evidence_comparison.py` +
  `api/app/reports/comparison.py` + `scripts/build_evidence_comparison.py`
  — builds and renders `anchor_only` → `chronological_tracing` →
  `tracing_plus_behavioral_rules` → `tracing_plus_behavioral_rules_plus_
  resource_evidence`, each level naming its own observed evidence,
  supported conclusion, unresolved items, source evidence ids, temporal
  scope, and completeness. A shared resource provider or shared behavior
  never merges two candidates (tested explicitly).
- **Completeness vs. verification quality are kept as separate axes**
  (added specifically to prevent one "complete" status from implying
  both): `acquisition_completeness`, `verification_quality`,
  `event_identity_quality`, `ordering_quality`. For the real candidate,
  level 3 now states plainly: *"Acquisition complete within the bounded
  window; execution and fine event ordering not verified."* The one
  transaction with separate Stage 1 receipt evidence is called out without
  upgrading the other 235 observations.
- Current output: `var/evidence-comparison/TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq/{comparison.json,comparison.html}`.

### E. Stage 3 prep (not Stage 3 itself)
- `api/app/services/evaluation_wallets.py` — an offline confounder/control
  wallet dataset (`data/evaluation_wallets.csv`), strictly separate from
  the attribution files. Categories: `self_custody`,
  `frequent_exchange_customer`, `payment_service`,
  `energy_rental_recipient`, `other_operational_confounder`. Every record
  requires its own `source_reference` and `evidence_type`; absence of a
  record is never read as a negative label. **Currently empty (header
  only) — no real confounder wallet has been human-sourced yet.**
- `api/app/services/feature_dataset.py` — converts already-computed
  Feature lists into a reproducible wallet-window table
  (`WalletWindowRow`), with a pseudonymous `wallet_id` (never the raw
  address), explicit missingness flags, and namespaced
  behavioral/resource feature columns. Includes deterministic
  `split_by_wallet` and `split_by_time` helpers so a later Stage 3 model
  can't leak the same wallet across train/eval. No score, no model, no
  accuracy number exists yet.

## Testing and code health

- `pytest -q` (from `api/`): **343 passed, 1 deselected** (the deselected
  test is the opt-in live-network contract test, gated behind an explicit
  flag).
- `ruff check .`: clean.
- `mypy app`: clean, 52 source files.
- Every collector (`collect_resource_evidence`, `collect_behavioral_evidence`)
  has tests proving it cannot modify `verified_anchors.csv`,
  `deposit_candidates.csv`'s review fields, or `review_log.csv`.

## Key invariants established along the way

- Four independent status axes, never collapsed into one score:
  `execution_status`, `coverage_status`, `attribution_status`,
  `case_flow_linkage` (Stage 1), plus the newer `acquisition_completeness`
  / `verification_quality` / `event_identity_quality` / `ordering_quality`
  split (Stage 2).
- `temporal_status=current_state_only` is never backdated to an earlier
  known event just because the same relationship exists now.
- An ambiguous chain event gets a content-derived reference and an
  explicit `ordering_ambiguous=True` flag — never an invented index.
- A truncated/incomplete collection reports "unknown", never "zero" or
  "complete" by omission (this is the exact class of bug found and fixed
  twice this session — once in resource-evidence counting, once in
  behavioral-evidence truncation flags).
- Data modes (`LIVE` / `RECORDED_PUBLIC` / `SYNTHETIC`) are never mixed;
  an adapter refuses to run under the wrong one.
- Every live acquisition writes raw provider responses plus a SHA-256
  manifest before anything derived is computed from it.

## Stage 3A — what was built (this session, dated 2026-09-20)

This is a new, dated increment on top of the Stage 2 status recorded above;
it does not rewrite or reinterpret any Stage 2 run record.

- `api/app/services/service_outcome.py` — a read-only, DISPLAY/DERIVED
  outcome layer that classifies one traced claim/branch into exactly
  `supported_destination` / `strong_inference` / `candidate_lead` /
  `unknown_or_blocked`, with explicit reason codes distinguishing "unknown"
  from "blocked". It never replaces the eight existing status axes
  (`execution_status`, `coverage_status`, `attribution_status`,
  `case_flow_linkage`, `acquisition_completeness`, `verification_quality`,
  `event_identity_quality`, `ordering_quality`) — every output record copies
  all eight through verbatim. Outcomes are scoped per claim: resolving one
  branch never implies anything about a sibling branch, and naming a path's
  terminal receiving service never asserts ownership of an intermediate hop
  on that path.
- `api/app/services/strong_inference_policy.py` — a documented, versioned
  (`POLICY_VERSION = "v1-uncalibrated-2026-09-20"`), explicitly uncalibrated
  policy gate requiring multiple independent, relevant evidence families
  (at least one reviewed, address-specific linkage item plus a distinct
  corroborating source) before promoting a claim to `strong_inference`. It
  is engineering judgment, not a trained/validated classifier, and never
  writes to `review_log.csv`, `deposit_candidates.csv`, or
  `verified_anchors.csv` — see `docs/DECISIONS.md` D023 for the full
  rationale, including the two traps it is written to avoid ("one upstream
  source counted twice" and "current-state delegation isn't historical").
- `api/app/reports/comparison.py` gained `render_service_outcome_html`, a
  thin, pure-rendering addition so JSON and HTML outcomes are produced from
  the same record and can never disagree.
- `scripts/build_service_outcome.py` — an offline CLI, mirroring
  `scripts/build_evidence_comparison.py`'s conventions, that reads only
  already-saved `verified_anchors.csv`/`deposit_candidates.csv` and writes
  only under `var/service-outcome/<candidate>/`.
- **Real demonstration**: run against the one real accepted anchor pair on
  file, the outcome layer reports `supported_destination` for the claim
  "OKX is this path's terminal receiving service" for
  `TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq` → `TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir`
  — the anchor label is accepted, in-date, right-network, and the seed
  transfer's execution is independently receipt-verified — while the
  candidate's own `review_state=unreviewed`/`address_role=unknown` are
  explicitly noted as untouched by that conclusion. Verified afterward by
  sha256-diffing `data/verified_anchors.csv`, `data/deposit_candidates.csv`,
  `data/review_log.csv`, and `data/evaluation_wallets.csv`: unchanged.
- `strong_inference` itself was **not** exercised on real data — this
  repository's saved evidence for the real candidate has no second
  independent, reviewed, address-specific linkage source. It is exercised
  only via SYNTHETIC-prefixed fixtures in
  `api/tests/test_service_outcome.py` (both the positive/negative pair and
  the frequent-customer/self-custody/energy-rental confounder cases — the
  latter are correctness fixtures only, not real evaluation data, and make
  no precision/accuracy claim).
- 20 new tests added (`api/tests/test_service_outcome.py`), full suite now
  363 passed / 1 deselected (verified by re-running `uv run pytest -q`);
  `uv run ruff check .` and `uv run mypy app` both clean.
- **Explicitly not done in this increment**: Isolation Forest training or
  scoring, any held-out precision/coverage evaluation, any change to
  `data/evaluation_wallets.csv` (it stays untouched/empty of invented
  labels), any dashboard, monitoring, or new chain/infra work. Stage 3 as a
  whole remains **not complete**.

## Stage 3B — what was built (this session, dated 2026-09-21)

Stage 3B is the evaluation-corpus workflow and model-readiness report only.
**No model was trained.** Isolation Forest training and held-out
precision/coverage evaluation remain Stage 3C, not started.

- `api/app/services/evaluation_wallets.py` grew three optional,
  backward-compatible columns (`upstream_source_id`, `reviewer`,
  `data_mode`) — an old CSV row missing them still loads, filled with safe
  defaults (`load_evaluation_wallets`). A new `dedupe_by_upstream_source`
  helper collapses records that cite the same upstream origin into one
  source for evidence-counting purposes, without ever treating two
  distinct, merely unlabeled sources as the same.
- `scripts/ingest_evaluation_wallet.py` — a dry-run-by-default local CLI.
  Requires `--write` to append; refuses unsourced/miscategorized rows
  (reusing `validate_evaluation_wallet`); refuses a duplicate
  (network, address, category) triple instead of silently double-appending;
  proven (via `api/tests/test_ingest_evaluation_wallet.py`) to preserve
  pre-existing rows byte-for-byte and to never touch
  `verified_anchors.csv`, `deposit_candidates.csv`, `review_log.csv`, or
  `independent_review.csv`. It has no credential/seed-phrase/PII fields by
  design — noted in its own docstring.
- `api/app/services/evaluation_dataset.py` — offline, deterministic
  materialization of ACCEPTED evaluation-wallet records (per
  `find_evaluation_wallet`'s existing semantics) plus SAVED
  `collect_behavioral_evidence` run bundles into `WalletWindowRow`s. A
  wallet with no saved run bundle on disk is skipped with reason
  `missing_evidence` — never fetched live. Never imports
  `service_outcome` or `strong_inference_policy` (grep-tested).
- `api/app/services/feature_dataset.py` gained
  `FEATURE_DEFINITION_VERSION`, a `feature_definition_version`/`data_mode`/
  `evaluation_source_reference` field on `WalletWindowRow`, a
  `dedupe_key` property, a `dedupe_rows` helper, and
  `assert_no_within_wallet_time_leakage` — a stronger, per-wallet check
  that a time-based split never trains on a later window while evaluating
  on an earlier window of the *same* wallet (plain `split_by_time` only
  guarantees a global boundary). `DISALLOWED_FEATURE_NAME_FRAGMENTS` grew
  `service_name` and `review_state`.
- `api/app/reports/evaluation_readiness.py` — a deterministic JSON +
  HTML model-readiness report. It separates "the pipeline structurally
  works" (demonstrable with zero real records via SYNTHETIC fixtures) from
  "the dataset is adequate for real evaluation" (`NOT_READY_FOR_REAL_
  EVALUATION`, with exact reasons — no invented numeric minimum-N is ever
  presented as scientifically sufficient). It reports no model metric of
  any kind: no accuracy/precision/recall/AUC/anomaly- or fraud-detection-
  quality number appears anywhere, because no model exists yet.
- `scripts/materialize_evaluation_dataset.py` — CLI wrapper, dry-run by
  default (`--write` to save `var/evaluation-dataset/*`).
- 30 new tests across `api/tests/test_evaluation_wallets.py` (extended),
  `api/tests/test_feature_dataset.py` (extended, plus isolation grep tests
  now also cover `service_outcome.py`/`strong_inference_policy.py`/
  `evaluation_dataset.py`), `api/tests/test_ingest_evaluation_wallet.py`
  (new), `api/tests/test_evaluation_dataset.py` (new), and
  `api/tests/test_evaluation_readiness.py` (new). Full suite now
  **392 passed / 1 deselected**; `uv run ruff check .` and
  `uv run mypy app` both clean (56 source files).

**Real demonstration.** `data/evaluation_wallets.csv` is still header-only
— **0 real evaluation wallets on file**, confirmed before and after this
session's work. Running the real materialization + readiness pipeline
against it (via `scripts/materialize_evaluation_dataset.py` and the
readiness-report builder) produces `materialized_window_count_real: 0`,
`independent_source_count_real: 0`, and status
`NOT_READY_FOR_REAL_EVALUATION`, with the exact stated reasons "0 real
evaluation wallets on file" plus "no related-wallet grouping data exists in
this repository in a defensible form". The pipeline's structural
correctness is instead demonstrated with SYNTHETIC-tagged fixtures
(`data_mode=SYNTHETIC`, addresses/source references prefixed `SYNTHETIC`)
in `test_evaluation_dataset.py` and
`test_evaluation_readiness.py::test_full_synthetic_pipeline_is_visibly_
tagged_and_excluded_from_real_counts`, which also proves SYNTHETIC output
is counted separately from, and never folded into, real-evaluation
coverage counts. Verified by sha256-diffing `data/verified_anchors.csv`,
`data/deposit_candidates.csv`, and `data/review_log.csv` before and after
(unchanged; `data/independent_review.csv` does not exist in this
repository and was not created).

**Explicitly not done in this increment**: any ML training, any held-out
precision/coverage/accuracy number, any real evaluation-wallet record
(fabricating one to make counts look better was explicitly avoided), any
related-wallet grouping heuristic (reported as an open structural gap
instead of invented), and no change to Stage 3's overall "not complete"
status.

## Stage 3B.1 — evidence-acquisition pass on the real evaluation corpus (this session, dated 2026-09-21)

Pure evidence-acquisition/validation work using the existing Stage 3B
ingest/materialize/readiness tooling. **No ML, no live blockchain
collection.**

- Baseline verified for real before touching anything: `392 passed, 1
  deselected`, `ruff check .` clean, `mypy app` clean (56 files) — matches
  the claimed baseline exactly.
- **2 real, RECORDED_PUBLIC records added** to `data/evaluation_wallets.csv`
  via `scripts/ingest_evaluation_wallet.py --write` (dry-run inspected
  first in both cases):
  1. `tron` / `TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT` — category
     `self_custody`. Source: SEC Form 8-K, Tron Inc. (Nasdaq: TRON), CIK
     0001956744, accession 0001493152-26-006323, filed 2026-02-12, Exhibit
     99.1 — the filer's own press release names this address as its
     designated on-chain TRX treasury wallet and links to it on TronScan
     itself. `upstream_source_id=tron-inc-2026-02-12-8k-ex99-1-trx-treasury-
     disclosure`. Retrieved/content-checked via WebFetch 2026-09-21.
  2. `tron` / `TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM` — category
     `other_operational_confounder`. Source: TronBid.com's own blog post
     (its own domain, published 2026-06-18, updated 2026-09-07) naming this
     address as belonging to TronBid.com's energy/bandwidth marketplace
     (TronScan public tag `TronBid_Energy_MarketPlace`).
     `upstream_source_id=tronbid-blog-tronscan-address-page-2026-06-18`.
     Retrieved/content-checked via WebFetch 2026-09-21.
  - Both records: `review_state=unreviewed` — this agent is not an
    authorized human reviewer for this project and did not self-promote
    either record to `accepted` (see `docs/DECISIONS.md` D025). Neither
    record therefore materializes a feature window yet, and
    `find_evaluation_wallet` (accepted-only) returns neither.
  - Categories still at zero: `frequent_exchange_customer`,
    `payment_service`, `energy_rental_recipient`.
  - `independent_source_count_real` (post-dedup, via
    `dedupe_by_upstream_source`): **2** (both upstream_source_ids are
    distinct, non-blank, and each named once).

- **A real bug was found and fixed while doing this**: appending a
  current-schema (12-column) row to the real, pre-existing 9-column-header
  `data/evaluation_wallets.csv` broke the file — the next
  `load_evaluation_wallets` call raised `TypeError` because
  `csv.DictReader` handed the extra values back under key `None`. Fixed
  with `_migrate_header_if_stale` in
  `api/app/services/evaluation_wallets.py` (header-only upgrade, in place,
  never touching existing data-row bytes) plus a relaxed, still-strict
  byte-preservation check in `scripts/ingest_evaluation_wallet.py`. Used
  the fixed code path itself to heal the one row already written under the
  stale header, rather than hand-editing the CSV. Two new regression tests
  in `api/tests/test_evaluation_wallets.py`. Full detail in
  `docs/DECISIONS.md` D025.

- **Sources investigated and rejected** (full list; every one checked with
  at least one WebFetch against the actual page, not just a search
  snippet):
  - Any exchange's (Binance, etc.) generic customer deposit address —
    rejected categorically per the operator's own prior finding: exchanges
    generate a unique per-user deposit address, so there is no fixed
    "frequent_exchange_customer" address an exchange's own docs could name.
  - USDT TRC20 token contract (`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`) —
    rejected: it is the token contract, not an operational wallet in any of
    the 5 categories.
  - OFAC/sanctions-list TRON addresses — excluded categorically by policy
    (D025), regardless of how well-documented; adversarial, not an
    operational confounder.
  - Binance's own Proof-of-Reserves page
    (`binance.com/en/proof-of-reserves`) — rejected: the actual TRON
    address list requires a client-rendered "Download All Address" action
    that a static WebFetch could not retrieve; no specific TRON address
    text was present in the fetched page content, so nothing here met the
    "actually read it" bar.
  - Netts.io's published "Trust Wallet Recipient Address"
    (`TDii6vao7xyWg2rKPbCPWVRpSmne8xcqYx`) — rejected: Netts.io's own page
    explicitly disclaims that the address is *not* affiliated with,
    operated by, or related to Netts.io; it is third-party tracking of an
    unrelated Trust Wallet fee-collection address, not a first-party
    disclosure by whoever actually controls it.
  - JustLend DAO docs (`docs.justlend.org`) — rejected: documentation
    describes the Energy Rental mechanism generically; no specific,
    checkable example/treasury wallet address is named anywhere in the
    docs found.
  - Feee.io — rejected: no official wallet address published anywhere
    found; only generic "how to rent" instructions and a support email.
  - TronScan's `TronBid_Energy_MarketPlace` tag considered on its own
    (i.e. absent TronBid's own blog corroboration) — would have been
    rejected as an unverified community-style explorer tag per the strict
    bar; accepted only because TronBid's *own* blog (a first-party source
    on TronBid's own domain) separately names the same address as its own
    — the tag was corroborating evidence, not the primary source.
  - Generic "how to use TRC20" / "how to send USDT on TRON" articles
    (TronSave blog, OneKey, Bitget, etc.) — rejected categorically:
    marketing/how-to content, never a named checkable example address tied
    to a real service's own operational wallet.

- **Materialization**: `scripts/materialize_evaluation_dataset.py` run
  (dry-run, no `--write` needed to observe the count) against the real
  registry: `materialized rows: 0`, `skipped: 0`. This is the correct,
  expected outcome — `materialize_evaluation_dataset` only considers
  `review_state=accepted` records, and both new records are
  `unreviewed`, so they never enter the accepted-record loop at all (not
  even as a `missing_evidence` skip). Both are valid evaluation identities
  today; neither is currently materializable, and that gap is a review-step
  gap, not an evidence gap — no live collection was attempted or proposed
  as a workaround.
- **Readiness report regenerated** against the real registry (via
  `build_readiness_report`): `real_wallet_count: 2`,
  `counts_by_category: {self_custody: 1, other_operational_confounder: 1}`,
  `counts_by_data_mode: {RECORDED_PUBLIC: 2}`,
  `independent_source_count_real: 2`, `materialized_window_count_real: 0`,
  `materialized_window_count_synthetic: 0`, `duplicate_rows_found: 0`,
  `split_feasible: true` (structural: ≥2 distinct wallet identities on
  file — this does **not** mean the corpus is usable for a real held-out
  experiment, since 0 windows materialize), status remains
  **`NOT_READY_FOR_REAL_EVALUATION`**, with reasons: "2 real evaluation
  wallets on file", the standing no-invented-minimum-N policy statement,
  and the still-unresolved related-wallet-grouping structural gap carried
  over unchanged from Stage 3B. No accuracy/precision/recall/AUC/anomaly-
  or fraud-detection-quality field appears anywhere; `no_model_trained_in_
  this_report: true`.
- Final verification re-run after all changes: `394 passed, 1 deselected`
  (392 baseline + 2 new regression tests), `ruff check .` clean, `mypy app`
  clean (56 files). `data/verified_anchors.csv`, `data/deposit_
  candidates.csv`, and `data/review_log.csv` sha256-verified byte-identical
  before/after; `data/independent_review.csv` still does not exist in this
  repository. `ppt/` untouched (file mtimes unchanged from before this
  session).

**Explicitly not done in this pass**: no ML training, no model metric of
any kind, no live blockchain collection (fully offline/saved-evidence, as
required), no self-promotion of either new record to `accepted` (left for
an actual authorized human reviewer), no fabricated authorized-team-member
observation (none was available this run, per the operator), and no change
to the readiness algorithm's thresholds or its `NOT_READY_FOR_REAL_
EVALUATION` conclusion.

## What's explicitly not done yet

- No ML model has been trained; no fraud, ownership, or customer-deposit
  probability has ever been computed anywhere in this codebase.
- The candidate has not been promoted or reviewed — it remains
  `unreviewed` / `address_role=unknown` throughout.
- 2 real confounder/control wallets have been sourced as of Stage 3B.1
  (`self_custody`, `other_operational_confounder`), both still
  `review_state=unreviewed` pending an authorized human reviewer — see
  "Stage 3B.1" above. `frequent_exchange_customer`, `payment_service`, and
  `energy_rental_recipient` remain at zero real records; the corpus is
  still far too small, one-sided, and unreviewed for any real held-out
  experiment.
- Only one chain (TRON) and one asset (USDT-TRC20) are supported.
- Stage 3C: the Isolation Forest ranker fits, scores, and evaluates a held-out
  split, but only on SYNTHETIC demonstration rows — no model has been trained
  on real data and no real held-out precision/coverage evaluation has been run
  (see the Stage 3C section above). Stage 5 (published evaluation) has not been
  started.

## Stage 3B.2 — evaluation-wallet review/audit/readiness-correctness workflow (2026-09-21)

Built the human-review workflow the two Stage 3B.1 real records were left
waiting on, plus corrected readiness semantics. No model was trained; no
review decision was made on a real record.

- New `api/app/services/evaluation_review.py`: the only code path that may
  change a `data/evaluation_wallets.csv` row's `review_state`. It never
  chooses accept/reject/quarantine itself — every call requires an
  externally supplied action, a named human reviewer (blank or
  automation-like identities such as "agent"/"assistant"/"claude"/"AI"/
  "system" are refused by `is_invalid_reviewer`), a non-blank rationale,
  and an `evidence_inspected` value that must identify the row's own
  `source_reference` or `upstream_source_id`. Dry-run by default;
  `--write` required to apply. Terminal states (`accepted`/`rejected`/
  `quarantined`) refuse re-review except the one documented transition
  `accepted -> quarantined` (for a problem discovered post-acceptance).
  Appends exactly one record per decision to new append-only
  `data/evaluation_review_log.csv` (schema: decision_id, decided_at,
  network, address, control_category, previous/new review_state, reviewer,
  reviewed_at, rationale, evidence_inspected, source_reference,
  upstream_source_id, data_mode).
- New CLI `scripts/review_evaluation_wallet.py`, mirroring
  `ingest_evaluation_wallet.py`'s dry-run-by-default shape. With no
  `--action`, it prints the full review packet and exits without deciding
  anything — this is how both real Stage 3B.1 records were inspected this
  session.
- Review packets never fetch a URL; they only display what's already on
  the CSV row, and explicitly say no locally preserved source
  snapshot/hash exists for this registry (unlike `verified_anchors.csv`'s
  `source_file`/`source_hash`), so a currently-reachable URL is not treated
  as immutable evidence.
- **Category-mismatch findings (unresolved, left for the human reviewer):**
  - `TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT`, proposed `self_custody`: the SEC
    8-K exhibit supports "Tron Inc.'s own designated on-chain TRX treasury
    wallet" — a corporate treasury disclosure, not literally
    "self_custody". The packet surfaces this explicitly and does not
    resolve it; no new `corporate_treasury` category was added
    unilaterally (see DECISIONS.md 2026-09-21 for why this is left open).
  - `TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM`, proposed
    `other_operational_confounder`: the TronBid.com blog post supports "a
    TronBid operational/service address associated with its energy
    marketplace"; the packet does not infer a specific send/receive
    transaction role beyond what the source states.
  - **Both records remain `review_state=unreviewed` at the end of this
    session — no accept/reject/quarantine decision was made on either real
    record.** `data/evaluation_review_log.csv` was never created against
    the real `data/` directory (0 real-record entries); any entries that
    exist anywhere came only from this session's own `tmp_path` test
    fixtures.
- **Four concepts kept explicitly separate** (module docstring and CLI
  output): (A) the sourced registry record, (B) the human-reviewed/accepted
  category, (C) feature-domain eligibility for the current TRON/USDT-TRC20
  experiment, (D) presence of a saved materializable evidence bundle on
  disk (`var/collect-behavioral-evidence/by-wallet/<network>/<address>/`).
  `domain_eligibility_for_wallet` checks (D) directly against the
  filesystem, never inferring it from `control_category` or from
  acceptance. For both real records today, eligibility is
  `not_accepted_and_no_materializable_window` — neither is accepted, and
  neither has a saved evidence bundle on disk. A synthetic
  fixture-only test (`test_accepted_record_with_no_saved_bundle_stays_
  accepted_but_materializes_nothing`) demonstrates the accepted-but-
  unmaterializable case with the explicit reason constant
  `accepted_registry_record_but_no_materializable_window`, since neither
  real record may be accepted in this task.
- **Readiness report corrected** (`api/app/reports/evaluation_readiness.py`):
  added `registry_wallet_split_structurally_possible` (≥2 distinct
  registry identities, any review state) as a clearly separate, much
  weaker field from the new `model_dataset_split_feasible` (requires ≥2
  distinct MATERIALIZED real wallet ids, non-empty train/eval partitions
  from `split_by_wallet`, and no within-wallet time leakage). The
  pre-existing `split_feasible` field is kept for backward compatibility
  but is now defined identically to `model_dataset_split_feasible` — no
  test or caller assumed the old registry-count meaning (grepped; only
  `evaluation_readiness.py` itself referenced the field), so nothing else
  needed updating. Also added: `unreviewed_real_registry_record_count`,
  `accepted_real_registry_record_count`, `missing_saved_evidence_bundle_
  count`, `categories_with_zero_real_examples` (coverage info, not a
  threshold), and `related_wallet_grouping_is_hard_blocker` (currently
  `False` — framed as a documented limitation pending explicit operator
  policy, not a permanent hard blocker; see DECISIONS.md 2026-09-21). No
  numeric minimum-N-for-adequacy threshold was invented anywhere.
- For the real 2-wallet state (both unreviewed, 0 materialized):
  `registry_wallet_split_structurally_possible=true`,
  `model_dataset_split_feasible=false` (reason: 0 distinct materialized
  real wallets; ≥2 required), `unreviewed_real_registry_record_count=2`,
  `accepted_real_registry_record_count=0`,
  `materialized_window_count_real=0`, `status=NOT_READY_FOR_REAL_
  EVALUATION`.
- **No live collection was performed.** For either real record to become
  materializable, an operator would need to run (NOT executed by this
  session):
  ```
  uv run python ../scripts/collect_behavioral_evidence.py \
      --candidate TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT \
      --token-contract <verified USDT-TRC20 contract> \
      --start <bounded window start> --cutoff <bounded window end> \
      --page-limit 5 --event-limit 100 --max-requests 20 \
      --out-dir ../var/collect-behavioral-evidence/by-wallet/tron/TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT \
      --write
  ```
  (and equivalently for `TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM`), followed by
  a human accept/reject/quarantine decision via
  `scripts/review_evaluation_wallet.py --write`, before
  `materialize_evaluation_dataset` would produce any row for either
  address. **Not executed in this session.**
- No ML model was trained; no accuracy/precision/recall/AUC or any model
  metric was produced anywhere in this pass.
- Full suite: 419 passed / 1 deselected (394 baseline + 25 new); `ruff
  check .` and `mypy app` both clean (57 files). `data/verified_anchors.csv`,
  `data/deposit_candidates.csv`, `data/review_log.csv`, and
  `data/evaluation_wallets.csv` sha256-verified byte-unchanged before/after;
  `data/independent_review.csv` still does not exist; `ppt/` untouched.

## Stage 3B.3 — evaluation-wallet capture as a distinct subject_kind (2026-09-21)

A proposed (never executed) LIVE `collect_behavioral_evidence.py` command
for the accepted TronBid evaluation wallet
(`TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM`) surfaced that the existing collector
only ever validates its subject against `deposit_candidates.csv` /
`verified_anchors.csv` -- correctly refusing this address, since it is
legitimately neither. Added a `subject_kind` field to
`BehavioralEvidenceRequest` (default unchanged: `"candidate_or_anchor"`)
and an `"evaluation_wallet"` capture path that validates instead against
an ACCEPTED `data/evaluation_wallets.csv` record, is always bundle-only
(never appends to `data/behavioral_evidence.csv`), never writes
`deposit_candidates.csv`/`verified_anchors.csv`/`review_log.csv`/
`evaluation_review_log.csv`, and stamps a registry snapshot into the run's
`manifest.json` for audit. Also added `scripts/evaluation_readiness_report.py`,
a CLI that actually calls `app.reports.evaluation_readiness.
build_readiness_report` correctly (verified by running it against the real,
unmodified `data/evaluation_wallets.csv`, offline, in this session).

- No live TronGrid call was made or attempted. No model was trained.
- The TronBid address was NOT added to `verified_anchors.csv` or
  `deposit_candidates.csv`; its `accepted` category was not changed; the
  quarantined `TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT` treasury record was not
  touched.
- Full suite: 432 passed / 1 deselected; `ruff check .` and `mypy app`
  both clean. `data/verified_anchors.csv`, `data/deposit_candidates.csv`,
  `data/review_log.csv`, `data/evaluation_wallets.csv`, and
  `data/evaluation_review_log.csv` sha256-verified byte-unchanged
  before/after; `data/independent_review.csv` still does not exist; `ppt/`
  untouched.
- See `docs/DECISIONS.md` (2026-09-21, "Stage 3B.3") for the full design
  rationale.

## Stage 3B.3 CLI wiring — `--subject-kind`/`--evaluation-registry` (2026-09-21)

Wired the already-implemented `subject_kind="evaluation_wallet"` service
path into `scripts/collect_behavioral_evidence.py` via new
`--subject-kind {candidate_or_anchor,evaluation_wallet}` (default
unchanged) and `--evaluation-registry PATH` (default
`data/evaluation_wallets.csv`, matching `materialize_evaluation_dataset.py`/
`evaluation_readiness_report.py`'s own `--registry` default) flags.
Evaluation-wallet mode calls
`collect_behavioral_evidence_for_evaluation_wallet` instead of
`collect_behavioral_evidence`, refuses `--write` at the CLI level before
any network activity, and never reads/writes `--data-dir`'s
`deposit_candidates.csv`/`verified_anchors.csv`/`behavioral_evidence.csv`.
Default candidate/anchor CLI usage (no new flags) is unchanged.

Added `api/tests/test_collect_behavioral_evidence_cli.py` (5 tests,
respx-mocked, no live network call): `--help` documents both modes;
default-mode CLI behavior unchanged; an accepted evaluation wallet is
admitted via the CLI with `manifest.json` recording
`subject_kind: "evaluation_wallet"`; a quarantined evaluation wallet is
refused with a clear stderr message and no bundle written; `--write` in
evaluation-wallet mode is refused before any network activity (test runs
with no respx interceptor registered at all, so any attempted HTTP call
would itself fail the test). All protected CSVs (`verified_anchors.csv`,
`deposit_candidates.csv`, `review_log.csv`, `evaluation_wallets.csv`,
`evaluation_review_log.csv`) are hash-verified unchanged by each scenario.

Also personally ran, offline, in this session (no live network call):
`scripts/evaluation_readiness_report.py --registry ../data/evaluation_wallets.csv
--evidence-root ../var/collect-behavioral-evidence/by-wallet` (real,
current output: `status: "NOT_READY_FOR_REAL_EVALUATION"`, 2 real
evaluation wallets on file, 0 materialized real windows) and
`scripts/materialize_evaluation_dataset.py` with the same registry/
evidence-root (dry run: 0 materialized rows, 1 skipped as
`missing_evidence` for the accepted TronBid wallet, since no saved
evidence bundle exists yet at
`var/collect-behavioral-evidence/by-wallet/tron/TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM/`).

No live TronGrid call was made or attempted. No model was trained. Nothing
was committed. Full suite: 437 passed / 1 deselected (432 baseline + 5
new); `ruff check .` and `mypy app` both clean (57 source files).
See `docs/DECISIONS.md` (2026-09-21, "Stage 3B.3 CLI wiring") for the
flag-naming and registry-default-path rationale.

## Stage 3C — Isolation Forest ranker, fitted on synthetic rows only (2026-09-21)

Implemented the `extract_features` / `train_anomaly` / `score_anomaly` core of
Stage 3C. **No model was trained on real data and no held-out evaluation was
run** — the corpus still has 0 accepted-and-materialized real windows, so the
only honest end-to-end run is a SYNTHETIC pipeline demonstration. This is
Order 2; held-out evaluation/reporting (Order 3) and console wiring (Order 4)
remain.

- `api/app/services/anomaly_ranking.py` (new). A deterministic Isolation Forest
  (scikit-learn) over a fixed, versioned, numeric-only allowlist
  (`ANOMALY_FEATURES`, `ANOMALY_FEATURE_VERSION`). It is carried *separately
  from* attribution evidence: a score is a review-priority ordering, never a
  probability, fraud likelihood, service label, or ownership claim.
  - `extract_features` pulls the curated features into a numeric matrix,
    leaving missing cells as `None` and rejecting non-numeric values.
  - `train_anomaly` fits `IsolationForest(random_state=seed, n_jobs=1)` and
    records seed, `MODEL_VERSION`, both feature versions, sample-selection
    method, training cutoff, and the exact training row keys. Deterministic
    for a fixed seed; a computability floor (`MIN_TRAIN_ROWS`) is explicitly
    *not* a claim of sample adequacy.
  - `score_anomaly` returns rows most-isolated first with a contiguous
    `rank`, the raw observed feature values, and the list of imputed features.
  - Missing data is imputed at the per-feature **train median** (0.0 only if a
    feature is entirely missing in train), so missingness is never scored as
    suspicious.
  - `assert_no_training_overlap` enforces "never fit and evaluate on the same
    rows" on row identity for the upcoming evaluation step.
  - `synthetic_demonstration_rows` is a clearly-labelled SYNTHETIC-only set
    (ordinary wallets, marketplace-like and treasury-like operational
    confounders, burst-and-forward shapes) used solely to show the pipeline
    runs; nothing in it is a claim about a real wallet.
- `scripts/anomaly_ranking.py` (new) — offline CLI. Trains on the synthetic
  set, scores a `split_by_wallet` holdout, and prints JSON tagged
  `"evaluation_kind": "pipeline_demonstration"`, `"data_mode": "SYNTHETIC"`,
  `"real_data_used": false`. It reports no accuracy/precision/recall/AUC. In
  the default run the top-ranked holdout rows are the marketplace-like
  confounder — the documented caveat that operational confounders can rank
  high on shape alone, which is exactly why the rank is not a fraud signal.
- Dependency: `scikit-learn` 1.9.1 (+ `numpy` 2.5.3, `scipy` 1.18.1) added to
  `api/pyproject.toml`/`uv.lock`. Rationale in `docs/DECISIONS.md`
  (2026-09-21, "Stage 3C: a synthetic-only Isolation Forest").
- `evaluate_anomaly` in the same module (Order 3): scores a held-out split and
  compares the ranking against a **predeclared** `AnalystRubric` and a
  random-ranking baseline.
  - The rubric declares three disjoint sets — review-worthy, known confounder,
    and independently-established negative. A row whose `control_category` is
    `None` or outside the rubric is excluded from every ratio and counted,
    never treated as a negative (an unevaluated wallet is not "clean").
  - `review_worthy_precision_at_k` is over LABELED rows in the top k. If the
    split has zero review-worthy rows the metric is **null, not 0.0**, with a
    stated reason. The baseline is the exact expected precision of a uniformly
    random ranking (the positive base rate) — no sampling randomness.
  - Known operational confounders are surfaced: `confounder_ranks`,
    `confounders_in_top_k`, `confounder_fraction_at_k` vs `confounder_base_rate`.
  - `evaluate_anomaly` refuses to score rows the model was trained on.
- `api/app/reports/anomaly_evaluation.py` (new) — a self-contained HTML report
  for one held-out evaluation, separate from the attribution/service-outcome
  reports; it states the run does not measure criminal guilt, ownership,
  service identity, or fraud.
- `scripts/anomaly_ranking.py` grew `--k` and `--html-out` and now emits an
  `evaluation` section alongside `model`/`scores`.
- **Demonstration result (reported as-is):** on the synthetic set the ranker
  ranks the marketplace-like confounder 1st/2nd and does not surface the
  burst-and-forward "review-worthy" shape in the top 5 —
  `review_worthy_precision_at_k: 0.0` against a `0.2` random baseline,
  `confounders_in_top_k: 2` of 5. That is an honest, unflattering result from a
  toy ranker; it is left visible rather than tuned away.
- 18 tests in `api/tests/test_anomaly_ranking.py` (determinism, rank
  contiguity, raw-vs-transformed values, missing-is-not-suspicious, the
  fit/eval overlap guard, no-metric metadata, SYNTHETIC labelling, the offline
  CLI, bidirectional isolation greps) plus 11 in
  `api/tests/test_anomaly_evaluation.py` (rubric disjointness, consistent
  ratios, unlabeled/outside exclusion, null-not-zero, overlap refusal, k>=1,
  demonstration-vs-held-out labelling, determinism, no-guilt/no-probability,
  rendered-HTML caveat). Full suite now **517 passed / 1 deselected**;
  `uv run ruff check .` and `uv run mypy app` both clean (63 source files).

**Order 4 — console/dashboard surface (2026-09-21).** The ranker is now shown
in the read-only console, kept strictly separate from the evidence:
- `app.services.demo_presets.load_anomaly_evaluation` reads the saved report
  from the allow-listed `var/anomaly-evaluation/report.json`; the request path
  never fits or scores anything.
- `_anomaly_evaluation_card` renders it on the dashboard and the console
  sidebar: badge **SYNTHETIC DEMONSTRATION** (or *held-out evaluation*), rubric,
  split, review-worthy precision@k vs the random-ranking baseline, confounder
  ranks, top-ranked rows, and the caveats. A null precision shows as *not
  computable*; the card states it is not an accuracy claim and changes nothing
  about the trace result.
- `build_capabilities` now marks `ml_anomaly_ranking` and `held_out_evaluation`
  as **partial** (implemented, synthetic-only, no real model) rather than
  `blocked`. `partial` is never read as validated.
- `docs/DEMO_RUNBOOK.md` step 17 walks the demo through the card and the
  offline command that writes the report.
- 6 new console tests; full suite now **523 passed / 1 deselected**;
  `uv run ruff check .` and `uv run mypy app` both clean (63 source files).

**Explicitly not done in this increment:** training on real evaluation
windows (a real held-out precision/coverage evaluation), persisting a model
artifact to disk by default, new-event monitoring, and any export beyond the
existing HTML/JSON report.

## Order 1 tooling — evaluation-wallet review wizard (2026-09-21)

Order 1 (human review of evaluation wallets + saved windows) is the external
blocker on all real training/evaluation. `scripts/review_evaluation_wizard.sh`
(committed, `chmod +x`) turns it into one guided, idempotent run per wallet:

1. capture the TronGrid key into `api/.env`;
2. register an independently-sourced wallet via `ingest_evaluation_wallet.py`
   (prompts for the source URL/evidence type — the wizard never invents a
   source — dry-run then confirm before `--write`);
3. review it via `review_evaluation_wallet.py` (packet, then dry-run, then
   confirm before `--write`);
4. capture one saved window via `collect_behavioral_evidence.py
   --subject-kind evaluation_wallet` (network; bundle-only);
5. materialize + regenerate `var/evaluation-readiness/readiness.json`.

The wizard never decides a review, never fabricates a source, and gates every
write behind a dry-run plus an explicit confirmation. Its non-network stages
were validated offline: `ingest` dry-run and the review packet leave
`data/evaluation_wallets.csv` and `data/evaluation_review_log.csv`
byte-identical; `materialize` dry-run and the readiness CLI both run clean.
Referenced from `README.md`.

## Stage 4 prototype — read-only investigator console (2026-09-21)

A demo-ready, local GUI was added without starting Stage 3C ML. It is one
server-rendered screen over already-saved artifacts; it trains no model,
makes no live provider call, and reads no database or case data.

- `api/app/services/demo_presets.py` — a server-side allow-listed registry of
  two presets and a loader. Every path is resolved under the repository root
  and anything outside it is refused (`PresetPathError`). A missing artifact is
  recorded as a warning, or an `error` when the trace itself is missing, never
  an empty success. Also reads the existing readiness output and counts
  evaluation-wallet review states with a read-only `csv.DictReader` (it never
  imports the writer service).
- `api/app/reports/console.py` — the HTML renderer. Panels: data-mode badge,
  result summary, the eight independent status axes, chronological transfer
  table, a simple CSS path, label/manifest provenance, limitations, supporting
  behavioral acquisition, report/export links, and the readiness card. Every
  value is escaped; amounts stay strings; `allocation_unknown` and the
  "recorded/synthetic is not live" statements are always visible.
- `api/app/routes/console.py` — `GET /console` plus saved-report routes
  (`/console/evidence|comparison|outcome|behavioral/{preset}`). Read-only,
  allow-listed, no auth dependency because the surface exposes only saved
  public/synthetic evidence, never case data.
- Presets: **recorded-okx-direct** (RECORDED_PUBLIC, the saved Stage 1 replay
  bundle plus the Stage 3A `supported_destination` OKX outcome) and
  **synthetic-multihop** (SYNTHETIC, 8 transfers, 4 branch endings including
  two unresolved).
- `api/tests/test_console.py` — 22 tests: escaping of hostile label/source
  text, exact string amounts, all eight axes present, candidate-lead never
  rendered as supported, unknown ownership not rewritten as service ownership,
  mode labels, error/partial not rendered as empty success, path-escape
  refusal, and route integration against the saved artifacts (skipped if the
  checkout has no `var/` bundles).
- `docs/DEMO_RUNBOOK.md`, a README "Quick demo" section, `scripts/run_demo.sh`,
  and a `make demo` target.
- Full suite: **459 passed / 1 deselected** (437 baseline + 22 new);
  `ruff check .` and `mypy app` clean (60 source files). Frontend `oxlint` and
  `tsc -b && vite build` both clean. No ML model was trained; no protected
  evidence or review file was modified; `ppt/` untouched.

### Improvement loop on the console (same session)

A second pass tightened correctness, size, and extensibility:

- `app/reports/evidence.py` now falls back to the older `provider_requests` /
  `provider_request_limit` budget names, so a saved trace that predates the
  `traversal_requests` rename renders instead of raising. Covered by a
  regression test.
- Saved bundles are **discovered automatically** from
  `var/live-validation/*/trace.json` (`discover_presets`/`all_presets`) and
  appended after the curated ones. A discovered bundle is **always presented
  as RECORDED_PUBLIC**, whatever its capture-time `data_mode`, with the capture
  mode stated as text — a file on disk must never wear a LIVE badge (tested).
- The readiness card now lists each sourced evaluation wallet with its review
  state and its on-disk materializable-window eligibility (via the existing
  `domain_eligibility_for_wallet`), so "not ready" is actionable per wallet.
- The behavioral panel inlines a 15-row preview and links to the full saved
  bundle instead of embedding all rows: the recorded console page dropped from
  ~194 KB to ~43 KB.
- Address input is canonicalized with the existing TRON validator: a malformed
  address is reported as invalid, distinctly from a valid address with no saved
  result.
- Print hides the sidebar so "Print / Save PDF" produces the result only, and
  adds a print-only run header. A `/console/trace/{id}` route exports the saved
  trace JSON; `/console` is now gated off in `prod`.
- The seed transfer is now a first-class fact on the trace result:
  `TraceResult.seed_transfer` (serialized as `seed_transfer`) is populated from
  the run's own saved seed event, and both the console and the printable
  evidence report show it as hop 0. A direct seed-to-boundary trace now shows
  its one transfer instead of an empty transfer table; older saved results that
  predate the field fall back to the labelled branch-arrival derivation.
  `make trace-demo` was re-run to regenerate the synthetic demo outputs
  (`var/trace.json`, `var/trace-report.html`), which are demo artifacts, not
  evidence.
- Full suite: **469 passed / 1 deselected** (468 + 1 new); `ruff check .` and
  `mypy app` clean (60 source files).

### Console UI and animation pass (same session)

- **Shneiderman's eight golden rules** applied to `app/reports/console.py`:
  consistency (endpoint status text + colour, one vocabulary), universal
  usability (skip link, `role="banner"`/`main`/`contentinfo`, `aria-live`,
  automatic `prefers-color-scheme: dark`, `prefers-reduced-motion`, responsive),
  informative feedback (live copy/step captions, hover/active/focus), closure
  (walkthrough ends on the actual result; report caveats), error prevention
  (fixed network/asset, canonicalized address, safe presets), easy reversal
  (Play/Step/Replay, Esc stops motion), user control (explicit controls), and
  reduced memory load (step indicator, colour legend with text labels).
- **Two animations**, CSS/SVG + vanilla JS only (no new dependency):
  1. a generic **"How this works"** walkthrough (saved evidence → tracer →
     branch endings → label match → outcome), whose final step is filled from
     the selected saved result, with Play/Pause/Step/Replay and an `aria-live`
     caption; autoplays on load unless `prefers-reduced-motion: reduce`;
  2. **"Replay this path"** on the observed-path card, lighting each node and
     edge in order.
- Tested: step count/controls, absence without a trace, reduced-motion and
  dark-mode CSS present, replay `data-order` attributes, landmark/skip-link,
  no external `<script src>`, and no `accuracy`/`auc`/`AI-powered` language.
  The embedded JavaScript is syntax-checked (`node --check`).
- Full suite: **474 passed / 1 deselected** (469 + 5 new); `ruff check .` and
  `mypy app` clean (60 source files); frontend `oxlint`/`vite build` clean.

### Three-page site, dashboard, and artifact-warning fix (same session)

- The console grew into a three-page read-only site sharing one shell, nav, CSS,
  and animation script:
  - `/` — **Overview**: key features, "what it will not do", and the generic
    how-it-works walkthrough (no case result).
  - `/console` — the investigator **Demo** (existing).
  - `/dashboard` — **status**: saved-run tiles, per-run table (mode, seed,
    transfers, branches, unresolved, outcome), outcomes-on-file counts,
    readiness card, evaluation-wallet table, and standing limitations.
  All three are registered only when `app_env is not prod`, alongside the
  console.
- New `app.services.demo_presets.summarize_presets()` aggregates saved runs for
  the dashboard. It reports an outcome category only when a Stage 3A record is
  saved; otherwise it says "Not recorded" rather than inventing one.
- **Fixed the spurious warnings.** `load_preset` now warns only when a preset
  *declares* an artifact that is missing. A trace-only/synthetic preset has no
  Stage 2 comparison or Stage 3A outcome by design, so the console shows a
  neutral one-line note in the report panel instead of a yellow warning. New
  `DemoView.has_outcome`/`has_comparison`/`has_report` drive the report buttons.
- Full suite: **480 passed / 1 deselected** (474 + 6 new); `ruff check .` and
  `mypy app` clean (60 source files); embedded JS `node --check` clean.

### Operational status: capability matrix and bundle integrity (same session)

The remaining gaps (ML, evaluation, monitoring, connectors) are now stated
plainly and grounded in real state instead of being implied.

- New `app/services/operational_status.py`:
  - `build_capabilities(...)` returns one row per capability with status
    `available` / `partial` / `not_built` / `not_configured` / `blocked`,
    derived from the saved readiness report and the live settings. The anomaly
    ranker and held-out evaluation are `blocked` while no model exists; live
    acquisition reflects whether a TronGrid key and LIVE mode are configured;
    monitoring, government connectors, and multi-chain are `not_built` /
    `not_configured`. It emits no accuracy/AUC/metric of any kind.
  - `verify_manifest_hashes(manifest, base_dir)` re-hashes each file a saved
    bundle's manifest lists and reports `ok` / `mismatch` / `missing`, with the
    manifest's own caveat repeated: a match shows the files are unchanged since
    the run, not that the attribution is correct.
- Dashboard gained two cards: **Capabilities and status** and
  **Saved-bundle integrity** (per-run file count, match, mismatch, missing, and
  a verdict). The recorded and discovered bundles verify "all match".
- `summarize_presets()` now carries each run's integrity summary.
- Full suite: **486 passed / 1 deselected** (480 + 6 new); `ruff check .` and
  `mypy app` clean (61 source files).

## Stage 4 — evidence export bundle (2026-09-22)

The second Stage 4 sub-part: upgrading the Stage 1 printable HTML report to a
generated PDF plus CSV/JSON package with file-integrity hashes, per
`docs/FIVE_STAGE_PLAN.md`'s Stage 4 spec. Full rationale in `docs/DECISIONS.md`
D026; summary here.

- `api/app/services/evidence_export.py` — `build_evidence_bundle(result, ...)`,
  a pure function (no I/O) building `evidence.json`, `evidence.html`,
  `evidence.pdf`, `transfers.csv`, `branch_endings.csv`, `labels.csv`,
  `limitations.csv`, and a manifest from one trace result dict.
- `POST /api/v1/traces/export` (new, alongside the existing `/traces` and
  `/traces/report` routes) zips the bundle and returns it as
  `application/zip`.
- The PDF is rendered (new dependency: `xhtml2pdf`) from the *exact* HTML
  string `app.reports.evidence.render_evidence_html` already produces, so the
  PDF and the on-screen/printable report can never disagree — there is one
  template, not two.
- The manifest's `files` field is `{relative filename: sha256 hex}`, matching
  the shape every other manifest in this project already uses
  (`live_validation.py`, `collect_resource_evidence.py`,
  `collect_behavioral_evidence.py`), so it needs no adaptation to be checked
  by the existing `app.services.operational_status.verify_manifest_hashes` —
  proven by a new test that round-trips a built bundle through that exact
  function, not just asserted.
- **Known, documented non-determinism**: `evidence.html`'s "Generated at ..."
  line is `datetime.now()`-stamped independent of the bundle's own
  `generated_at` parameter (pre-existing Stage 1 report behaviour), and
  `xhtml2pdf`/`reportlab` embed their own PDF creation-time metadata — so
  those two files' hashes are not reproducible across two builds of the same
  trace result, while `evidence.json` and every CSV file are.
- **Not done in this increment**: no server-side persistence of a generated
  bundle (nothing is written under `var/`; the zip is built and returned
  per-request), no signature beyond a plain SHA-256, checkpointed new-event
  monitoring, draft legal-request generation, and the mock complaint adapter
  (Stage 4's other two sub-parts) are untouched.
- Full suite: **642 passed / 1 deselected** (628 measured baseline on this
  working tree + 14 new: 13 in `api/tests/test_evidence_export.py`, 1 in
  `api/tests/test_trace_endpoint.py`); `ruff check .` clean; `mypy app` clean
  (66 source files).

## Stage 4 — legal-request drafts (2026-09-22)

The third Stage 4 sub-part: information/preservation/asset-restriction
request drafts, marked DRAFT / INVESTIGATOR REVIEW REQUIRED, per
`docs/FIVE_STAGE_PLAN.md`'s Stage 4 spec. Full rationale in
`docs/DECISIONS.md` D027; summary here.

- `api/app/services/legal_requests.py` — `build_request_draft(result, *,
  request_kind, target_address, requesting_agency, requesting_officer,
  case_reference, alleged_incident_summary, ...)`, a pure function (no I/O,
  no send) building a `RequestDraft` against one branch-ending address from
  an already-run trace result.
- `POST /api/v1/traces/legal-request-draft` (JSON) and `POST /api/v1/
  traces/legal-request-draft/report` (HTML, `api/app/reports/
  legal_request.py`, reusing `evidence.py`'s stylesheet).
- **Field checklist sourced from a real, fetched provider guide**: OKX's own
  published law-enforcement request guide, retrieved 2026-09-22
  (`CHECKLIST_SOURCE`) — agency identification, legal-authority reference,
  items requested, incident overview, investigation amount, account
  identifiers, and wallet/transaction identifiers "in a copiable format",
  which points to this session's own `/traces/export` bundle rather than
  duplicating it.
- **Structural pooled-wallet refusal**: an `asset_restriction` draft against
  an address whose label `address_role` is `hot_wallet`/`cold_reserve`/
  `settlement`, or whose role is not established at all (`unknown` or no
  label), comes back `status="refused"` with a stated reason -- never an
  exception, never a silently-drafted freeze request. Demonstrated against
  **real data, not only the synthetic fixture**: both real accepted anchors
  in `data/verified_anchors.csv` are `address_role=unknown` today, so an
  asset-restriction draft against either is refused as this codebase stands.
  `information`/`preservation` drafts are unaffected by this rule.
- `investigation_findings_to_date` is auto-filled from the trace's own
  recorded facts (seed/target address, endpoint class, attribution status),
  not free text.
- **Not done in this increment**: nothing is ever sent to a provider; no
  signature/letterhead generation; no persistence of a drafted request;
  checkpointed new-event monitoring and the mock complaint adapter (Stage 4's
  other two sub-parts) are untouched, and `operational_status.py`'s existing
  `government_connectors` capability row is unaffected.
- Full suite: **674 passed / 1 deselected** (642 baseline + 32 new: 21 in
  `api/tests/test_legal_requests.py`, 6 in `api/tests/test_legal_request_
  report.py`, 5 in `api/tests/test_trace_endpoint.py`); `ruff check .` clean;
  `mypy app` clean (68 source files).

## Stage 4 — mock complaint queue (2026-09-22)

The fourth and last Stage 4 sub-part besides monitoring: "provide a clearly
marked mock complaint adapter only", per `docs/FIVE_STAGE_PLAN.md`. Full
rationale in `docs/DECISIONS.md` D028; summary here.

- `api/app/services/mock_complaint_adapter.py` — reads exactly one file,
  `fixtures/mock_complaints.json` (3 fictional complaints), no network call,
  no credential. Every record and every API response carries
  `source_channel: "MOCK_LOCAL_QUEUE"`; the loader refuses to read a file
  that doesn't declare that exact channel.
- `GET /api/v1/complaints/mock`, `GET /api/v1/complaints/mock/
  {complaint_reference}`, `GET /api/v1/complaints/mock/{complaint_reference}/
  seed-draft` (`api/app/routes/mock_complaints.py`) — all require
  authentication (`CurrentUser`), per Stage 4's own requirement.
- **Creates nothing.** `mock_complaint_to_seed_draft` only shapes a suggested
  seed payload (`token_contract`, not a fabricated `asset_id`, since this
  module has no database access) for a human to review and submit themselves
  through the existing `POST /api/v1/cases/{case_id}/seeds` route -- no
  parallel case-creation path was added.
- **Demonstrated as a connected pipeline, not just a shape**: one fixture
  complaint intentionally names the same address/asset/seed event as the
  existing SYNTHETIC trace fixture, and a test actually posts that
  complaint's own seed-draft output to the real `/api/v1/traces` endpoint and
  gets back the real supported-destination result.
- Small adjacent fix made while here: `GET /api/v1/meta`'s hardcoded
  `capabilities.evidence_export` (unrelated to `operational_status.py`) was
  stale at `False` since the D026 export route shipped; flipped to `True`.
  `operational_status.py`'s capability matrix gained `legal_request_drafts`
  and `mock_complaint_queue` rows, and its `evidence_export`/
  `government_connectors` detail text was refreshed to describe current
  reality instead of D026-era placeholder text.
- **Not done**: no persistence/claimed-state tracking, no PII-handling
  machinery, no real NCRP/SAHYOG credential or endpoint anywhere.
  Checkpointed new-event monitoring -- the one remaining Stage 4 item -- is
  untouched.
- Full suite: **692 passed / 1 deselected** (674 baseline + 18 new: 11 in
  `api/tests/test_mock_complaint_adapter.py`, 7 in `api/tests/test_mock_
  complaints_route.py`); `ruff check .` clean; `mypy app` clean (70 source
  files).

## Stage 4 — checkpointed new-event monitoring (2026-09-23)

The last Stage 4 sub-part. Full rationale in `docs/DECISIONS.md` D029; test rows in
`docs/ACCEPTANCE_CATALOG.md` ("Stage 4 — checkpointed new-event monitoring").

**What monitoring now does.** A watch is `(case, network, canonical address, exact
verified TRC-20 contract, data mode)`. `scripts/poll_watches.py --once` runs one
bounded poll per active watch and exits: fetch
`[checkpoint - overlap, now]` through the existing `ChainAdapter.fetch_transfers`
(all pages, up to a page budget) → collapse repeats by `event_reference` →
verify execution through receipts where the source is TronGrid → exclude
approvals, failed/reverted, removed, zero-value, wrong-contract,
not-involving-the-address and before-scope events (each with a reason) → one
alert per new event under the database's `UNIQUE(watch_id, dedupe_key)` →
advance the checkpoint only if the whole window was read without error. Alerts,
alert state changes, the checkpoint and the poll-run audit row are committed
together. A later `removed`/`failed`/`reverted` observation retracts an alert
(never deletes it); `provisional → confirmed` is recorded in its history.

- `api/app/services/monitoring.py` — `create_watch`, `poll_watch`,
  `poll_enabled_watches`, serializers.
- `api/app/models/casework.py` — `Watch`/`Alert` columns filled in (they were
  reserved empty), new `WatchPollRun`; enums `WatchPollStatus`, `AlertState`.
- `api/migrations/versions/4c0696953d8d_...` — checked on SQLite with upgrade,
  `alembic check` (no drift), downgrade and re-upgrade. It refuses to run over
  pre-existing watch/alert rows. **Not run on PostgreSQL. Not applied to the
  local `var/cfa.db`:** run `make migrate` before using the API against it.
- `api/app/routes/watches.py` — `POST/GET /api/v1/cases/{id}/watches`,
  `GET .../{watch_id}`, `.../alerts`, `.../polls`. All are case-authorized, so a
  foreign org gets 404. Polling is not an HTTP route.
- `scripts/poll_watches.py`, `scripts/monitoring_demo.py`,
  `fixtures/tron_synthetic_monitoring.json`, and `make poll-watches` /
  `make monitor-demo`.
- Capability row `monitoring`: `not_built` → **`partial`** (tested offline, no
  live poll verified). `/api/v1/meta` `capabilities.monitoring`: `False` →
  `"POLLING_ONLY"`. `test_console.py`'s capability test was updated to that
  state and now also asserts "not a mempool feed" (a changed expectation, not a
  weakened one). There is no dashboard card for watches or alerts: those are
  case data, and the dashboard is unauthenticated.

**Demonstration (SYNTHETIC, offline, injected clock):** `make monitor-demo`
prints new alerts per step as `1, 1, 0, 0`:
- poll at 10:10: E1 is new;
- poll at 10:20: E1 repeated, E2 new, the approval excluded;
- the same poll again in the same process;
- the same poll from a separate `poll_watches.py` process (restart).

That leaves 2 alerts in total, and the summary is written to
`var/monitoring-demo/summary.json`.

**Tests actually run.** `uv run pytest -q`: **733 passed / 1 deselected** (692
baseline measured on this working tree at the start of the session, + 41 new in
`api/tests/test_monitoring.py`). The deselected test is the existing opt-in
live-network test. `uv run ruff check .`: clean (the two new scripts also checked
explicitly). `uv run mypy app`: clean, 72 source files. The new tests catch four
deliberately injected faults: dedupe by tx hash, advancing the checkpoint on
failure, no overlap, and ignoring execution status.

**No live call was made.** No TronGrid key is configured. The TronGrid path is
exercised offline through `respx` with the documented response shapes: history,
event index, receipt verification (SUCCESS alerts, REVERT excluded), and HTTP
429 as a provider failure. **No protected file changed**: `verified_anchors.csv`,
`deposit_candidates.csv`, the review logs, the evaluation registry and the
`var/live-validation/` bundles are untouched.

**Known limitations.**
- Polling of indexed, confirmed history, not a mempool feed; nothing pending is
  seen.
- TRON and one verified TRC-20 contract only.
- The checkpoint is a block-time frontier. The 600 s default overlap is a
  configured margin; the provider's indexing lag is unmeasured, and events
  indexed later than the overlap would be missed.
- TronGrid exposes no removed-event signal, so live retraction can only come
  from a receipt.
- An alert whose receipt cannot be read stays `execution_status=unknown`.
- A window that never fits the page budget reports `truncated` on every poll
  until `--max-pages` is raised.
- No live observation lag has been measured.
- No external notifications or automatic action; the explicit local outbox only
  writes pending evidence packages. No global provider budget is shared across
  traces and watches (T12 still open).
- Watches are created and read through the API; polling is CLI-only.

## Stage 4 — investigator notification outbox (2026-09-26)

The monitoring path now has an explicit local delivery seam for new alerts. It
does not send email, call a webhook, publish to a queue, or contact NCRP,
SAHYOG, a VASP, or any other external system.

- app/services/alert_notifications.py turns a persisted, case-scoped alert
  into a LOCAL_EVIDENCE_OUTBOX package containing case/watch context, the exact
  event reference, execution/finality state, stored acquisition evidence,
  limitations, and state history.
- scripts/poll_watches.py --notification-out <directory> writes one JSON package
  per newly created alert plus a SHA-256 manifest. LIVE captures default to
  <capture>/notifications; fixture runs require the explicit option.
- Delivery is visibly pending and external_send=false. A future delivery worker
  still needs authentication, retry/acknowledgement semantics, and
  agency-specific approvals before any external channel is enabled.
- The package writer has a focused regression test; the existing offline
  monitoring demo still reports 1, 1, 0, 0 new alerts across its four polls.

## Stage 4 — fund-flow graph page (2026-09-23)

A **Fund flow** page (`/graph?preset=<id>`, in the site nav, linked from the Demo's
Path card) draws one saved trace result as a directed multigraph: one box per
distinct wallet, one arrow per observed transfer, laid out left to right by hop.
Built from `api/app/reports/fund_flow.py` (pure model and layout, then inline SVG)
plus small vanilla JS for selection. No new dependency and no external script.
`GET /console/graph/{preset_id}` returns the same model as JSON. Like the console,
it is registered only outside `prod` and reads only saved, allow-listed artifacts.

- **What is drawn.** Observed token transfers only, the seed transfer included.
  Resource delegations, TRX funding and inferred control relationships are not
  arrows, and the page says so. A wallet reached by two branches is one node; two
  transfers between the same wallets, or in one transaction, are two edges.
  Colours come from the tracer's recorded branch endings. A candidate lead is
  drawn dashed amber and labelled "not verified", never as a supported service.
  Conflicting endings at one address are drawn as a conflict rather than letting
  the stronger class win.
- **Honesty details.**
  - Amounts are the saved strings and nothing is summed (no total implies a
    case-attributable amount).
  - Ordering-ambiguous transfers are dashed.
  - Left-to-right is hop order, not chain order.
  - A cycle falls back to breadth-first layers, with a warning.
  - The tracer records a branch that rejoined an explored path as an `unresolved`
    ending with no boundary reason. The graph draws that wallet as a
    reconvergence point, not a boundary, and counts it separately.
- **Older saved results.** `recorded-okx-direct` predates the stored
  `seed_transfer`. Its seed-to-OKX transfer (72.140000 USDT) is reconstructed only
  because the branch's arrival event is the seed event, so the sender is known.
  It is drawn dotted and labelled "reconstructed"; its block time and execution
  are shown as not recorded. A missing non-seed event is reported, not invented.
- **Verified in a real browser** (headless Chromium, light and dark).
  - Checked on the synthetic multihop and recorded OKX presets: node click,
    transfer click, branch highlight, Esc, keyboard Enter, zoom, and fit-to-width
    (60% floor).
  - The only console error is the pre-existing `/favicon.ico` 404.
- Tests: 24 new in `api/tests/test_fund_flow.py`. The new tests catch three
  deliberately injected faults: no reconvergence rule, no JSON escaping, and no
  event-reference dedupe. Full suite **757 passed / 1 deselected** (733 + 24).
  `ruff check .` is clean; `mypy app` is clean on 73 files.
- **Not done:** no graph in the React `frontend/` shell, and no delegation or
  funding overlay (it would need its own visually distinct edge type). Layout is a
  layered heuristic, so large graphs (>60 edges) hide per-edge amount labels,
  which remain in the table.

## Live validation milestone — 2026-09-26

The first bounded LIVE validation was run with the configured TronGrid key. It
used the known TRON/USDT-TRC20 transfer from
`TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq` to the reviewed OKX address
`TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir`.

- Run: `var/live-validation/20260926T070828Z-c53a38/`
- Provider exchanges: 3
- Data mode: `LIVE`
- Coverage: `complete_within_scope`
- Result: `known_service`, OKX
- Reviewed registry snapshot: 2 accepted service claims and 1 unreviewed candidate
- Bundle: raw responses, normalized output, receipt data, label snapshot, HTML
  report, and SHA-256 manifest
- Secret check: the API key was not written to any bundle file
- Replay: the bundle was replayed successfully in `RECORDED_PUBLIC` mode through
  the same parser and tracer (`var/live-validation/20260926T072054Z-f96dac/`)
- Receipt correctness: verified execution/finality is now propagated into the
  seed/onward transfer rows in `trace.json` and the HTML report; a regression
  test prevents the trace from reverting to history-endpoint `unknown` values

This proves the end-to-end live path for one bounded public example. It does not
prove broad attribution coverage, continuous exchange control, or customer-
deposit status. The candidate sender remains unreviewed.

## Evaluation capture milestone — 2026-09-26

The accepted TronBid operational-confounder wallet was captured through the
same live TRON provider path used for candidate evidence. Evaluation-wallet mode
is bundle-only, so no attribution or review CSV was changed.

- Wallet: `TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM`
- Window: `2026-09-01T00:00:00Z` to `2026-09-26T00:00:00Z`
- Bundle: `var/collect-behavioral-evidence/by-wallet/tron/TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM/20260926T071207Z-1d803e/`
- Provider requests: 8
- Rows: 3, with 2 outgoing and 1 incoming
- Page, event, and request-budget truncation: none
- Materialized real windows: 1
- Readiness: `NOT_READY_FOR_REAL_EVALUATION`

The remaining evaluation blocker is structural: a wallet-separated train/eval
split needs at least 2 distinct accepted materialized wallets. The quarantined
self-custody record is not used as evaluation truth. The materialization CLI
also gained a regression fix for datetime provenance fields and now writes the
derived JSON dataset successfully.

## Working-tree state

Nothing from this session (or the Stage 2/3A session before it) is
committed yet — `git log` still ends at `241f7c9` ("Add deterministic
resource evidence and feature extraction"). Everything described above is
currently untracked in the working tree, ready to be committed when asked.
