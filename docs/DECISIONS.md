# Decisions

Numbered, dated, and revisable. A decision reversed gets a new entry, not an edit.

---
## D001 — Stack
**2026-09-19. Accepted.**

Python 3.12 / FastAPI API and worker, PostgreSQL, React + TypeScript frontend,
Redis with `arq` as the single worker library, Docker Compose for local
infrastructure.

Versions resolved and locked on 2026-09-19 (`api/uv.lock`, `frontend/package-lock.json`):

| Package | Version |
|---|---|
| fastapi | 0.141.1 |
| starlette | 1.6.0 |
| uvicorn | 0.53.0 |
| pydantic | 2.13.5 |
| pydantic-settings | 2.15.0 |
| sqlalchemy | 2.0.54 |
| alembic | 1.20.0 |
| psycopg (binary) | 3.3.6 |
| arq | 0.28.0 |
| redis | 5.3.1 |
| argon2-cffi | 25.1.0 |
| itsdangerous | 2.2.0 |
| structlog | 26.1.0 |
| httpx | 0.28.1 |
| base58 | 2.1.1 |
| pytest | 9.1.1 |
| ruff | 0.16.8 |
| mypy | 2.3.1 |

**Why:** this is the stack the playbook proposes, and it is a recommended simple
architecture rather than a benchmarked winner. No graph database, Kafka,
Kubernetes, full node, token, or smart contract — none is a prerequisite for a
read-only prototype, and each would add operational surface we cannot staff.

**One of each:** SQLAlchemy + Alembic is the only ORM/migration path. `arq` is
the only worker library. Adding a second of either requires a new decision entry.

---
## D002 — Address identity is `(network, canonical_address)`
**2026-09-19. Accepted.**

Never `address` alone. The original supplied string is preserved alongside the
canonical form. The same hex string is a valid address on every EVM chain, so
network can never be inferred from syntax; intake requires an explicit choice
whenever syntax is ambiguous.

---
## D003 — Asset identity is `(network, native_asset_id | token_contract)`
**2026-09-19. Accepted.**

Symbols are display metadata. "USDT" is not an identifier — dozens of contracts
claim it. Production asset rows must record an issuer/chain source reference and
a verification timestamp before they leave `SYNTHETIC` mode.

---
## D004 — Amounts are integers in base units
**2026-09-19. Accepted.**

Postgres `NUMERIC(78,0)`, Python `int`, JSON **string**. 78 digits covers a
`uint256` (~1.16e77). No float, no `Decimal` arithmetic on the storage path, no
JavaScript `Number` anywhere near an amount. Display conversion is exact decimal,
done once, at the edge.

---
## D005 — Event identity is chain-specific, never the transaction hash
**2026-09-19. Accepted.**

One transaction can carry many transfers. Deduplicating by `tx_hash` destroys
real evidence. Canonical form of `event_reference`:

- TRON TRC-20: `tron:<tx_hash>:<event_index>`
- EVM logs: `evm:<chain_id>:<tx_hash>:<log_index>`
- TRON native TRX: `tron:<tx_hash>:internal:<internal_index>` / `:contract:0`
- UTXO (phase 12, if built): `btc:<txid>:vout:<n>` — a different model, not forced into this one

Unique constraint on `(network_id, event_reference)`. An event index is never
invented: if a listing endpoint omits it, the adapter fetches the receipt. If the
receipt cannot supply it, the record is stored with
`ordering_ambiguous = true`, not with a guessed index.

---
## D006 — Four independent status axes
**2026-09-19. Accepted.**

`execution_status`, `coverage_status`, `attribution_status`, `case_flow_linkage`.
Collapsing these into one "confidence" number is the failure mode this whole
project exists to avoid. Evidence categories are not calibrated probabilities and
are never rendered as percentages.

---
## D007 — Fixture provider implements the same adapter interface as live
**2026-09-19. Accepted.**

`ChainAdapter` is an ABC. The fixture provider is a real implementation reading
JSON captures — not a set of hardcoded trace results. If tracing can be satisfied
by returning a canned answer object, the engine is untested. Rejected alternative:
monkeypatching the engine in tests.

---
## D008 — Sessions: signed cookies + Argon2id
**2026-09-19. Accepted.**

