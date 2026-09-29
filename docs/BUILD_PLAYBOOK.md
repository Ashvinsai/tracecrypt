# Crypto Fraud Attribution — phased AI-assisted build playbook

**Prepared: 19 September 2026.** This is a planning and prompt pack, not an implemented or tested application. It assumes a small team, limited initial infrastructure, no commercial attribution licence, and no approved government credentials. Adjust scope based on actual team capabilities; no completion-time or universal coverage guarantee is made.

## Use it in order
Read START_HERE.md, then put AGENTS.md in your repository. Review the design and acceptance catalog. Give your coding assistant one phase prompt at a time. You remain responsible for reviewing data provenance, tests, and claims. Do not send actual victim information to a public coding assistant.

**Working cycle:** inspect -> define acceptance tests -> implement a small change -> run tests -> inspect evidence and diff -> commit. Completion is determined by the gate, not by the assistant saying “done.”

## Milestones
- **Narrow working prototype:** phases 00–11, with the relevant controls/tests from 15–17. TRON-only is a declared limited prototype.
- **Broader problem-statement demonstration:** add phase 12 (at least one additional chain), phase 13 (a specifically supported cross-chain route), and phase 14 only if claiming implemented AI/ML.
- **Presentation:** phase 18, backed by actual evaluation.
- **Operational service:** phase 19 requires authorization and independent validation beyond a prototype.

## Proposed stack
Use Python/FastAPI, PostgreSQL, React/TypeScript, Redis with one worker library, a bounded in-memory graph engine, and Docker Compose. A graph database, Kafka, Kubernetes, full nodes, a token, and a custom smart contract are not prerequisites for the initial read-only prototype. This is a recommended simple architecture, not a benchmarked winner. Verify compatible versions before installation.

## Phase 00 — Scope and measurable requirements

**Purpose:** Agree on exactly what a trace result means before generating application code.

**Prompt to use:**

```text
Create docs/PRD.md, docs/REQUIREMENTS_MATRIX.md, docs/THREAT_MODEL.md, and docs/DECISIONS.md. Define address-discovery mode separately from incident-trace mode. Incident mode accepts network, address, transaction hash and selected transfer event where available, asset, amount, time window, and case reference. Address-only inputs return scoped activity leads without asserting that every transfer contains victim funds.
Define the first supported receiving VASP on each chronological branch as the destination, with deposit-candidate and known-service endpoints clearly distinguished. Document live/recorded/synthetic modes and explicit unknown, partial, ambiguous, and unsupported outcomes.
Map every problem-statement requirement to a component, phase, demonstration, and limitation. Propose initial configurable search budgets; identify them as targets, not measured performance. Keep KYC identity discovery, automatic freezes, all-chain coverage, and universal mixer tracing out of the initial scope. Do not claim approved government connectivity.
```

**Completion gate:** A teammate can explain inputs, outputs, uncertainty, and non-goals; every problem-statement item has a mapped implementation or explicit dependency.

## Phase 01 — Repository, environment, and secure application skeleton

**Purpose:** Make a reproducible project that runs locally before adding blockchain logic.

**Prompt to use:**

```text
Create a monorepo with Python/FastAPI API and worker modules, React/TypeScript frontend, PostgreSQL, Redis, and Docker Compose. Choose compatible maintained versions after checking official documentation; pin them with lockfiles. Use one ORM/migration tool and one worker library rather than competing stacks.
Implement health/readiness routes, structured logs, request IDs, environment validation, .env.example, ignored secrets, basic authenticated sessions using maintained authentication components, organization/case authorization interfaces, and a development-only local account bootstrap. Never use default production credentials or home-grown cryptography.
Expose documented make targets for dev, test, lint, typecheck, migrate, and seed-demo, with platform alternatives. CI should run deterministic tests without live provider keys. Create a minimal frontend showing build mode and API health. Do not generate fake working chain integrations.
```

**Completion gate:** A fresh clone boots from the README, migrations run, unauthorized requests fail, and smoke tests run without live keys.

## Phase 02 — Canonical data model and test fixtures