`itsdangerous`-signed session cookies (via Starlette's `SessionMiddleware`) and
`argon2-cffi` for password hashing, both maintained. No home-grown cryptography,
no bearer tokens in localStorage for the browser path. Machine-to-machine API
keys arrive in phase 11 with their own decision entry.

Authorization is a deny-by-default FastAPI dependency that resolves
`(user, organization, case)` server-side on every route. UI hiding is not
authorization.

---
## D009 — Data mode is carried in the response envelope, not the docs
**2026-09-19. Accepted.**

`LIVE`, `RECORDED_PUBLIC`, `SYNTHETIC`. Every API response carries `data_mode`.
The fixture adapter refuses to run when mode is `LIVE`; the live adapter refuses
to run when mode is `SYNTHETIC`. Offline replay records its capture time and can
never present itself as live.

---
## D010 — Tracing state, not visited-address set
**2026-09-19. Accepted. (Contract only; engine is phase 05.)**

The engine walks `TraceState` objects carrying `(network, asset, address,
arrival_event, chronological position, branch path, scope)`. A single global
visited-address set, or a lifetime shortest path, would discard later valid
receipts and is explicitly rejected. Later receipts cannot explain earlier
outgoing transfers; same-block ordering is resolved from receipt evidence or
flagged ambiguous.

---
## D011 — The five-stage plan replaces the 20-phase playbook
**2026-09-20. Accepted. Supersedes the build order only.**

`docs/FIVE_STAGE_PLAN.md` is the build order. `docs/BUILD_PLAYBOOK.md` stays as a
correctness and production reference.

What changed in practice: the tracing engine moves from phase 05 to stage 1,
because the first deliverable is now one real end-to-end transfer path rather
than a complete foundation. The queue, Redis, and enterprise auth leave the
critical path — the plan's kill list is explicit that they must not be
prioritised over a sourced attribution result.

What did not change: the data model and every invariant in D002–D010. The
plan's twelve day-one correctness tests are the same invariants stated as tests,
and five of them already had passing coverage when the plan arrived.

Work already done under the old order (contracts, skeleton, data model, auth) is
kept. It is not on the critical path, and no test was deleted to make room.

---
## D012 — SQLite is the default; PostgreSQL stays supported
**2026-09-20. Accepted. Revises D001.**

Local default is `sqlite+pysqlite:///../var/cfa.db`. PostgreSQL remains a
`CFA_DATABASE_URL` change away. Redis, `arq`, and Docker Compose are no longer
required to run or test anything.

The column types adapt per dialect rather than letting SQLite quietly win:

- `BaseUnits` — `NUMERIC(78,0)` on PostgreSQL, zero-padded decimal **string** on
  SQLite. SQLite's NUMERIC affinity returns a float, which loses precision far
  below a uint256. Consequence: never `ORDER BY` an amount column on a mixed-sign
  range; sort amounts in Python.
- `UtcDateTime` — timezone-aware UTC on both. SQLite returns naive datetimes,
  which would break every chronological comparison the tracer makes. Naive input
  is rejected outright rather than assumed to be UTC.
- `JSONColumn` — `JSONB` on PostgreSQL, `JSON` elsewhere.
- `Uuid` — native on PostgreSQL, `CHAR(32)` elsewhere.
- Enums stay `native_enum=True`; SQLAlchemy renders them as VARCHAR + CHECK on
  SQLite, so the constraint survives.

Two SQLite behaviours had to be corrected explicitly in `make_engine`:
`PRAGMA foreign_keys=ON`, without which every foreign key is decorative; and
disabling pysqlite's implicit transaction handling, without which `BEGIN` is
never emitted, SAVEPOINT does not work, and a "rolled back" test transaction
silently commits. The second was found by a test suite that passed while leaking
rows between tests.

---
## D013 — The login identifier is an account name, not an email address
**2026-09-20. Accepted.**

`LoginRequest.email` is a lightly validated string, not `EmailStr`. Strict RFC
validation rejects the reserved domains (`.test`, `.invalid`) that local demo and
test accounts should use, and this system never sends mail. The `email-validator`
dependency was removed.

---
## D014 — Validation errors are sanitized before they leave the API
**2026-09-20. Accepted.**

Pydantic's raw `exc.errors()` carries the submitted input and the original
exception object. The first is complaint data that must not be echoed back
(T-PII), the second is not JSON-serializable at all. The handler emits only
`{field, type, message}`.

---
## D015 — A shared resource sponsor is a lead about one address, never a merge
**2026-09-20. Accepted.**

TRON energy rental is a market. JustLend and comparable services delegate to
thousands of unrelated strangers, exchanges delegate energy to addresses they do
not control, and one funder can pay fees for a crowd. So a shared sponsor is
consistent with a relationship and equally consistent with two people using the
same shop.

`app/engine/resources.py` therefore produces one `SponsorLead` per
(receiver, sponsor) pair and has no clustering function at all. A lead carries
`attribution_status=candidate` and `entity_name=None`. Where the sponsor itself
has a label, it is shown as `sponsor_label` so a reviewer can see who is
delegating — it is never inherited by the receiver.

`may_promote` refuses on a shared sponsor alone, refuses on a shared sponsor
plus TRX funding or repeated sweeps (one overlap described twice), and allows
promotion only on evidence independent of the delegation — and only as far as
`inferred`. Nothing in this module can produce `supported`: that needs a source
naming the address, which a delegation record is not.

`DEFAULT_SHARED_SERVICE_FANOUT = 20` is a review threshold, not a measurement.
Nothing here has been calibrated against known sponsors, and a sponsor below the
threshold is not thereby related to anyone.

---
## D016 — Current delegation state is not a delegation history
**2026-09-20. Accepted.**

Read from the TRON documentation on 2026-09-20 rather than assumed:

- `POST /wallet/getdelegatedresourceaccountindexv2` returns `account`,
  `fromAccounts`, `toAccounts`. Address lists. No time, no amount, not even
  which resource was delegated.
- `POST /walletsolidity/getdelegatedresourcev2` returns `from`, `to`,
  `frozen_balance_for_{bandwidth,energy}`, `expire_time_for_{bandwidth,energy}`.
  The expiry fields are when the lock ends, not when the delegation began.

Neither endpoint says when a relationship started, and neither reports one that
has already ended. Consequences, enforced in code:

- `DelegationObservation` with `basis=current_state` refuses to carry an
  operation hash, kind or time. `basis=historical_operation` requires both a
  transaction and its block time.
- `delegation_timing` returns `status="unknown"` for anything state-derived.
  `active_at` answers only for the moment observed or later; asking about an
  earlier moment returns `None`, not `False`.
- `expire_time = 0` parses to `None` — no lock, not an epoch-zero delegation.
- An empty current-state response leaves coverage `unknown` and emits
  `delegation_history_not_queried`. Absence of an active delegation now is not
  absence of one earlier, and `establishes_absence` says so.

---
## D017 — Three label sets, three files, and an importer that never accepts
**2026-09-20. Accepted.**

`import_anchors` (`app/services/anchor_import.py`, `scripts/import_anchors.py`)
routes each row of a downloaded disclosure by what the document can support:

| Document | May establish | Destination |
|---|---|---|
| Proof-of-reserves file | dated control; roles `cold_reserve`/`unknown` only | `verified_anchors.csv` |
| Signed address verification | the role the service itself states | `verified_anchors.csv` |
| Aggregator collection (TagPacks) | a lead | `independent_review.csv` |
| Authorized observation | evaluation material | `independent_review.csv` |

A reserve file asserting a `deposit` or `hot_wallet` role is rejected with
`role_not_supported_by_source` rather than imported with a caveat: a reserve
disclosure says the service controlled an address, not that a customer deposits
there.

Every row lands `review_state=unreviewed` whatever the source, so nothing an
importer writes can terminate a trace until a human opens the source and accepts
it. The original file is copied to `data/sources/<hash16>-<name>` with a
manifest row, and corroboration counts distinct upstream sources, not documents:
two aggregators repeating one disclosure are one source.

A missing URL, disclosure date, methodology, or (for an aggregator) reuse terms
and upstream source refuses the whole document before anything is written.

---
## D018 — Review is the only step that can accept a claim
**2026-09-20. Accepted. Extends D017.**

`import_anchors` writes every row `unreviewed`, so the label sets arrive inert.
`app/services/candidate_review.py` is where that changes, and it changes only on
a decision that can show its work:

- A decision needs a named reviewer and a rationale. Both are refused when
  blank, because "accepted" with nobody behind it is worse than unreviewed.
- An acceptance must name the row's own source in `evidence_inspected` — its
  URL, hash, or preserved filename. This is Stage 2's gate stated as code: the
  team can open the exact source behind each anchor, so a decision that cannot
  name one does not get made.
- The preserved copy is re-hashed at decision time. A file that changed since
  import is not the file anyone read, and acceptance is refused with
  `source_changed` rather than trusting the recorded hash.
- A `deposit_candidate` never becomes an anchor by review, whatever the
  corroboration. Sweeping, a shared sponsor and a repeated rule are one
  observation restated; an anchor needs a document naming the address, which is
  an import. This is the plan's "prevent candidate-to-trusted promotion based
  solely on repeated sweeps, a shared sponsor, or a repeated rule".
- A lead may be promoted, but only on `INDEPENDENT_EVIDENCE_KINDS` — the same
  constant D015 applies to sponsors, because it is the same question asked about
  a different observation.
- A competing claim naming a different entity must be acknowledged. The losing
  claim becomes `conflicted` and stays in its file: resolving a conflict never
  deletes the record that lost.

Nothing deletes. A decision rewrites `review_state` in place, a promotion copies
the row into `verified_anchors.csv` and marks the original with `promoted_to`,
and every decision appends to `review_log.csv` with the state it moved from, who
decided, what they opened and why.

One correction to D017 fell out of building this: routing was checking the
document kind before the assertion type, so a `deposit_candidate` claim carried
by an aggregator or an authorized observation landed in `independent_review` and
the candidate set could never be populated. The assertion type now decides
first. `LEAD_ONLY` exists to keep an ownership claim out of the anchors, not to
keep a candidate out of the candidate set.

---
## D019 — The tracer reads the reviewed sets, and a live trace has no fallback
**2026-09-20. Accepted.**

Until now `POST /trace` and `trace_demo` loaded `data/anchors.csv` directly, so
the whole import-and-review pipeline could work perfectly while the application
ignored it. `load_labels(settings)` is now the single provider both go through.

`CFA_LABEL_SOURCE` picks the set, defaulting from the data mode: the synthetic
fixture under SYNTHETIC, the reviewed sets otherwise. `CFA_LABEL_DIR` points at
the directory. Two configurations are refused outright rather than resolved
quietly:

- LIVE with `label_source=synthetic_fixture` fails settings validation. Putting
  fictional entity names on real chain observations is the worst output this
  system can produce.
- LIVE with no accepted service claim in the reviewed sets raises
  `TraceUnavailable` naming the two commands that fix it. It does not fall back
  to `anchors.csv`.

`LabelRegistry.from_reviewed_sets` reads `verified_anchors.csv` and
`deposit_candidates.csv` only. `independent_review.csv` is never read: a lead is
material for a human, not a label for a tracer. A row a reviewer rejected or
quarantined is not loaded at all, and the count of what was dropped is reported
rather than silently absent.

Eligibility is unchanged and still enforced in `Anchor`: only an accepted,
in-date `service_control` claim terminates a branch, so unreviewed, conflicted,
expired and candidate rows cannot, and a claim on another network never matches.

Every result now carries a label snapshot — which files were read, their
SHA-256, how many rows loaded and how many were withdrawn — and every label
carries its own `source_hash`, `reviewed_by`, `reviewed_at` and a
`review_reference` into `review_log.csv`. A saved report is therefore readable
later without the CSV that produced it, which is the point: the evidence a
report shows must be the evidence the run used, not today's file.

---
## D020 — Execution and finality are two questions, and the receipt answers both separately
**2026-09-20. Accepted.**

The TRC-20 history endpoint documents no execution status, so every transfer
starts `unknown`. That was correct as a fallback and wrong as a permanent
answer. `fetch_receipt` resolves it from the documented receipt endpoints,
checked 2026-09-20:

`POST /walletsolidity/gettransactioninfobyid` is asked first, because it returns
receipts for solidified transactions only — an answer there is final. An empty
answer there means "not yet solidified", not "does not exist", so
`POST /wallet/gettransactioninfobyid` is asked next and its answer is marked
`provisional`. A successful execution in an unsolidified block is
`success` + `provisional`; nothing lets execution imply finality.

`receipt.result` is described in the endpoint's prose but not enumerated in its
published schema, so the mapping fails closed: `SUCCESS` is success, `REVERT` is
reverted, a missing field is unknown, and **any other value is failed with the
raw string preserved**. Reading an unrecognised status as success would invent a
fund-flow edge out of a contract that moved nothing — day-one test 6.

Both endpoints document that an exception can arrive as HTTP 200 carrying only
an `Error` field. `_reject_error_body` raises `provider_error` on both the GET
and POST paths, so that can never be read as an empty receipt or an empty
history.

`verify_execution` asks once per transaction, not once per event, and never
upgrades an event whose receipt failed: it keeps `unknown` and lists the event
in `unverified` with the reason.

`reconcile_event` checks the asset contract, both participants and the exact
base-unit amount against the transaction's event detail. A near miss is not a
match — two transfers in one transaction can differ only in amount, and
accepting a near miss would merge distinct events.

---
## D021 — A live validation is a bundle, and it fails rather than half-reports
**2026-09-20. Accepted.**

`scripts/validate_live.py` runs one bounded trace against the real chain and
writes everything it saw to `var/live-validation/<run-id>/`: `manifest.json`,
`raw/` (every provider exchange), `normalized-transfers.json`, `receipts.json`,
`accepted-label-snapshot.json`, `trace.json` and `report.html`. The manifest
hashes every file — which establishes that the bundle has not changed since the
run, and nothing about whether the attribution is right.

Four refusals, because the failure this guards against is a validation that
reports success without having validated anything:

- Not `CFA_DATA_MODE=LIVE`, or no `CFA_TRON_API_KEY`: the run **fails**. An
  explicitly requested live validation never degrades into a fixture run and
  never reports itself as skipped-but-fine.
- A provider error fails the run. A partial bundle and a manifest saying
  `status: failed` are written; nothing is presented as clean.
- A trace that hit `provider_failure` on any branch fails the run. The tracer is
  right to record that as a boundary and carry on — a partial trace is still
  evidence — but a *validation* is a stronger claim, so `_reject_incomplete`
  refuses it.
- A replay request the recording does not hold returns an `Error` body, which
  the adapter classifies as a provider error. "We have no recording of this" and
  "the chain had nothing" are different facts, and a replay that invents silence
  is not a replay.

Replay reads `raw/` back through the same adapter, parser, tracer and report;
only the transport differs, so the analysis path under test is the real one. The
exchange key covers method, path, query and body, so a paginated sequence
replays in the order the live run made it.

No secret reaches the bundle: headers are never recorded, and the manifest
states only `tron_api_key_configured: true`.

The seed event is an input to the trace rather than something the walk
discovered, so it is not in `observed_transfers` — and in a direct A → anchor
case it is the only transfer there is. The harness asks the adapter to read the
transaction back out of the event reference and verifies that receipt too.

C06 (`test_c06_trongrid_answers_the_documented_shape`) is marked `live` and
skips without a key. It is a contract test that the documented fields still
arrive; it is deliberately not the Stage 1 gate. The gate is a bundle a person
has opened and compared against a public explorer.

---
## D022 — A selection records the publication it was cut from
**2026-09-20. Accepted. Extends D017.**

A bulk disclosure cannot be handed to `import_anchors`: the OKX proof-of-reserves
release is a 38 MB archive holding a 74 MB CSV, and the importer needs a small
tabular file. So a human selects the rows and imports the selection — which
means the `source_hash` recorded against the claim was the hash of a derived
file the publisher never issued. The link back to the real document existed only
as a sentence in the methodology.

`SourceDocument` now takes `original_file`, `original_member` and
`original_row_locator`, and four columns carry them: `original_reference`,
`original_hash`, `original_member`, `original_row_locator`. Both hashes are
kept. The selection's hash still describes the file in `sources/`; the archive's
hash describes the publication. Neither is overwritten with the other, because a
hash that does not match the file beside it is worse than no hash.

The archive is not copied into `sources/`. It is preserved where it is, the row
records where that is, and review re-hashes it there. Paths are stored relative
to the data directory's parent when possible.

Linkage is all-or-nothing. A member or locator without the file is refused at
import (`original_source_unlinked`), a named file that is absent is refused
(`original_source_not_found`), and at review time a row whose linkage is partial,
whose archive has moved, or whose archive no longer matches its recorded hash
cannot be accepted (`original_source_unlinked`, `original_source_missing`,
`original_source_changed`). Acceptance needs the original, not only the
selection cut from it.

Re-importing the same claim from the same document updates the provenance
columns in place instead of appending a second row, and never touches a review
decision: an importer does not un-review anything.

The linkage reaches `LabelEvidence`, so a saved report names the publication,
the member inside it, the row the claim came from and that publication's hash —
not only the selection.

---
## D023 — Stage 3A: a read-only service-outcome layer and an uncalibrated strong-inference policy v1
**2026-09-20. Accepted.**

Two new modules (`api/app/services/service_outcome.py`,
`api/app/services/strong_inference_policy.py`), read-only, over evidence this
codebase already collects.

**What the outcome layer infers.** For one traced claim/branch, it classifies
into exactly four categories — `supported_destination`, `strong_inference`,
`candidate_lead`, `unknown_or_blocked` — as a DISPLAY/DERIVED layer. It never
replaces or collapses the eight existing status axes (`execution_status`,
`coverage_status`, `attribution_status`, `case_flow_linkage`,
`acquisition_completeness`, `verification_quality`, `event_identity_quality`,
`ordering_quality`); every output record copies all eight through verbatim.
Outcomes are scoped per claim: resolving one branch never implies anything
about a sibling branch, and naming a path's terminal receiving service never
asserts ownership of an intermediate hop on that same path — those are
separate claims, and the intermediate hop's ownership/address_role stays
unknown unless a separate claim independently establishes it.

**What the strong-inference policy v1 infers, precisely.** That the evidence,
taken together, supports naming an *operational/receiving relationship for
this specific path window* — nothing more. It explicitly does NOT infer
ownership of the subject address, a customer-deposit relationship, or
continuous control beyond the evidenced window. `POLICY_VERSION =
"v1-uncalibrated-2026-09-20"`. This is engineering judgment encoded as an
explicit, testable, versioned gate — not a trained or validated classifier,
and not a substitute for Stage 3's later Isolation Forest scoring and
held-out precision/coverage evaluation, which remain separate, not-yet-started
work.

**The independent-evidence requirement, and why.** Promotion to
`strong_inference` requires at least one item of reviewed, address-specific
linkage evidence independent of whatever behavioral pattern surfaced the
candidate, plus a second such item from a *distinct upstream source*. Two
traps this is written specifically to avoid:

1. *One upstream source counted twice.* Two evidence items (e.g. two
   forwarding addresses that share one TRX funder, or a resource sponsor and
   a funder that are themselves the same operator) that trace back to one
   common upstream source are counted as one source, not two independent
   ones. The policy de-duplicates by `upstream_source_id` before counting.
2. *Current-state delegation is not historical.* Resource delegation observed
   as a current state cannot retroactively establish that the same
   delegation existed at an earlier claimed time; the policy refuses to
   promote a claim that asks it to backdate current-state evidence.

Repeated sweeps/forwarding alone, a shared resource sponsor alone, TRX
funding from a common funder alone, and high fan-out/volume alone —
regardless of magnitude — never qualify as the required independent
evidence, no matter how many such features are counted.

**What this does not do.** No ML training, no trained classifier, no scoring
model, no dashboard, no monitoring, no live network call. The policy computes
a label only; it never writes to `review_log.csv`, `deposit_candidates.csv`,
or `verified_anchors.csv`, and never auto-promotes or auto-reviews a real
candidate. It never reads `data/evaluation_wallets.csv` (confounder-analysis
data stays isolated from attribution, per D0xx/`evaluation_wallets.py`'s
existing isolation — a grep for that file's name over the new policy module
turns up nothing, matching `test_feature_dataset.py`'s sibling isolation
test). Where the existing schema could not express an independent-evidence
input, the smallest possible new read-only dataclass
(`IndependentEvidenceItem`) was added, and it is exercised only via fixtures
whose ids are prefixed `SYNTHETIC` in tests — never presented as real
acquired evidence.

**Demonstration.** Run against the one real accepted anchor + deposit
candidate on file (`TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq` →
`TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir`, OKX), the outcome layer honestly reports
`supported_destination` for the claim "this path's terminal receiving service
is OKX" — the anchor label is accepted, in-date (a single dated instant), on
the right network, and the seed transfer's execution was independently
receipt-verified — while explicitly noting the candidate's own
`review_state=unreviewed` and `address_role=unknown` are untouched by that
conclusion. `strong_inference` was not exercised on real data because no
second independent, reviewed, address-specific linkage source exists in this
repository's saved evidence for this candidate; it is exercised only via
SYNTHETIC fixtures in `test_service_outcome.py`.

## D024 — Stage 3B: evaluation-corpus categories are not labels, upstream
## sources are deduplicated before counting, and "not ready" is reported
## honestly instead of picking an arbitrary sufficient-N

Dated 2026-09-20.

Stage 3B needed three policy calls before any code:

**1. `evaluation_wallets.py`'s categories (`self_custody`,
`frequent_exchange_customer`, `payment_service`, `energy_rental_recipient`,
`other_operational_confounder`) describe independently established
operational context, never "innocent"/"fraud"/"negative"/model-target
labels.** A record only exists because a human found and cited an
independent source for it — never because a behavioral or resource feature
pattern looked a certain way. This is why `evaluation_dataset.py` (the new
materialization module) is grep-tested to never import
`service_outcome.py` or `strong_inference_policy.py`, and why
`evaluation_wallets.py` itself is grep-tested to never import them or
`evidence_comparison.py`. A model trained later on this corpus (Stage 3C)
would otherwise have a route to quietly treat "we don't have a fraud label
for this wallet" as "this wallet is not fraud" — exactly the trap D0xx
already named for the original, empty `evaluation_wallets.csv`, now
extended into the materialization and CLI layers Stage 3B adds.