**Purpose:** Prevent irreversible design errors around networks, amounts, event identity, and evidence.

**Prompt to use:**

```text
Implement versioned schemas and migrations using design/SCHEMA_AND_API.md. Include networks, assets, addresses, blocks/inclusions, transactions, transfer events, acquisitions, entities, attribution evidence, label assertions, cases, case seeds, trace runs, trace states, findings, watches, alerts, exports, and audit events.
Use exact integer base units and string serialization for large values. Include a stable documented chain-specific event reference and block inclusion information; never deduplicate solely by transaction hash. Preserve original input and canonical network-scoped identity.
Define separate execution_status, coverage_status, attribution_status, and boundary_reason fields. Introduce a fixed analysis cutoff and versioned engine/label configuration.
Translate the supplied acceptance catalog into independently reviewed fixture tests by implementation phase. Use symbolic synthetic addresses only in fixture mode. Implement a fixture provider against the same adapter interface planned for live providers; do not bypass tracing with hardcoded result objects.
```

**Completion gate:** Multiple events in one transaction survive storage; network separation, integer precision, and fixture isolation tests pass.

## Phase 03 — TRON live-data adapter

**Purpose:** Connect to real chain observations without corrupting them.

**Prompt to use:**

```text
Read current TRON documentation for account TRC-20 history, transaction receipts, events, and rate limits. Configure mainnet/testnet base URLs explicitly; do not copy a testnet documentation example into mainnet configuration. Configure the genuine supported token using issuer-verified contract metadata rather than a ticker.
Implement address validation/canonicalization; paginated history retrieval with an analysis cutoff; outgoing/incoming filters; retry/backoff with jitter; configurable rate limits; timeout/error classification; and acquisition provenance. Keep pagination query parameters consistent for a cursor. Filter transfer records versus approval records and verify execution/confirmation state before calling a transfer confirmed.
Enrich relevant transactions from receipts/events/block data when history pages lack event identity or same-block order. Preserve ambiguity rather than fabricate fields. Implement receipt and range caches with freshness metadata. Never return an empty successful history after an authentication or quota error.
Provide opt-in live contract tests and deterministic recorded-response tests. Record what coverage the adapter actually supports.
```

**Completion gate:** Pagination, duplicate pages, multiple events, token spoofing, failed receipts, and API outages are tested; selected live records are manually reconciled with their source.

## Phase 04 — Trusted label registry and provenance workflow

**Purpose:** Build the scarce attribution input instead of pretending that the graph contains exchange names.

**Prompt to use:**

```text
Implement label import, validation, review, conflict handling, time validity, and a provenance drawer. Store entity type separately from address role. Distinguish supported service-control assertions, deposit candidates, complaint allegations, public abuse reports, and sanctions-related tags.
Support CSV/JSON import with source reference, retrieval date, evidence document hash, reviewer, methodology, valid_from/valid_to, and last_verified_at. Public disclosures and permitted public tag collections are starting inputs, not automatic ground truth. Review each source's provenance and reuse terms. A reserve wallet is not automatically an active customer-deposit address.
Seed fictional services only in synthetic mode. Create an evidence checklist for manually reviewing a small real label set; do not generate plausible real labels or claim completeness. Add stale/conflicting-label views and scheduled review tasks. Candidate labels must not be promoted by merely participating in further heuristics.
Make exports and label history reproducible by label-set version.
```

**Completion gate:** Every visible real entity attribution has inspectable evidence; unsupported imports are rejected or quarantined; conflicts and expired validity do not disappear.

## Phase 05 — Chronological tracing engine

**Purpose:** Deliver the first correct address-to-service trace on controlled examples.

**Prompt to use:**