**2. Upstream-source deduplication matters because evidence-counting must
not be gameable by republication.** Two news articles, or two disclosure
documents, quoting the same original disclosure are one source, not two —
counting them as two would let a single well-publicized fact inflate an
"independent source count" without any new independent fact existing. The
new `upstream_source_id` column and `dedupe_by_upstream_source` do exactly
this, symmetric to the existing `INDEPENDENT_EVIDENCE_KINDS` dedup logic in
`strong_inference_policy.py` (D023) — both modules refuse to let one
upstream fact masquerade as several.

**3. "Not ready for real evaluation" is reported as an honest fact, not
softened or hardened by an invented numeric threshold.** It would have been
easy to write "readiness requires N ≥ 30 real wallets per category" and
call that a scientific standard; it is not one — this project has no basis
for such a number, and presenting one would manufacture false confidence
exactly like a fabricated accuracy percentage would. The
`ReadinessReport.status` is `NOT_READY_FOR_REAL_EVALUATION` whenever the
real corpus is empty or a named structural gap remains (currently: no
defensible related-wallet grouping data exists in this repository, so
`split_by_wallet`'s optional `group_of` parameter is never populated with a
fabricated heuristic), and the exact reason is always the real count plus
the real gap — never a pass/fail against an arbitrary bar. This mirrors why
the readiness report contains no accuracy/precision/recall/AUC/anomaly- or
fraud-detection-quality field at all: there is no model in this stage, so
there is nothing honest to put in that field.

**Demonstration.** `data/evaluation_wallets.csv` remains header-only (0
real rows) after this work, confirmed by direct inspection before and
after. The real materialization + readiness pipeline run against it
reports `NOT_READY_FOR_REAL_EVALUATION` with reasons "0 real evaluation
wallets on file" and the related-wallet-grouping gap above. The pipeline's
own correctness (ingest → materialize → readiness) is instead demonstrated
end-to-end with SYNTHETIC-tagged fixtures
(`test_evaluation_readiness.py::test_full_synthetic_pipeline_is_visibly_
tagged_and_excluded_from_real_counts`), whose output is explicitly excluded
from the report's real-evaluation coverage counts.
`data/verified_anchors.csv`, `data/deposit_candidates.csv`, and
`data/review_log.csv` were sha256-verified byte-unchanged before and after;
`data/independent_review.csv` does not exist in this repository.

---
## D025 — Stage 3B.1: sourcing bar for evaluation-corpus wallets, and a
header-migration bug found while applying it
**2026-09-21. Accepted.**

**Sourcing policy (new and durable).** For `data/evaluation_wallets.csv`,
an address only qualifies as evidence when a *first-party* source (the
entity itself, on its own domain/filing, naming that exact address as its
own) makes a *narrowly scoped* claim, with a stated retrieval date because
the source page can change or disappear later. This project explicitly
excludes, by policy, going forward:
- OFAC/sanctions-list addresses — adversarial/bad-actor examples, not
  operational confounders; using them would misrepresent this dataset's
  purpose.
- Unsourced/community-guessed explorer tags, aggregator-copied address
  lists, and "probably an exchange wallet" pattern-matching.
- Two pages citing the same one upstream origin, counted as two sources
  (`upstream_source_id` collapses these; see D024/`dedupe_by_upstream_
  source`).
- Deriving `control_category` from any on-chain behavioral shape (fan-out,
  concentration, resource sponsor, etc.) — categories are established
  independently of blockchain behavior, per D024; a behavioral observation
  may only be *noted* in `notes`, never used to pick the category.

**Real demonstration.** Two RECORDED_PUBLIC records were added via
`scripts/ingest_evaluation_wallet.py --write` after a genuinely thorough
search (SEC EDGAR, TronScan public-tag process, several named energy-rental
services' own blogs/docs, and payment-processor disclosures were checked;
most were rejected — see `docs/PROGRESS.md` for the full accept/reject
list). Both remain `review_state=unreviewed`: this agent is not an
authorized human reviewer for this project and did not self-promote either
record to `accepted`, so neither currently materializes a feature window
or counts toward `find_evaluation_wallet`'s accepted-only semantics. This
mirrors the project's existing anchor/candidate human-review pattern
(`anchor_import.py`, `candidate_review.py`) rather than adding a new
exception to it.

**Bug found and fixed.** Appending a Stage-3B-schema row (12 columns) to a
real, pre-existing Stage-2-schema file (9-column header, predating
`upstream_source_id`/`reviewer`/`data_mode`) via `append_evaluation_wallet`
wrote a row wider than the on-disk header. The very next
`load_evaluation_wallets` call then crashed (`csv.DictReader` hands the
extra trailing values back under key `None`, and `EvaluationWallet(**filled)`
rejects a non-string keyword) — a real, previously-undiscovered gap,
because no prior session had appended a new-schema row to an old-schema
file. Fixed with `_migrate_header_if_stale` in
`api/app/services/evaluation_wallets.py`: on append, an old-format header
that is a strict prefix of the current column list is rewritten in place
to the full column list; every pre-existing *data* row's bytes are left
untouched (already-loadable via `load_evaluation_wallets`'s existing
missing-column defaulting). `scripts/ingest_evaluation_wallet.py`'s
byte-preservation check was relaxed to allow exactly this one documented
header upgrade while still asserting every data row is unchanged. Two new
regression tests cover this in `api/tests/test_evaluation_wallets.py`.
Full suite: 394 passed / 1 deselected (392 baseline + 2 new), `ruff check .`
clean, `mypy app` clean (56 files).

## Stage 3B.2 — review workflow policy, split-feasibility semantics, related-wallet-grouping framing (2026-09-21)