```text
Implement a bounded, deterministic forward exploration engine over normalized events. Maintain states containing network, asset, current receipt/event order, branch history, and scope rather than only an address. Cache address history separately from tracing state. Do not use a static lifetime shortest path or a global visited-address shortcut that drops later valid receipts.
Use successful relevant transfers, chronological ordering, and explicit same-block ambiguity. Preserve fan-out and reconverging branches. Check supported receiving service labels at each branch and stop the supported custody trace at its first justified service boundary. Do not continue from a pooled exchange wallet to arbitrary withdrawals as victim funds. Show candidates separately and continue to a supported boundary where evidence permits.
Implement hop/event/API/time limits, cancellation, fixed snapshot cutoffs, and unresolved branch accounting. Unsupported asset changes, bridges, privacy mechanisms, and opaque contract flows produce boundary findings rather than guesses.
Return observed event paths, their provenance, limitations, and candidate endpoints. Do not calculate exact victim-fund allocations yet.
```

**Completion gate:** Golden tests reject the pre-receipt shortcut, retain separate branches, avoid cycles/repeated-event loops, and stop at the correct supported custody boundary.

## Phase 06 — Conservative inference, case linkage, and amount uncertainty

**Purpose:** Expand coverage without turning behavioral resemblance into ownership proof.

**Prompt to use:**

```text
Implement this phase as three reviewable tickets: (A) deposit-candidate features, (B) evidence categories and case-linkage assessment, (C) amount presentation.
A: derive inspectable features such as repeated forwarding to supported operational anchors, concentration, delay distributions, repeated low residual balances where complete data supports them, and independently evidenced operational funding. Store feature windows, exclusions, rules, and versions. Benign frequent customers are required negative examples. Output CANDIDATE, never a trusted owner label from a sweep pattern alone.
B: keep attribution, case-flow linkage, behavioral indicators, and completeness independent. Define supported/inferred/conflicted/unresolved categories and show reasons. No fabricated probabilities or unvalidated heuristic weights disguised as confidence.
C: always show observed transfer amount independently of victim-associated estimates. Default to allocation_unknown for mixed or incomplete balances. An optional simple bound calculator is allowed only under documented complete-history assumptions and reviewed tests. Do not sum overlapping/reconvergent path estimates. Never assign more case value than the seed, duplicate it across branches, or assume an outgoing transfer consists entirely of victim funds.
```

**Completion gate:** The 900-existing + 100-victim -> 500-out example is ambiguous, not a 500 victim transfer; repeated customers are not auto-labelled as service-owned.

## Phase 07 — Trace jobs, caching, and incremental responses

**Purpose:** Keep the interface responsive while controlling provider load and analysis scope.

**Prompt to use:**

```text
Implement an authenticated trace-job API returning a job ID, with a worker performing bounded analysis. Stream or poll genuine progress and partial findings; do not fabricate progress percentages. Store durable run state, deadlines, input hashes, engine/label versions, and final coverage.
Implement idempotent job creation, per-organization quotas, cancellation, retry budgets, and checkpoint recovery. Reuse public chain observations while isolating case-derived results and private labels. Cache keys must include network, asset, scope, confirmation policy, relevant label/engine version, and authorization boundaries where applicable.
Deduplicate concurrent fetches and impose a provider-wide budget across new traces and watches. Handle stale-cache fallback explicitly with acquisition times. Reorg or label changes must invalidate or version affected results. Expose searched/pending/pruned branches and budget use.
Measure warm/cold first-result time and final-result time separately. A proposed thirty-second initial budget is a configuration to test, not a guaranteed attribution time.
```

**Completion gate:** Duplicate submissions do not duplicate work; interrupted jobs recover; one organization cannot retrieve another organization's case cache.

## Phase 08 — Investigator dashboard and intake

**Purpose:** Make evidence and uncertainty usable without requiring manual graph expertise.

**Prompt to use:**

```text
Build intake, case list, trace detail, source/label inspector, watch panel, and export preview. Network selection is explicit when address syntax is ambiguous. When a transaction includes multiple transfers, let the user select the relevant event. Do not request seed phrases or private keys.
Render a graph with distinct observed-transfer, inferred-attribution, and supported protocol-link types. Also provide an accessible chronological table. Every observed edge opens its transaction/event evidence, amounts, network, asset, ordering, and confirmation state. Every entity name opens provenance and role.
Show data mode, analyzed cutoff, acquisition freshness, supported/inferred/unknown status, partial coverage, unresolved branches, and search limits beside the result rather than in hidden tooltips. Separate observed service receipts from estimated case-associated amounts.
Use real job status from the API, paginate large histories, cap graph rendering without silently trimming analysis, and expose zero-result/error states clearly. Build an honest coverage panel. Test intake-to-result-to-export navigation.
```