Three decisions made while building the evaluation-wallet human-review
workflow and correcting the readiness report:

**1. Registry-vs-model split is now two separate, explicitly named
fields.** `evaluation_readiness.py`'s pre-existing `split_feasible` field
was actionable-sounding but computed from the wrong thing: registry record
count (`real_wallet_count >= 2`), not materialized rows. That let a report
claim a train/eval split was "feasible" while zero real wallet-window rows
existed to split. Fixed by adding
`registry_wallet_split_structurally_possible` (weak: ≥2 distinct registry
identities, any review state) as a clearly separate field from
`model_dataset_split_feasible` (the real question: ≥2 distinct
MATERIALIZED real wallet ids, non-empty train/eval partitions from
`split_by_wallet`, no within-wallet time leakage via
`assert_no_within_wallet_time_leakage`). `split_feasible` is kept for
backward compatibility but is now defined identically to
`model_dataset_split_feasible`, never the old registry-count meaning.
Grepped the whole repo for `split_feasible`: only `evaluation_readiness.py`
itself referenced it (no test asserted a specific value before this
change), so no other call site needed updating.

**2. Reviewer-identity-must-be-human-named policy.** The evaluation-wallet
review workflow (`api/app/services/evaluation_review.py`) refuses any
review decision whose supplied `reviewer` is blank or matches an
automation/non-human identity pattern (`is_invalid_reviewer`: whole-word,
case-insensitive match against "agent", "assistant", "claude", "ai", "bot",
"llm", "gpt", "automation", "automated", "system", "model", "anthropic",
"chatgpt", "copilot"). This is a hard policy, not a suggestion: it is the
only thing standing between "a human decided this" and "a coding agent
decided this and wrote a name that looked human-adjacent." A real name that
happens to contain one of these as a substring inside a longer word (e.g.
"Aiyana") is not flagged, because the pattern requires word boundaries.
This mirrors, but does not replace, `candidate_review.py`'s existing
reviewer-required check — the evaluation-wallet registry is a distinct file
with a distinct workflow, so a parallel, adapted check was added rather
than trying to force one destination-based reviewer function to cover a
single-file registry it wasn't designed for.

**3. Related-wallet-grouping limitation: documented limitation, not a
permanent hard blocker.** The pre-existing `unresolved_blockers` list
(Stage 3B) already unconditionally names the lack of related-wallet
grouping data as a gap and keeps `status` at `NOT_READY_FOR_REAL_
EVALUATION` regardless of any other field. That is a real, current effect
— but nothing in Stage 3A/3B's design commits to it being *permanent*: no
document states that this project can never accept a `READY` status until
related-wallet grouping data exists, and `split_by_wallet`'s `group_of`
parameter was already built specifically so this could be supplied later
without a redesign. Framed here as an explicit new field,
`related_wallet_grouping_is_hard_blocker = False`, with the stated meaning:
today it functions as a blocker only because `status` has no other value
implemented yet, not because of a stated policy that it always must. An
operator with knowledge of the real registry's actual relatedness (e.g.
confirming TronBid.com's marketplace address and any other wallets it
controls are or aren't meaningfully "the same actor" for split purposes)
should make the explicit call later, and this field exists so that decision
is visible and overridable rather than buried in an unconditional list.
This is presented as the current honest choice, not as a claim that no
other framing was possible.

## 2026-09-21 — Stage 3B.3: evaluation-wallet capture as a distinct subject_kind

**Problem.** A proposed (never executed) LIVE
`collect_behavioral_evidence.py` command for
`TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM` -- the accepted
`other_operational_confounder` evaluation-wallet record sourced to
TronBid.com's own blog -- would have been refused by the existing
collector. `collect_behavioral_evidence()`'s `_require_known_candidate`
check only ever looks the address up in `deposit_candidates.csv` /
`verified_anchors.csv` (via `LabelRegistry.from_reviewed_sets`). The TronBid
address is legitimately neither a fraud-tracing deposit candidate nor a
verified anchor -- it is an independently-sourced operational confounder --
so the refusal was correct, not a bug to patch around by adding it to
either registry (that would misrepresent an operational confounder as a
fraud-tracing subject and would corrupt the meaning of both files).

**Decision.** Added a `subject_kind: Literal["candidate_or_anchor",
"evaluation_wallet"]` field to `BehavioralEvidenceRequest` (default
`"candidate_or_anchor"`, so every existing caller is unaffected). When
`subject_kind="evaluation_wallet"`, `collect_behavioral_evidence()`
validates the address via `find_evaluation_wallet(..., review_state=
"accepted")` against `data/evaluation_wallets.csv` instead of the
candidate/anchor registries, and:

- refuses any non-accepted (unreviewed/rejected/quarantined), missing, or
  wrong-network evaluation-wallet record with the same loud-refusal
  discipline as the candidate/anchor path;
- is always bundle-only: `write=True` is refused outright for this subject
  kind, because an evaluation wallet must never become a row in
  `data/behavioral_evidence.csv` (that file's schema and downstream
  consumers assume a candidate/anchor subject);
- never writes `deposit_candidates.csv`, `verified_anchors.csv`,
  `review_log.csv`, or `evaluation_review_log.csv` -- capturing behavioral
  evidence for an evaluation wallet does not promote, demote, or re-review
  it;
- stamps `subject_kind` and a snapshot of the admitting
  `evaluation_wallets.csv` row (category, source_reference,
  upstream_source_id, review_state, reviewer, data_mode) into the run's
  `manifest.json`, so any saved bundle is self-auditing about which kind of
  subject it captured and on what registry basis it was admitted.

A thin wrapper, `collect_behavioral_evidence_for_evaluation_wallet()`, is
also provided so a caller does not need to hand-construct a request with
`subject_kind` and `write=False` set correctly every time.

**Why this is safe.** The registry snapshot is audit metadata on the raw
run bundle only -- it is never fed into `app.services.evaluation_dataset`'s
materialized model features (`compute_behavioral_features_from_run` and
`build_wallet_window_row` already exclude review state, source identity,
and raw address from any feature name, enforced by
`feature_dataset.DISALLOWED_FEATURE_NAME_FRAGMENTS`, unchanged by this
work). The evaluation-wallet path and the candidate/anchor path remain
fully independent code paths sharing only the TronGrid-walking internals
(`_collect_direction`, `_is_fund_flow_event`) -- neither path can silently
widen the other's validation.

**Not done in this pass.** No live TronGrid call was made or attempted, no
model was trained, the TronBid address was not added to
`verified_anchors.csv` or `deposit_candidates.csv`, its `accepted`
evaluation category was not changed, and the quarantined
`TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT` treasury record was not unquarantined.

## 2026-09-21 — Stage 3B.3 CLI wiring: `--subject-kind`/`--evaluation-registry`

`scripts/collect_behavioral_evidence.py` previously only ever built a
`BehavioralEvidenceRequest` with the default `subject_kind=
"candidate_or_anchor"` -- the already-implemented service-layer
`"evaluation_wallet"` path (see the entry above) had no CLI entry point.
Two small, durable choices made wiring it in:

- **Flag naming**: `--subject-kind {candidate_or_anchor,evaluation_wallet}`
  (argparse `choices=`, default `candidate_or_anchor`) mirrors the service's
  own `SubjectKind` literal exactly, so the CLI value and the dataclass
  field never drift; `--evaluation-registry PATH` mirrors `--registry`'s
  naming in `scripts/materialize_evaluation_dataset.py` and
  `scripts/evaluation_readiness_report.py` rather than inventing a new term.
- **`--evaluation-registry` default**: `data/evaluation_wallets.csv`,
  matching those same two scripts' own `DEFAULT_REGISTRY` convention
  exactly (same path, same "resolved from `REPO_ROOT`" pattern) -- an
  operator who already knows those two scripts' registry flag gets the
  same default here for free.
- **`--write` refusal is CLI-level, not just service-level**: the CLI
  checks `args.subject_kind == "evaluation_wallet" and args.write` and
  refuses with a clear message *before* constructing the request or
  calling the service at all -- consistent with how this script already
  turns `BehavioralEvidenceError` into a clear stderr message rather than
  a stack trace for the existing candidate/anchor path. The service's own
  `write=True` refusal for this subject kind (already implemented) is left
  untouched and unweakened; the CLI check is an added, redundant, and
  strictly earlier guard, not a replacement for it.
- **Registry path plumbing**: `collect_behavioral_evidence_for_evaluation_wallet`
  takes `data_dir` (from which it reads `data_dir/"evaluation_wallets.csv"`),
  not a direct registry file path. The CLI resolves this by passing
  `args.evaluation_registry.parent` as that `data_dir` for the
  evaluation-wallet call only -- `--data-dir` (used for the
  candidate/anchor path's `deposit_candidates.csv`/`verified_anchors.csv`/
  `behavioral_evidence.csv`) is never read or touched in evaluation-wallet
  mode.

No live TronGrid call was made in this pass. No model was trained. Nothing
was committed. Full suite: 437 passed / 1 deselected (432 pre-existing + 5
new CLI-level tests in
`api/tests/test_collect_behavioral_evidence_cli.py`); `ruff check .` and
`mypy app` both clean (57 source files).

---

## 2026-09-21 — Stage 4 prototype: a server-rendered console over saved artifacts

**Context.** A demo-ready local GUI was needed without starting Stage 3C ML,
and without live provider access.

**Decision.** Build the investigator console as server-rendered HTML in the
existing FastAPI app (`/console`), reusing the existing trace/outcome/
comparison contracts and the saved `var/` artifacts. Do not extend the React
shell into a second application for this.

**Why not the React frontend.** The React app is a working-but-minimal
health/meta shell. Growing it into the console would require a new
authenticated JSON surface (the case routes require a session), CORS, a
separate API client for saved artifacts, and a node process at demo time —
more moving parts than the server-rendered path, each one a way for the demo
to fail on a laptop. This is not a rejection of the React frontend; it stays
and now links to the console. The invariant is "do not add a second framework,
do not add a second source of truth", not "the console must be React".

**Why no auth on `/console`.** The invariant that every case route enforce
server-side authorization is about case data. The console reads only an
allow-listed set of saved public-disclosure and synthetic artifacts; it has no
case data, no PII, and no private labels to protect. Every preset path is
resolved under the repository root and rejected otherwise, and the routes
accept no arbitrary path. A production console would sit behind the same
authorization the case routes use; that work belongs with Stage 4's real
investigator workflow, not this prototype.

**Accepted trade-offs.** The console is a presentation layer only: it derives
no attribution and invents no status. Where a saved artifact lacks a field
(for example, a Stage 3A outcome record on the synthetic trace), the page says
so instead of filling it in. Amounts stay strings. An unknown address is
reported as "no saved result", never as "no activity". The page renders the
readiness output but states that no model is trained and that the result does
not depend on one.

---