**Completion gate:** A reviewer can distinguish what was observed, inferred, incomplete, and simulated; changing the URL does not bypass case authorization.

## Phase 09 — Monitoring, alerts, and explainable behavioral rules

**Purpose:** Detect supported new activity without claiming universal mempool access.

**Prompt to use:**

```text
Implement watch registration with permissions, monitored scope, configurable polling/subscription strategy, persistent cursor, replay overlap, deduplication, confirmation policy, and cancellation. Start with supported TRON event/block observations. Report provider/indexing lag and provisional/confirmed/removed states separately.
Create rules for new case-linked movements, reached supported service boundaries, label changes, supported rapid-forwarding/fan-out patterns, and unresolved protocol boundaries. Each alert includes evidence IDs, rule version, window, and limitations. Behavioral resemblance is not proof of money laundering or a particular scam type; complaint typology remains an allegation.
Add alert acknowledgement, duplicate suppression, resume-after-restart tests, per-user/organization access, and a global provider budget shared with traces. Do not poll every watched address at an unrealistic interval independent of quotas. Retractions/updates must propagate when observations are invalidated.
WebSocket or SSE delivery from your backend to the browser is not evidence of a blockchain mempool feed; label the monitored source accurately.
```

**Completion gate:** A replayed new event creates one alert, worker restart does not create gaps, and removed/provisional events are not reported as settled facts.

## Phase 10 — Evidence bundle and reviewed request drafts

**Purpose:** Turn the analysis into a reproducible operational artifact.

**Prompt to use:**

```text
Implement a versioned investigation bundle with readable report, transfer CSV, findings JSON, label/evidence provenance, acquisition metadata, raw-response references or access-controlled snapshots, checksum manifest, and engine/configuration versions. Reports must include scope, cutoffs, unresolved branches, confirmation states, and whether the data is live, recorded, or synthetic.
Use deterministic templates for core facts; never rely on an LLM to calculate amounts or compose unsupported attribution. Implement report preview, redaction, pagination/long-hash handling, content escaping, and CSV-formula neutralization. Export exact transaction identifiers in a copyable format.
Create distinct drafts for information, preservation, and asset-restriction requests. Add fields for case context, authorized requester, reviewed legal basis, precise requested action, relevant deposit identifiers, and attachments. Mark as DRAFT / REVIEW REQUIRED and block submission until an approved process exists. Do not invent legal citations, signatures, or authority, or request freezing an entire pooled wallet by default.
Support reproducible re-generation from saved analysis snapshots; document that hashes establish file integrity, not factual correctness or legal admissibility.
```

**Completion gate:** Report identifiers reconcile with source events, hash verification detects changes, and no external request is sent by generating a draft.

## Phase 11 — External API and mock LEA integration

**Purpose:** Demonstrate integration readiness without fabricating institutional access.

**Prompt to use:**

```text
Publish a versioned OpenAPI contract for case intake, address validation, trace jobs/results, watches, alert acknowledgements, evidence exports, and reviewer approval state. Validate request size, field limits, agency/case scopes, and idempotency.
Implement a clearly marked mock complaint-system connector and webhook simulator. Use authenticated requests or signed messages, replay protection, stable external complaint IDs, error/retry behavior, and delivery acknowledgements. Define schema-mapping adapters so approved future systems do not dictate the internal schema.
Create a connector-status screen: MOCK, NOT CONFIGURED, SANDBOX, or APPROVED LIVE. Use actual supplied specifications before implementing NCRP/SAHYOG endpoints; do not guess hostnames, payloads, credentials, legal permissions, or available functionality.
Keep real case data out of public demo webhooks. Human approval must be required before any externally consequential operation. Record integration contracts, contact verification procedures, and production access dependencies.
```

**Completion gate:** A duplicate simulated complaint creates one case; invalid/replayed messages fail; all demonstration integration output clearly says MOCK.

## Phase 12 — Additional chains and capability registry

**Purpose:** Make multi-chain a tested capability rather than a list of logos.

**Prompt to use:**

```text
Add an EVM adapter using current documented explorer/RPC interfaces, explicit chain ID, asset registry, receipt/log enrichment, and the same normalized contracts. Verify provider-plan support for each selected network instead of assuming a shared key means free access everywhere. Implement correct event identity and canonicality handling.
Test identical address strings on different networks, duplicate logs, failed receipts, multiple token events, asset decimals, pagination, and chain reorganizations. Show per-network/per-asset capabilities and known exclusions. TRON and one tested EVM network are the first multi-chain milestone; additional chains must pass adapter contract tests.
Treat Bitcoin as an optional separate subproject. Model transactions, spent outpoints (txid,vout), and new outputs; do not force account-token tracing semantics onto UTXOs. Multi-input/multi-output allocation and ownership heuristics require explicit uncertainty. Do not infer a named owner using naive common-input/change rules.
Do not claim that independent chain queries constitute cross-chain tracing.
```

**Completion gate:** The same incident workflow works on each claimed network, and the capability screen disables unsupported assets and features.

## Phase 13 — Protocol-aware bridges, swaps, and privacy boundaries

**Purpose:** Extend the trace only where protocol evidence establishes a supported connection.

**Prompt to use:**

```text
Implement a protocol-adapter interface identifying protocol version, supported networks/contracts, source event, destination event, asset transformation, amount/fee interpretation, message identifiers, finality, and evidence references.
Select one documented cross-chain protocol with accessible fixtures and live/public examples. A Circle CCTP USDC demonstration is one possible choice on currently supported networks; it is not TRON-USDT or arbitrary bridge coverage. Verify matching source message and destination execution, contract/domain/version identity, replay state, and confirmation requirements. An attestation or matching amount alone is not proof of completed destination execution.
For swaps, add at most one narrowly scoped protocol/version adapter using decoded logs and receipt evidence. Do not infer an onward transfer from any pool output. Unknown routers, multi-route swaps, liquidity actions, bridges, or privacy mechanisms return explicit unresolved boundaries.
Do not create verified edges by timestamp/amount similarity or reused address strings. Any experimental correlation lead must remain separate from supported paths and reports.
```

**Completion gate:** A supported protocol fixture links correctly; missing destination execution and equal-amount unrelated transfers remain unresolved.

## Phase 14 — Optional AI/ML assistance

**Purpose:** Add assistance without handing factual attribution to a language model.

**Prompt to use:**

```text
Keep the deterministic investigation workflow fully functional with AI disabled. First implement rule-based prioritization as a baseline. Only train ML after defining a task, obtaining permissioned representative labels, and separating training/validation/test data by time and entity as appropriate. Do not call a hand-written rule engine a trained model.
Use ML for lead prioritization or anomaly detection, not unsupported named-exchange identification. Publish task definition, training-source limits, evaluation, calibration where relevant, false positives, and versioning. Unknown owners remain unknown.
An optional LLM summary receives only approved structured findings and evidence IDs, with personal data removed or retained locally under approved policy. Validate its structured output against existing evidence IDs and exact amounts; reject invented entities, transactions, confidence values, or legal authority. Treat complaint text and external metadata as untrusted data, not instructions.
Provide a deterministic summary fallback, reviewer approval, failure handling, and prompt-injection tests. The AI must not submit requests, modify labels, fetch arbitrary URLs, or change the graph autonomously.
```

**Completion gate:** Disabling AI changes neither trace nor attribution; fabricated evidence references are rejected; injected instructions do not produce actions or data disclosure.

## Phase 15 — Security and data-governance hardening

**Purpose:** Review the whole system before placing it on a network or using real complaints.

**Prompt to use:**