## 2026-09-21 — A saved bundle is RECORDED_PUBLIC, regardless of its capture mode

**Context.** Auto-discovery of saved bundles under `var/live-validation/` found
a bundle whose `scope.data_mode` reads `LIVE` (it was captured by a live run).

**Decision.** The console presents every saved bundle as **RECORDED_PUBLIC**.
The capture-time mode is kept as a text fact in the preset's scope note, never
as a badge.

**Why.** The data-mode invariant says recorded data must never masquerade as a
live connection. A badge describes what the viewer is looking at *now*; a file
re-read from disk is a recording. A LIVE badge on a saved file would be false
at the moment it is displayed, even though the run that wrote it was live. A
regression test (`test_saved_bundle_is_normalized_to_recorded_public`) pins
this: a discovered preset built from a trace with `data_mode="LIVE"` must come
out as `RECORDED_PUBLIC` with `LIVE` present only in its scope note.

---

## 2026-09-21 — The trace result records its own seed transfer

**Context.** A run started from an explicit seed event begins its forward walk
at that event's *recipient* (hop 0). The seed transfer itself was therefore
never in `observed_transfers`, and a direct seed-to-service-boundary trace
produced a path with no transfer row at all. The console had to reconstruct the
row from the branch ending and join its time from a separate behavioral
acquisition.

**Decision.** Add `TraceResult.seed_transfer` (serialized as `seed_transfer`),
populated in `ChronologicalTracer.trace` from the supplied seed event when that
event is spendable. It is reported separately from `observed_transfers` because
it is the case link, not an onward hop. The console and the printable evidence
report render it as hop 0; a saved result that predates the field falls back to
the labelled branch-arrival reconstruction.

**Why separate and not prepended to `observed_transfers`.** Existing callers
and tests treat `observed_transfers` as "onward transfers followed from the
seed" — a direct trace has zero of them, and day-one tracer tests assert that.
Appending the seed transfer there would have changed that meaning and broken
the semantics the invariant depends on. A dedicated field keeps both facts
distinct and additive, so replay/live comparisons and the existing assertions
are unaffected.

---

## 2026-09-21 — Console UI: Shneiderman's rules, and animation that cannot overclaim

**Context.** The demo console needed a clearer, more teachable interface and a
visual explanation of how a saved result becomes an outcome.

**Decision 1 — apply Shneiderman's eight golden rules concretely.**
Consistency (one card/chip/address vocabulary, endpoint status text *and*
colour); universal usability (skip link, landmarks, `aria-live`, automatic
`prefers-color-scheme` dark theme, `prefers-reduced-motion`, responsive
layout); informative feedback (copy/step/caption live regions, hover/active/
focus); closure (the walkthrough ends on the actual result; each report ends
on its caveat); error prevention (fixed network/asset, server-side address
canonicalization, presets as safe choices); easy reversal (Replay/Step/Reset,
Esc stops motion, collapsible cards); user control (no destructive actions,
explicit Play controls); reduced memory load (step indicator, colour legend
with text labels, preset titles always visible).

**Decision 2 — animation is CSS/SVG + vanilla JS only.** No new dependency, no
external asset, deterministic and testable server-side; the JavaScript is
syntax-checked in review.

**Decision 3 — autoplay on load, except under reduced motion.** The walkthrough
autoplays by default (the demo choice), but the `prefers-reduced-motion: reduce`
query always wins and shows the completed, static state. Accessibility is not a
preference to be traded away for a nicer demo.

**Decision 4 — the animation explains the *method*, never the *case*.**
The walkthrough is generic; only its final step is filled from the selected
saved result. It never implies a live chain call, never collapses the eight
status axes, and never uses confidence/probability language. A test asserts the
page contains no `accuracy`/`auc`/`AI-powered` strings and no external
`<script src>`.

---

## 2026-09-21 — Three-page site, and "missing artifact" is only a warning when expected

**Context.** The console showed two yellow warnings on the synthetic preset:
"No Stage 3A service-outcome record is saved…" and "No Stage 2 comparison
report is saved…". A synthetic, trace-only fixture has neither by design, so the
warnings were noise, not a defect to fix by fabricating artifacts.

**Decision 1 — warn on declared-but-missing, not on not-applicable.**
`load_preset` now emits a warning only when a preset names an artifact path and
the file is absent. A preset that never declares a Stage 3A outcome or Stage 2
comparison gets a neutral note in the report panel ("this saved result has no …
That is expected for a trace-only or synthetic fixture"), and the corresponding
report button is omitted. This keeps a genuinely missing configured artifact
loud while removing a false alarm.

**Decision 2 — do not derive a Stage 3A outcome for a trace-only preset.**
It was tempting to run `classify_service_outcome` over the trace's branch
endings so every preset shows a category. That would silently apply the
stricter service-outcome verification gate (which requires receipt-verified
execution for `supported_destination`) to a trace whose own
`attribution_status` means something different, producing a confusing
downgrade or an overclaim. The honest presentation is the trace's own branch
endings, labelled as such; a saved Stage 3A record is required to show a
service-outcome category.

**Decision 3 — three pages, one shell.** Overview (`/`), Demo (`/console`), and
Dashboard (`/dashboard`) share one page shell, nav, stylesheet, and animation
script. The dashboard aggregates saved runs from `summarize_presets()` and
reports a category only when one is saved. All three read-only routes are
registered only outside `prod`, like the console.

---

## 2026-09-21 — Incomplete features are shown as status, never filled in

**Context.** ML/evaluation and several operational features (monitoring,
connectors, multi-chain) remain incomplete. The risk is implying capability the
repository does not have — a claimed model, a fabricated metric, or a
"dashboard" that suggests monitoring exists.

**Decision 1 — a derived capability matrix, not a roadmap.** The dashboard's
*Capabilities and status* card is built by
`app.services.operational_status.build_capabilities` from the saved readiness
report and the live settings. The anomaly ranker and held-out evaluation are
`blocked` (no model, corpus not ready); monitoring and multi-chain are
`not_built`; government connectors are `not_configured`; live acquisition is
`available` only when a key and LIVE mode are both configured. It never emits
an accuracy, precision, recall, or AUC figure, because none exists.

**Decision 2 — a real operational capability: bundle integrity.** The
dashboard re-hashes each file a saved bundle's manifest lists and reports
ok / mismatch / missing (`verify_manifest_hashes`). This is a genuine Stage-4
usefulness feature that needs no chain access, and it repeats the manifest's
own caveat: a hash match shows the files are unchanged since the run, not that
the attribution is correct or legally admissible.

**Decision 3 — no model is trained to "complete" Stage 3C.** The corpus has
real wallets but no accepted-and-materialized windows, so training an Isolation
Forest now would produce an uncalibrated score with no held-out evaluation —
exactly what the acceptance catalog forbids. The honest completion is the
explicit `blocked` status and the standing readiness report.

---

## 2026-09-21 — Stage 3C: a synthetic-only Isolation Forest, fitted but not "validated"

**Context.** Stage 3C is "implement extract_features, train_anomaly,
evaluate_anomaly" with a gate that "the model actually fits and scores saved
data, the module has a held-out comparison, and disabling it does not change
observed transfer evidence or service labels." The corpus still has no
accepted-and-materialized windows (the one accepted record, the TronBid
marketplace confounder, has no saved run bundle), so a *real* train/holdout
comparison is impossible. The risk is either (a) shipping nothing, or (b)
shipping a model that quietly implies validation it does not have.

**Decision 1 — add scikit-learn, and say why.** `scikit-learn` 1.9.1 (with
`numpy`/`scipy`) is now a dependency of `api/`. Hand-rolling an Isolation
Forest would have kept the dependency set small but introduced bespoke code
whose correctness is exactly the thing under test. The plan's own reference
is scikit-learn's `IsolationForest`; using the maintained implementation is
the lower-risk choice. The full dependency set is recorded in `uv.lock`.

**Decision 2 — a fixed, versioned, numeric-only feature allowlist.**
`app.services.anomaly_ranking.ANOMALY_FEATURES` is a curated list of 19
numeric behavioral features (transfer/counterparty counts, outgoing
concentration, repeat/forwarding counts, receipt-to-outflow timing summaries,
residue, missing-index counts). It excludes every string provenance/quality
feature, window timestamps, booleans, and any address, case id, complaint/
outcome field, or service name; the allowlist is re-checked against
`feature_dataset.DISALLOWED_FEATURE_NAME_FRAGMENTS` at run time. Resource
features are deliberately *not* merged in for v1: current-state and historical
resource evidence are separate families by project invariant, and combining
them into one model is the merge the invariants forbid.
`receipt_to_outflow_timing_seconds` is excluded because it collapses to a
last-wins value in the row dict rather than a well-defined summary; the
min/median/count summaries are used instead.

**Decision 3 — missing is imputed at the TRAIN median, and shown.** A missing
feature is filled with the median of that feature's non-missing training
values (0.0 only if a feature is entirely missing in train), so an imputed
cell sits at the *typical* value and is never scored as suspicious. Every
`AnomalyScore` lists which features it imputed, and every score carries the
raw observed values next to the score so an analyst sees *what was observed*,
not a claimed model explanation.

**Decision 4 — no metric, and no real model, until the corpus is ready.**
`train_anomaly` records seed, `model_version`, `anomaly_feature_version`,
`feature_definition_version`, sample-selection method, training cutoff, and
the exact training row keys — everything needed to reproduce it — but reports
no accuracy/precision/recall/AUC. `scripts/anomaly_ranking.py` runs on a
deterministic SYNTHETIC set only and labels its output
`"evaluation_kind": "pipeline_demonstration"`, `"real_data_used": false`.
Held-out precision/coverage evaluation, and any training on real accepted
windows, remain Stage 3C evaluation (Order 3) and require the Order 1 human
review to complete first. The capability matrix keeps the ranker `blocked`.

**Decision 5 — the ranker cannot touch the evidence path.** `anomaly_ranking`
imports nothing from the tracing/evidence/outcome modules, and none of those
import it; grep tests assert both directions. Disabling the ranker therefore
cannot change observed transfer evidence or service labels, which is the
gate's second clause.

---

## 2026-09-21 — Stage 3C evaluation: a predeclared rubric, nulls not zeros, and a confounder check

**Context.** The plan asks for "review-worthy precision@k under a predeclared
analyst rubric against a random-ranking baseline and known operational
confounders." But this repository's only independent label vocabulary —
`evaluation_wallets.CONTROL_CATEGORIES` — is entirely *confounder* categories
(self-custody, frequent exchange customer, payment service, energy-rental
recipient, other operational confounder). There is no review-worthy
("positive") class in the corpus at all. A metric that quietly treated the
absence of a positive class as a zero, or that treated an unevaluated wallet
as clean, would be dishonest.

**Decision 1 — the rubric is explicit and predeclared, never inferred.**
`AnalystRubric` names three disjoint sets: review-worthy categories, known
confounder categories, and independently-established negatives. A row whose
`control_category` is `None` or outside the rubric is EXCLUDED from every
ratio and counted (`unlabeled_excluded`, `outside_rubric_excluded`); it is
never counted as a negative. `evaluate_anomaly` refuses to run on rows the
model was trained on (`assert_no_training_overlap`).

**Decision 2 — a null is reported as null.** When the evaluation split
contains zero review-worthy rows, `review_worthy_precision_at_k` and its
random-ranking baseline are `null` (not computable), with a stated reason —
never a fabricated `0.0`. The baseline itself is the exact expected precision
of a uniformly random ranking (the positive base rate), so no sampling
randomness is introduced.

**Decision 3 — confounders are surfaced, not hidden.** The evaluation records
the rank of every known operational confounder in the split
(`confounder_ranks`, `confounders_in_top_k`, `confounder_fraction_at_k` vs
`confounder_base_rate`). A ranker that over-ranks legitimate patterns should
show it, not bury it. The report repeats that a high-ranked confounder is a
false positive to inspect, not a finding.

**Decision 4 — the report is review-prioritization only, and separate.**
`app.reports.anomaly_evaluation.render_anomaly_evaluation_html` renders the
evaluation on its own page; it carries no attribution evidence, states that it
does not measure criminal guilt, ownership, service identity, or fraud, and
emits no accuracy/recall/AUC. It is labelled `pipeline_demonstration` whenever
every evaluation row is SYNTHETIC, and `held_out_evaluation` only otherwise.

**Decision 5 (Order 4) — the console shows the ranker as a separate, partial
capability, never as evidence.** The dashboard and console sidebar gained a
*ML review-prioritization (experimental)* card that renders the saved Stage 3C
report (read from the allow-listed `var/anomaly-evaluation/report.json`; the
request path never fits or scores anything). The card is visually and
conceptually apart from the trace/evidence cards, is badged
**SYNTHETIC DEMONSTRATION** whenever the report is a pipeline demonstration,
shows a null precision as *not computable*, lists the confounder ranks, and
repeats that it changes nothing about the attribution result. The capability
matrix now marks `ml_anomaly_ranking` and `held_out_evaluation` as
**partial** — code exists, synthetic-only, no real model — rather than
`blocked`. `partial` never means "validated".

**Decision 6 — the demonstration result is reported as-is.** On the synthetic
set the ranker ranks the marketplace-like confounder top and does not surface
the burst-and-forward "review-worthy" shape within top-5
(`review_worthy_precision_at_k: 0.0` vs a `0.2` baseline). That is an honest,
unflattering result from a toy ranker, and it is left visible rather than
tuned away — tuning synthetic data until the demo looks good would be exactly
the fabricated validation the plan forbids. Real evaluation waits on Order 1
(human review of the evaluation corpus).

## 2026-09-21 — The analysis window is a validated, human-supplied input

**Choosing a window is human work, not code's.** A capture reports truncation
and completeness *against* an explicitly declared window, so an inferred
window would make those statuses unfalsifiable. `app/services/
evaluation_window.py` therefore only parses, validates, and canonicalizes
`WINDOW_START`/`WINDOW_CUTOFF`; it never anchors to "today", reuses another
wallet's window, reads chain activity to pick a range, or optimizes after
seeing outcomes.

**Datetime convention (decided after inspecting the existing one).** The
collector CLI's `parse_time` accepts explicit offsets and silently reads a
naive timestamp as UTC. This validator is deliberately stricter: a naive
timestamp is refused, while an explicit non-UTC offset is normalized to UTC
*while preserving the exact instant*. Normalizing an offset cannot widen,
shrink, or move a window — the canonical UTC printed by the validator is what
the caller passes on to the collector, via a small `--canonical-out` file, so
no second parse can drift the bounds. A zero-length or reversed window is
refused.

**Provenance, not proof.** The capture manifest gains a `window_selection`
block (`requested_window_start`, `requested_window_cutoff`,
`requested_window_duration_seconds`, `evaluation_window_rationale`,
`evaluation_window_policy`, `window_selected_by: "human_supplied"`, plus a
pseudonymous `wallet_id` and the `capture_run_id`). These fields are
descriptive: the block states that the requested window does not imply
complete observation, and the collector's existing `truncated_by_*` fields
remain authoritative. This reuses `feature_dataset.wallet_id` and adds no new
relatedness/grouping heuristic, so the existing
`assert_no_within_wallet_time_leakage` remains the single leak-check.

**Reruns are reported, not adjudicated.** If a preferred bundle already exists
for the wallet, the validator reports whether the new request is identical,
overlapping, or distinct. Overlap is never auto-rejected and a distinct
capture is never blocked; the collector's existing
`allow_overwrite_existing_run=False` default still refuses to silently replace
a saved bundle.

## 2026-09-21 — One canonical layout for evaluation-wallet evidence bundles

**The contract:**
`<evidence_root>/<network>/<address>/<run_id>/{manifest.json,evidence.json}`.
`<evidence_root>` is the `by-wallet` directory. A wallet directory and a
capture run id are separate concepts: the address is never the run id, and
each capture gets its own `run_id` child so distinct/overlapping windows for
one wallet coexist and no earlier capture is overwritten.

**Why this changed.** Stage 4 was writing to `<out_dir>/<run_id>` while
Stage 5, `domain_eligibility_for_wallet`, and the readiness report searched
`<evidence_root>/<network>/<address>/`. A successful capture was therefore
invisible to materialization. The earlier `run_id=<address>` comment was also
incompatible with the project's support for multiple windows per wallet.

**One contract, not two.** Rather than let each script rebuild the path, the
writer and every reader share small helpers in
`app.services.collect_behavioral_evidence`:
`evaluation_wallet_evidence_dir`, `evaluation_capture_dir`, `run_dirs_in`,
and `wallet_run_dirs`. They reject empty/`.`/`..`/separator/NUL path
segments. The CLI resolves `--out-dir` for evaluation-wallet mode to the
evidence root (default `<var>/collect-behavioral-evidence/by-wallet`), and
still emits a human `bundle` line plus a stable machine-readable
`bundle_path=` line so the wizard never reconstructs the path.

**Materialization sees every window.** `materialize_evaluation_dataset`
discovers all readable run children and builds one row per run, which matches
the existing per-window row semantics in
`app.services.feature_dataset` ("the same address observed in two different
windows is two distinct rows"). A missing wallet directory is still
`missing_evidence`; an unreadable run is skipped by name rather than silently
dropping the wallet. No grouping heuristic was added, and
`assert_no_within_wallet_time_leakage` remains the single leak check.

## 2026-09-21 — Evaluation units: wallets, windows, sources, and groups

Three axes of independence, kept visible and separate:

- **Wallet is the primary independence unit.** `materialize_evaluation_dataset`
  produces one `WalletWindowRow` per saved window, so
  `materialized_window_count_real` counts WINDOWS. The readiness report now
  also reports `materialized_distinct_wallet_count_real`,
  `materialized_windows_per_wallet`, and concentration diagnostics
  (`wallets_with_multiple_materialized_windows`,
  `maximum_windows_from_one_wallet`,
  `most_represented_wallet_window_fraction`, per-wallet rows). N windows is
  never presented as N wallets.
- **Windows are repeated observations, not independent identities.** They stay
  useful for longitudinal/temporal work, but a window is not a subject.
- **Upstream-source independence is a separate axis.**
  `dedupe_by_upstream_source` is unchanged: five windows from one first-party
  disclosure remain one source basis, and repeated windows never inflate
  `independent_source_count_real`.

**Related-wallet groups are external input, never inferred.**
`evaluation_experiment.py` adds `ExperimentKind` (`wallet_held_out`,
`group_held_out`, `future_window`, `synthetic_pipeline_demonstration`) and
split guards. Grouping is supplied via `group_of`/`--grouping`; absent
grouping is reported as a limitation and only a wallet-level split is
offered. Relatedness is never derived from a shared funder, resource sponsor,
behavioral similarity, timing, or destination.

**Experiment kinds are not interchangeable.** `wallet_held_out` refuses any
wallet on both sides; `group_held_out` refuses any group on both sides;
`future_window` requires strictly later windows for every shared wallet (and
refuses backward temporal leakage, and refuses to run at all with no shared
wallet); SYNTHETIC rows are refused by every real kind. `evaluate_anomaly`
validates the declared kind against the model's recorded training keys and
refuses an undeclared real split that shares a wallet with training rather
than mislabelling it an independent-wallet holdout. A `future_window`
experiment is stated as such in the report and is never called a
wallet-holdout. The Stage 3C synthetic demo declares
`synthetic_pipeline_demonstration` explicitly.

**No arbitrary minimum sample size.** No threshold (30 wallets, 100 windows,
10 per category, etc.) is introduced; readiness still reports the actual
counts and named structural gaps only.

## 2026-09-21 — Evaluation-wallet capture is an auditable transaction

A provider-backed capture now runs as **preflight → staging → validation →
atomic finalize**. The by-wallet layout is unchanged
(`<evidence_root>/<network>/<address>/<run_id>/`); what changed is how a
bundle gets there.

**Staging, then rename.** Evaluation-wallet collection writes into
`<wallet_dir>/.staging-<run_id>/` and, only after every artifact is written
and `validate_evaluation_capture_bundle` passes, atomically renames the
directory to `<wallet_dir>/<run_id>/`. No file-by-file copy into the final
location. An overwrite is still refused unless the operator explicitly asks;
an existing staging directory is refused rather than reused.

**Readers never see staging.** `run_dirs_in` ignores hidden children,
`.staging-*`, rejected runs, and any directory missing manifest/evidence, so
materialization, readiness, console/status, and window-relation inspection
all treat a half-written capture as zero rows.

**Two separate concepts, not one.** Filesystem status (`run_status`: complete
| partial | failed) is distinct from acquisition completeness
(`complete_within_scope` | `truncated`, matching
`load_preferred_behavioral_run`). A bounded run that hit a configured
page/event/request limit finalizes as a valid `partial` bundle and is never a
failure; a classified provider error yields `partial` while an unhandled
failure yields `failed`.

**Failures are preserved, not deleted.** On an unhandled exception after
staging exists, the capture is moved to
`<collect-root>/rejected-runs/<network>-<address>-<run_id>-<data_mode>-<ts>-invalid/`
with a `FAILED.json` recording failure type, error classification, requests
completed, whether raw responses exist, run id, requested window, timestamp,
and data mode. No secret is recorded: `BundleRecorder` stores
method/path/params/body only, never headers, so the TronGrid key never reaches
the bundle (regression-tested).

**Minimum finalized contract (derived from readers).** manifest.json,
evidence.json, and raw/ must exist; the manifest must carry run_id,
subject_kind, network/address, window_selection bounds, a final run_status, a
valid acquisition_completeness, and (for evaluation wallets) the registry
snapshot. Validation returns a structured result rather than scattered
existence checks.

## D026 — Stage 4: the evidence export bundle is rendered from one template, and a checksum is documented as consistency, not correctness
**2026-09-22. Accepted.**

The five-stage plan's Stage 4 calls for upgrading the Stage 1 report (HTML
that prints to PDF from a browser) to a generated PDF plus a CSV/JSON package
with file-integrity hashes. `api/app/services/evidence_export.py` implements
this as `build_evidence_bundle(result, ...)`, exposed at
`POST /api/v1/traces/export` (alongside the existing `/traces` JSON and
`/traces/report` HTML routes), returning a zip of `evidence.json`,
`evidence.html`, `evidence.pdf`, `transfers.csv`, `branch_endings.csv`,
`labels.csv`, `limitations.csv`, and `manifest.json`.

**One template, not two.** The PDF is rendered from the exact HTML string
`app.reports.evidence.render_evidence_html` already produces and already has
tests for (`xhtml2pdf.pisa.CreatePDF` converts that HTML string directly) —
there is no second, PDF-specific template to drift out of sync with the
screen/HTML report. `test_evidence_export_bundle_matches_the_report_and_
verifies_its_own_hashes` in `api/tests/test_trace_endpoint.py` asserts the
bundle's `evidence.html` carries the same supported-destination label and
disclaimer text as the plain `/report` route.

**New dependency: `xhtml2pdf`.** Chosen over `weasyprint` (native
cairo/pango system dependencies, heavier to deploy) and over a headless-browser
approach (`playwright`, a much larger dependency for one report). `xhtml2pdf`
is pure-Python-installable (it pulls in `reportlab`, `lxml`, `pypdf`, `Pillow`
and `pyhanko` transitively) and was sufficient for this project's table-and-
definition-list report styling; it does not support some CSS this report's
`STYLE` block uses for the on-screen page (`box-sizing`, `border-collapse`,
`color-scheme`, `break-after`/`break-inside`, `currentColor`, and the Unicode
arrow "→" have no glyph in its default font) and logs warnings for each,
which is cosmetic degradation in the PDF layout, not a data-correctness
problem — no fact, number, or label differs between the HTML and the PDF, only
some visual polish.

**The manifest reuses this project's one existing manifest shape, on the
second attempt.** The first draft invented its own `files: [{name, sha256,
bytes}, ...]` list. Before finishing, `api/app/services/operational_status.
py`'s `verify_manifest_hashes` was checked and turned out to already expect
`files: {relative_filename: sha256_hex}` — the exact shape
`live_validation.py`, `collect_resource_evidence.py`, and
`collect_behavioral_evidence.py` all already write. Per AGENTS.md ("use
existing abstractions"), the bundle's manifest was changed to match that
mapping exactly (dropping the invented per-file byte count, which no other
manifest in this project carries) and its caveat field was renamed `note` →
`caveat` to match those same manifests' key name. This means
`verify_manifest_hashes` can check this bundle's manifest with zero
adaptation — proven directly in
`test_manifest_interoperates_with_verify_manifest_hashes`, not just asserted.
The caveat wording itself was already effectively independently reinvented
the same way those other manifests phrase it — a good sign the posture is
now a project-wide habit, not a one-off.

**Two known sources of run-to-run non-determinism, both pre-existing, neither
hidden.** `render_evidence_html` stamps a "Generated at ..." line with
`datetime.now()`, independent of any bundle-level timestamp parameter; this
was already true of the Stage 1 report and is not changed here.
`xhtml2pdf`/`reportlab` additionally embed their own PDF creation-time
metadata. Net effect: regenerating a bundle from the byte-identical trace
result does not reproduce `evidence.html`'s or `evidence.pdf`'s exact bytes
(their SHA-256 in the manifest legitimately differs each time), while
`evidence.json` and every CSV file are a pure function of the result and are
byte-identical across regenerations (`test_json_and_csv_files_are_byte_
identical_across_two_builds`). This is a real limitation of what "reproducible
bundle" means here, recorded rather than glossed over: the manifest attests to
*this specific generated bundle's* internal consistency, not that regenerating
it would produce the same file.

**What this increment does not do.** No bundle is persisted server-side
(the zip is generated per-request and streamed back; nothing under `var/` is
written by this route, unlike the offline `scripts/build_*` report builders).
No digital signature beyond a plain SHA-256 hash. No PDF/A or archival-format
compliance claim. Checkpointed new-event monitoring and the mock complaint
adapter (the other two Stage 4 sub-parts) are untouched by this change.

Full suite after this change: 642 passed / 1 deselected (628 measured
baseline on this working tree before this session's edits + 14 new: 13 in
`api/tests/test_evidence_export.py`, 1 in `api/tests/test_trace_endpoint.py`);
`ruff check .` clean; `mypy app` clean, 66 source files (this working tree's
pre-existing 65 plus the one new `evidence_export.py` — this checkout already
carried other uncommitted, pre-existing changes unrelated to this decision
when this session began, so 65 is this tree's own baseline, not a prior
session's recorded count).

## D027 — Stage 4: legal-request drafts refuse asset-restriction against a pooled or role-unknown address, structurally
**2026-09-22. Accepted.**

The five-stage plan's Stage 4 calls for "distinct information/preservation/
asset-restriction request drafts marked DRAFT / INVESTIGATOR REVIEW
REQUIRED... use a verified provider guide as a field checklist... do not
request a blanket freeze of a pooled exchange wallet." `api/app/services/
legal_requests.py` implements `build_request_draft(result, request_kind,
target_address, ...)`, exposed at `POST /api/v1/traces/legal-request-draft`
(JSON) and `POST /api/v1/traces/legal-request-draft/report` (HTML, via new
`api/app/reports/legal_request.py`).

**The field checklist is not invented.** `CHECKLIST_SOURCE` reproduces OKX's
own published law-enforcement request guide
(`https://www.okx.com/help/okx-law-enforcement-request-guide`), fetched and
read (not just linked) 2026-09-22: agency identification, a signed court
order/official letter or other documentation of authority, specific items
requested, an incident overview with investigation findings and total
amount, relevant provider account identifiers, and wallet/transaction
identifiers "in a copiable format (e.g., csv)" — the last of which points the
reader at this session's own `/traces/export` bundle rather than duplicating
its CSV inline. The guide does not itself distinguish information/
preservation/asset-restriction request types or discuss pooled wallets by
name; those distinctions and the refusal rule below are this project's own,
applied on top of the provider's real checklist, not attributed to it.

**The pooled-wallet rule is structural, not investigator-trusted.**
`build_request_draft` refuses (`status="refused"`, a normal 200 response with
a stated reason, never an exception) an `asset_restriction` draft whenever
the target's label `address_role` is `hot_wallet`, `cold_reserve`, or
`settlement` (`app.models.enums.AddressRole`'s pooled/operational roles), or
when no narrower role has been established at all (`unknown`, or no label —
an unreviewed `deposit_candidate` lead). Only `address_role=deposit` drafts
cleanly. This is deliberately grounded in this project's own real data, not a
hypothetical: **both real accepted anchors in `data/verified_anchors.csv`
today carry `address_role=unknown`**, specifically because (per each row's
own recorded methodology) an OKX proof-of-reserves signature establishes
control of a signing key at one snapshot instant, not whether the address is
cold storage, a hot wallet, or a customer deposit address. An
asset-restriction draft against either real anchor, as this codebase stands,
is refused — exactly the outcome this rule exists to produce, exercised
against real data, not only against the SYNTHETIC fixture's `address_role=
deposit` service address (`data/anchors.csv`) that the happy-path tests use.

**Refusal is a result, not an error.** `RequestDraftError` (→ HTTP 422) is
reserved for a genuine caller mistake: a blank required investigator field,
an unrecognised `request_kind`, or a `target_address` the trace never
actually reached. A pooled-wallet refusal is not one of these — it is
returned as an ordinary, fully-populated `RequestDraft` with
`status="refused"` and a `refusal_reason`, still carrying every checklist
field, the draft marker, and the target's real recorded role, so an
investigator (or a reviewer of this code) can see exactly what was asked for
and why it was declined, per this project's "never omit, always show why"
posture (same posture as `service_outcome.py`'s `unknown_or_blocked`
category, applied here to a different question).

**`investigation_findings_to_date` is auto-filled from the trace's own
recorded facts** (seed address, target address, endpoint class, attribution
status), not free text the caller supplies — one more place a claim is
sourced from something this codebase actually observed rather than typed in.

**AGENTS.md non-negotiables carried through explicitly**: every draft,
drafted or refused, carries a fixed `draft_marker` stating it is not legal
process, establishes no legal authority, has not been sent to any provider,
and was not signed or authorised by any officer. `requesting_officer` is
recorded for this project's own accountability (matching the reviewer-must-
be-named pattern from D025's `evaluation_review.py`), explicitly labelled in
its own checklist entry as *not* one of OKX's own required fields, so the two
sources of "required" are never conflated as one thing.

**What this increment does not do.** No draft is sent anywhere, ever — this
module builds text, nothing more. No signature or letterhead is generated.
No case/DB persistence of a drafted request (stateless, like `/traces/export`
before it). The mock complaint adapter (Stage 4's third sub-part, alongside
this and checkpointed monitoring) is untouched; `operational_status.py`'s
existing `government_connectors` capability row ("NCRP / SAHYOG and similar
remain MOCK / NOT CONFIGURED by policy") is unaffected by this change.

Full suite after this change: 674 passed / 1 deselected (642 baseline after
D026 + 32 new: 21 in `api/tests/test_legal_requests.py`, 6 in
`api/tests/test_legal_request_report.py`, 5 in `api/tests/test_trace_
endpoint.py`); `ruff check .` clean; `mypy app` clean, 68 source files.

## D028 — Stage 4: the mock complaint queue is one fixture file, never a real NCRP/SAHYOG connector
**2026-09-22. Accepted.**

The five-stage plan's Stage 4 closing instruction: "Provide a clearly marked
mock complaint adapter only. Do not invent NCRP/SAHYOG APIs or claim approved
connectivity." AGENTS.md is explicit in the same direction: "Government
connectors remain MOCK/NOT CONFIGURED until approved documentation,
credentials, and permission exist. Do not invent NCRP or SAHYOG production
APIs." `api/app/services/mock_complaint_adapter.py` + `api/app/routes/
mock_complaints.py` implement exactly this and nothing more.

**What it actually is.** `list_mock_complaints`/`get_mock_complaint` read
one repository file, `fixtures/mock_complaints.json` (three fictional
complaints), and nothing else -- no network call, no external portal, no
credential of any kind. Every complaint and every API response derived from
one carries a fixed `source_channel: "MOCK_LOCAL_QUEUE"`, and the loader
(`_load_fixture`) refuses to load any file that doesn't declare that exact
channel -- a small guard against this loader ever being silently pointed at
something else later. `GET /api/v1/complaints/mock` and the two per-
complaint routes require `CurrentUser` (the same authenticated dependency
every case-adjacent route in this project uses), per Stage 4's "require
appropriate authentication/authorization before exposure beyond local
public-data use."

**It creates nothing.** `mock_complaint_to_seed_draft` only *shapes* a
suggested seed payload for a human to review; it is never POSTed anywhere by
this module. It deliberately cannot resolve a real database `asset_id`
(this module has no database access), so the draft is expressed by
`token_contract` -- the same way `POST /api/v1/traces` already accepts an
asset -- leaving the actual lookup and the actual `POST /api/v1/cases/
{case_id}/seeds` call to the investigator, through the one real, already-
authenticated intake path this project has (`api/app/routes/cases.py`).
Nothing here duplicates that path or adds a second, parallel case-creation
mechanism.

**Mode is derived honestly, not defaulted to the more impressive one.** A
complaint that names a specific seed event drafts as `mode="incident"`; a
complaint with no recorded transaction drafts as `mode="address_discovery"`
and carries no amount, because `address_discovery` mode "asserts nothing
about victim funds" (PRD section 2, `docs/PRD.md`) and this module does not
invent a transaction reference just to make a complaint look more actionable
than it is.

**Demonstrated as a real, connected pipeline, not just a shape.** One fixture
complaint (`MOCK-Q-2026-000101`) intentionally names the same address, asset,
and seed event as this project's existing SYNTHETIC trace fixture
(`fixtures/tron_synthetic_case_alpha.json`), so
`test_seed_draft_from_a_mock_complaint_traces_end_to_end` actually posts that
complaint's own seed-draft output to the real `/api/v1/traces` endpoint and
gets back the real supported-destination result -- complaint -> seed draft ->
trace, exercised as one path, not asserted as three disconnected pieces.

**Small, adjacent, honest fix made while here.** `GET /api/v1/meta`'s
hardcoded `capabilities` dict (`api/app/routes/health.py`, unrelated to
`operational_status.py`'s richer capability matrix and not consuming it) had
`"evidence_export": False` -- stale since D026 shipped an actual export
route two sessions ago. Flipped to `True`, and a new `"mock_complaint_
queue": "MOCK_LOCAL_QUEUE_ONLY"` key added. `operational_status.py`'s
`build_capabilities` gained a `legal_request_drafts` row (D027) and a
`mock_complaint_queue` row, and its existing `evidence_export` and
`government_connectors` row detail text was updated to describe what those
now actually do/don't do, rather than the D026-era placeholder text.

**What this increment does not do.** No claimed/unclaimed state tracking (no
persistence at all -- converting a complaint to a real case seed does not
remove it from this list, and this is stated plainly rather than silently
absent). No PII-handling machinery of any kind -- every `reporter_contact`
in the fixture is itself fictional test data, matching this project's
existing "(FICTIONAL)" convention for synthetic entity names. No real
NCRP/SAHYOG credential, endpoint, or claimed connectivity anywhere.
Checkpointed new-event monitoring (Stage 4's remaining sub-part) is
untouched.

Full suite after this change: 692 passed / 1 deselected (674 baseline after
D027 + 18 new: 11 in `api/tests/test_mock_complaint_adapter.py`, 7 in
`api/tests/test_mock_complaints_route.py`); `ruff check .` clean; `mypy app`
clean, 70 source files.

## D029 — Stage 4: checkpointed new-event monitoring is one-shot polling with database-enforced idempotency
**2026-09-23. Accepted.**

The last Stage 4 sub-part: "Add checkpointed new-event monitoring for supported
token transfers, with deduplication, restart recovery, and measured observation
lag. Do not claim a public mempool feed." Implemented in
`api/app/services/monitoring.py`, `api/app/routes/watches.py`,
`scripts/poll_watches.py`, and one migration
(`api/migrations/versions/4c0696953d8d_...`). It reuses the tables the initial
schema reserved empty (`watches`, `alerts`), the existing
`ChainAdapter.fetch_transfers` path, `NormalizedTransfer`, and the tracer's own
qualification rule. No worker, queue, Redis, or second database was added.

**Checkpoint representation.** `watches.checkpoint_time` is a block-time
*frontier*: every qualifying event with `block_time <= checkpoint_time` was
acquired by one complete, untruncated, error-free poll. It is not a
`last_run_at` and not a provider cursor. The existing `watches.cursor` column
stays unused: a TronGrid fingerprint is only valid for the exact parameter set
it was issued under, so it is not a durable resume point. TronGrid's TRC-20
history rows carry no block height and no in-block position, so block time is
the strongest ordering available at this endpoint; the frontier is inclusive
and every event keeps its own `ordering_ambiguous` flag rather than being given
an invented position.

**Replay overlap.** Each poll's window is
`[max(scope_start, checkpoint - overlap_seconds), now]`, lower bound inclusive.
`overlap_seconds` is stored per watch (default `CFA_MONITOR_OVERLAP_SECONDS`,
600 s) so a later poll is reproducible. The overlap exists because a provider
can index an event after a poll has passed its block time (TRON solidification
alone is about a minute). It is a configured margin, not a measured one: an
event indexed later than the overlap after its block time would be missed, and
that is stated on every poll and alert.

**Idempotency key.** `alerts.dedupe_key = "<rule_key>:<event_reference>"`
under the existing `UNIQUE(watch_id, dedupe_key)`. `event_reference` is the
adapter's chain-specific identity (D005), never a transaction hash, so two
transfers in one transaction are two alerts. The watch fixes the network, so
`(watch_id, event_reference)` covers `(watch, network, event_reference)`. The
application checks for an existing alert first; the insert runs in a SAVEPOINT
and an `IntegrityError` there is counted as a duplicate, so a racing second
writer is absorbed by the database, not by application logic
(`test_m13_a_racing_insert_is_absorbed_by_the_unique_key`).

**Crash safety.** A poll commits twice. First, alone, a `watch_poll_runs` row
with `status=running`, so a crash mid-poll leaves an audit row that never
completed. Then, in one transaction, every new alert, every alert state change,
the checkpoint (only on success) and the finished poll-run row. A crash before
that commit changes nothing and the next poll re-reads the same window. The
"alert persisted, checkpoint not advanced" window cannot arise from this code;
it is still tested by forcing it on a file-backed database across a real engine
restart, and the unique key prevents a second alert.

**Failure is never "no activity".** A `ProviderError` on the first page makes
the poll `provider_failure` with `coverage_status=failed`. After some pages it
is `partial`, and a page budget reached before the window ends is `truncated`.
None of the three moves the checkpoint. Events already received in a partial or
truncated poll are still alerted: they were genuinely observed, and idempotency
makes the re-read safe. A truncated window that never fits the page budget would
re-read the same pages indefinitely. That is visible, since every such poll says
`truncated`, and the remedy is a larger `--max-pages`. The checkpoint is never
advanced past pages that were not read.

**Persistence choice.** The existing SQLAlchemy models on SQLite by default
(D012), with a migration. The migration refuses to run if `watches` or `alerts`
already hold rows, because a pre-existing row has no honest `data_mode` or
`event_reference`. Verified on SQLite: upgrade, `alembic check` (no drift from
the models), downgrade, and re-upgrade. **Not run against PostgreSQL** in this
session; the migration reuses existing PostgreSQL enum types
(`create_type=False`) and creates only the two new ones.

**One-shot, not a daemon.** `scripts/poll_watches.py --once` runs one bounded
poll per active watch and exits (0 on all succeeded, 2 otherwise). This is
deterministic and testable, cron/systemd can schedule it, and restarting is
just the next invocation. Polling is deliberately not an HTTP route, so no
provider call happens inside a web request. A LIVE run writes every provider
exchange to `var/monitoring/<capture-id>/raw/` through the existing
`BundleRecorder`, plus a manifest with the same `{file: sha256}` shape
`verify_manifest_hashes` checks. Headers, and so the API key, are never
recorded, and the configured key and session secret are value-redacted from
stored error text.

**Why this is not a mempool feed.** It reads the TronGrid TRC-20 history
endpoint with `only_confirmed=true`: indexed, confirmed history, after the fact.
Nothing pending or unconfirmed is observable. Every poll output, alert, route
response and capability row says "polling of indexed provider history; not a
mempool feed".

**Observation lag.** `first_observed_at - block_time`, recorded per alert with
a `basis`. `live_wall_clock` is used only for a LIVE poll on the real clock (a
LIVE poll with an injected clock is refused). `simulated_clock` or
`synthetic_fixture_times` apply to SYNTHETIC data and are labelled "not a
latency measurement". A RECORDED_PUBLIC replay gets `null` with basis
`unavailable_recorded_replay`. It is never described as mempool, propagation or
exchange-notification latency. **No live lag has been measured; no latency
figure exists.**

**Execution and finality.** TronGrid history rows document no execution status,
so every row starts `unknown`. For a TronGrid source, the monitor calls the
existing `verify_execution` (receipt endpoints) for new or still-unknown
candidates only. A `failed`/`reverted` receipt excludes the event, or retracts
an existing alert. An unverifiable receipt leaves the alert at
`execution_status=unknown` with the reason stored; it is never upgraded to
success. Execution and confirmation are separate columns and a separate
history.

**Reorg / removal semantics.** An alert first seen `provisional` is upgraded to
`confirmed`, and an alert later observed `removed` (or `failed`/`reverted`) is
set `state=retracted`. Both are recorded in `evidence.state_history`, and the
alert row is never deleted (T7). **Limitation:** the TronGrid history endpoint
serves confirmed rows only and exposes no removed-event signal, so on the live
path retraction can only come from a receipt. Removal is exercised only where a
source reports `confirmation_state=removed` (fixtures, tests). An event that
merely disappears from a later poll is not treated as removed.

**Authorization and UI.** Watches are case-scoped. `POST/GET
/api/v1/cases/{id}/watches`, `GET .../{watch_id}`, `.../alerts` and `.../polls`
all resolve the case through `AuthorizedCase` and the watch through that case,
so a foreign organization gets 404 for the case, the watch, its alerts, and its
polls. The unauthenticated local dashboard shows only the capability row, which
is `partial`: the code is tested offline and no live poll has been verified.
Watch counts and alerts are case data and stay behind the authenticated API.
`GET /api/v1/meta` reports `monitoring: "POLLING_ONLY"`.

**Scope held.** TRON only; the watch's single verified TRC-20 contract (exact
contract, never a symbol; a LIVE watch refuses a SYNTHETIC fixture asset); one
rule, `new_supported_token_transfer` v1. No notifications, no automatic action,
no ML, no scoring, no multi-chain.