```text
Extend security controls from phase 01. Threat-model case-ID guessing, cross-organization access, label poisoning, hostile uploads/metadata, quota exhaustion, report injection, dependency compromise, and stolen credentials.
Test authorization on every case/job/watch/stream/export route; use least-privilege identities, secret rotation procedures, approved session/auth components, transport encryption, and restricted database/cache access. Sanitize rendered text, neutralize spreadsheet formulas in CSV exports, restrict report-renderer network/file access, and allowlist external acquisition destinations where appropriate.
Add upload size/type checks and safe filename handling. Prevent SSRF in provenance fetching and webhooks, avoid arbitrary local file access, and strip secrets/PII from logs. Separate public chain caches from restricted case data and private labels.
Define retention, deletion holds, access audit, evidence versioning, backup protection, breach response, and permitted AI processing with the intended agency before real deployment. A hash chain alone is not tamper-proof storage. Run dependency and secret scans; report actual unresolved issues rather than asserting perfect security.
```

**Completion gate:** Cross-case access and export bypass tests fail safely; logs contain no test secrets; hostile text stays inert; unresolved high-impact risks block real-data deployment.

## Phase 16 — Independent correctness and performance evaluation

**Purpose:** Prove the benefit with reproducible measurements rather than demo-only successes.

**Prompt to use:**

```text
Build a benchmark harness separating synthetic algorithm tests, recorded public observations, and independently verified real attribution cases. Do not evaluate a heuristic against labels produced by that same heuristic. Keep a held-out set and time/entity-separated examples where possible.
Compare direct lookup, lookup plus chronological tracing, and the full conservative-inference system on identical cases and budgets. Report named-service precision with sample size and uncertainty, resolution coverage with a clear denominator, path correctness, false alerts, unresolved outcomes, warm/cold latency percentiles, freshness, API calls, and resource usage. Do not count a synthetic supported label as real-world attribution success.
Add deliberate difficult cases: wrong time order, mixed funds, reconvergence, frequent exchange customers, competing labels, unknown assets, failed API pages, provisional/removed events, unsupported protocols, and queue overload. Test each chain separately.
Publish failure analysis, exact configuration, dataset provenance, hardware, provider plan, and capture date. A small sample is a limitation, not permission to claim national accuracy. Real recovery outcomes are outside synthetic validation.
```

**Completion gate:** A reviewer can reproduce the benchmark and see failures, denominators, and limits; no displayed percentage lacks a measured supporting dataset.

## Phase 17 — Deployment, capacity, and operations

**Purpose:** Make the prototype maintainable and quantify what scaling would require.

**Prompt to use:**

```text
Create reproducible deployment manifests for an approved environment, with HTTPS, restricted service exposure, health checks, worker limits, durable database/evidence storage, secret injection, and environment separation. Document dependency versions and licenses.
Test database migrations, backup restore, provider outages, worker crashes, queue recovery, and graceful shutdown. Add metrics for request budget use, indexing lag, time-to-first-result, error rate, queue depth, label age, and disk/storage growth.
Estimate daily provider calls as new-trace work plus receipts/enrichment plus watch scans; use measured calls per case and actual provider terms rather than invented prices. Share public event acquisition across watches while enforcing case privacy. Add selective incremental indexing, partitions/indexes, fair scheduling, and horizontal workers only after measurements identify a bottleneck. Do not claim unlimited scale from one server.
Provide a deployment runbook, cost worksheet in Markdown, rollback plan, retention settings, and clearly separate local-demo readiness from production security/availability approval.
```

**Completion gate:** Another teammate deploys the application, restores a backup, observes a simulated provider outage, and understands the workload/cost assumptions.

## Phase 18 — Demo, documentation, and judge questions

**Purpose:** Demonstrate the end-to-end system honestly under success and failure conditions.

**Prompt to use:**

```text
Create a rehearsable demo with: (1) supported service destination, (2) intermediary and independently justified inference, (3) unresolved/mixed or protocol-boundary case, (4) new-event alert, (5) reviewed evidence export, and (6) clearly marked mock integration. Show a second chain and protocol route only if implemented and tested.
Prepare a recorded fallback with visible capture times and synthetic examples with fictional names. Never present recorded output as live, fake a freeze, or claim an unseen address must resolve. Display the current coverage matrix and label provenance.
Write an architecture summary, installation guide, investigator workflow, API documentation, evaluation report, limitations, attribution methodology, data/license inventory, threat model, and maintenance plan. Include measured benchmarks and prior-art comparison without unverified first-ever or cheapest claims.
Create judge answers grounded in your artifacts: labels, false positives, speed, mixing, unknowns, offshore cooperation, privacy, costs, government integration, scalability, and ML necessity. No unmeasured recovery or accuracy statistics.
```

**Completion gate:** A teammate unfamiliar with the implementation can run the demo; every claim can be traced to implemented behavior, a test, or an explicit dependency.

## Phase 19 — Authorized pilot and long-term maintenance

**Purpose:** Separate a useful prototype from an approved operational service.

**Prompt to use:**

```text
Produce a pilot-readiness checklist covering intended agency authorization, data handling, security review, label-source licensing, approved infrastructure, analyst training, support ownership, and signed integration/data-sharing arrangements where required. Do not connect to real complaint systems merely because mock tests pass.
Define shadow-mode evaluation: analysts compare the system against established investigations without automatic consequential actions. Record disagreements, verified VASP confirmations, corrected labels, timeliness, and workflow utility under approved access. Use only permissioned case material and verified outcomes.
Establish label re-verification, dependency/provider monitoring, supported-protocol review, versioned releases, incident response, audit retention, deletion/hold procedures, and appeals/correction workflow for erroneous private intelligence. Integrate private confirmed labels without leaking customer data into public packs.
Expand chain coverage and indexing only when case demand, validation, cost, and maintainers justify it. Document explicit production go/no-go criteria and unresolved external dependencies. Recovery and freeze outcomes can be measured only when verified through authorized operations.
```

**Completion gate:** There is a named operational owner, approved scope, measured shadow evaluation, and documented production approval—not merely a prototype deployment.

## Source register
These are primary documentation references checked for the planning guidance. Re-check versions, terms, supported networks, and access at implementation time. Source references are not endorsements or permission to redistribute data. All other project requirements are proposed engineering choices rather than claims that a product already implements them.

```text
S1  TRON account TRC-20 records
https://developers.tron.network/reference/get-trc20-transaction-info-by-account-address
S2  TRON receipt details
https://developers.tron.network/reference/gettransactioninfobyid
S3  TronGrid quotas and retry guidance
https://developers.tron.network/reference/rate-limits
S4  TRON event access methods
https://developers.tron.network/docs/event-subscription
S5  Issuer token/protocol registry
https://tether.to/en/supported-protocols/
S6  GraphSense public TagPacks and provenance format
https://github.com/graphsense/graphsense-tagpacks
S7  Etherscan account token transfer endpoint
https://docs.etherscan.io/api-reference/endpoint/tokentx
S8  Etherscan supported chains and plan restrictions
https://docs.etherscan.io/supported-chains
https://docs.etherscan.io/rate-limits
S9  Ethereum receipt/log identity, ordering, and removed state
https://ethereum.org/en/developers/docs/apis/json-rpc/
S10 Bitcoin transaction input/output model
https://developer.bitcoin.org/devguide/transactions.html
S11 Circle CCTP message and destination-execution model
https://developers.circle.com/cctp/references/technical-guide
S12 Example VASP-specific law-enforcement request requirements
https://www.okx.com/help/okx-law-enforcement-request-guide
S13 OWASP authorization guidance
https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
S14 OWASP prompt-injection guidance
https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
```

Sources support limited technical facts: S1–S4 describe TRON data access, pagination, receipts, and event transport; S5 is an issuer source for asset configuration; S6 illustrates structured attribution provenance; S7–S9 document EVM API/event concepts; S10 establishes the distinct UTXO model; S11 documents one cross-chain protocol, not universal bridge tracing; S12 illustrates why request formats and authorization require service-specific review; S13–S14 support security design. Consult the original documentation instead of treating generated prompts as API specifications.
