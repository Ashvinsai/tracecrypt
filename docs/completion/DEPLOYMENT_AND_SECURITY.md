# Deployment, evidence and operational boundaries

## Local process model

`launch.py --with-worker` manages the HTTP process and a companion trace worker. The queue persists in SQL rather than Python memory. Claims are conditional and leased; a stale worker must pass a token fence before saving a result. An interrupted claim can be retried after lease expiry. Exhausted leases become failed instead of remaining permanently running. A cancelled job cannot subsequently commit its result through the old lease.

SQLite uses WAL and a 15-second busy timeout on local disk. Idle queue polls do not write. Read transactions are released before provider I/O and report rendering. This fixes the worker/export lock observed during integration checking; it is **not** proof of unlimited concurrent write scalability. Use one SQLite worker. Do not use SQLite WAL on an unsuitable shared/network filesystem.

PostgreSQL-specific claim code uses `FOR UPDATE SKIP LOCKED`. That database backend, concurrent workers, migrations against PostgreSQL, crash/failover behavior, load, capacity, fairness and operational quotas still need deployment-specific validation. Install the appropriate PostgreSQL driver separately. The code does not include a whole-chain ingestion cluster, Kafka deployment, autoscaling or a distributed watch scheduler. The event table indexes exact observations saved by investigations, not every chain transaction.

Queue retry backoff, provider budgets and a bounded task count are protective local limits. They do not constitute a production SLA or a strongly serialized concurrent tenant quota. Job execution is at-least-attempted with fenced final saves; do not market it as end-to-end exactly-once external execution.

## Access and secrets

Basic session authentication, organization-aware case access, same-origin mutation checks, input validation, size limits and no-store API responses are present. Intake bearer credentials are expiring, source/organization-bound and hashed at rest. Administrative issuance is a local host operation. Use HTTPS in production; trust forwarded headers only from the actual reverse proxy. Never expose public demo credentials or a demo database.

Fine-grained government roles, SSO, multi-factor authentication, independent penetration testing, immutable external audit custody, database encryption, encryption-key rotation, backup restoration drills, retention/deletion schedules and accreditation are not completed by this prototype. Storage and database administrators can change both content and its local hash. The manifest provides change detection relative to its stored value, not independent provenance authentication, an external timestamp signature or guaranteed legal admissibility.

Provider URLs can include secrets. The new bounded CCTP acquisition stores request methods/parameters and response artifacts, not configured provider URLs. Failure summaries use categories rather than raw URLs or secrets. Audit exports and complaint references remain sensitive case information and must be protected even when no victim name is collected.

## Meaning of attribution

A service-controlled recipient and a transaction from a reported wallet do not prove that the sender is service-controlled. A first receiving service boundary is returned only when supported by applicable accepted service-control evidence. Conflicting entity or role assertions are not resolved by input order. Transaction connectivity alone does not establish custody of the victim's exact units after commingling. Unspent balance, recovery amount, customer identity and account ownership are not invented.

A label set needs scope, source, time validity and review. This ZIP contains only two narrow historical accepted real OKX addresses. The synthetic label set is separate and conspicuously fictional. Unsupported networks, missing providers, inadequate finality, incomplete pagination and unknown labels remain visible limitations rather than clean-looking empty successes.

## Cross-chain checker

The new runtime connector accepts **one Ethereum→Base USDC CCTP V2 message**, with optional exact Base destination transaction or a bounded Base block window. It checks both RPC chain IDs; successful receipts; receipt/block hash and height agreement; provider-reported finalized heights; chronological ordering; non-removed relevant logs; recognized contracts; source message/log reconciliation; unique matching complete Iris message; nonce, domains, caller/recipient and exact amount-minus-fee reconciliation; destination message body, mint and final USDC Transfer.

Automatic destination search derives a bounded window from timestamps/finalized blocks and is capped. Multiple messages, ambiguity, unsupported route, missing data, pending finality and malformed evidence fail or remain unresolved. Acquisitions obtained before failure are retained in the review evidence where available. The raw bundle is hash-checked before export or continuation. Recipient continuation is explicit and idempotent, starts at the destination time and is **address discovery**, not an assertion that all future recipient funds are victim funds. The evidence package for a linked saved recipient run includes its checked cross-chain review.

The connector trusts the configured RPC and Circle API observations. It does not independently verify Circle attestation signatures, re-execute contracts, validate consensus or authenticate archival captures. The older CCTP research CLI and captured examples are retained as historical tools, not silently substituted for this new checker. Offline tests replay supplied captures and use HTTP mocks; no new live provider transaction was traced in this build.

## ML and recommendations

The deterministic pattern priority rules are separate from ML. Optional IsolationForest refits over a bounded organization/mode/network/token cohort and does not load arbitrary pickles. At least 25 distinct eligible seed wallets are required; the earlier 80% trains and only later saved traces are scored, with disjoint seed wallets and no time ties across the split. Only the newest 500 snapshots are scanned before scope filtering. Missing dependencies or inadequate data yield explicit statuses, not pretend scores.

The anomaly score measures unusual graph structure within that selected complaint-derived sample. It is not a probability of crime, a validated fraud detector, a wallet ownership label or an enforcement instruction. Feature sizes depend on available tracing scope. No fraud precision/recall, unbiased sampling or field calibration has been demonstrated. The original CLM is optional shadow action ranking; it cannot independently change evidence or authorize action.

## External systems

NCRP/SAHYOG/VASP connectors require actual authorized onboarding. The supplied application-owned bearer endpoint can receive a mapped complaint, but it does not create a government account or send notices. Request generation is draft-only and requires investigator review. No blockchain signing, asset custody or freezing takes place. No secret-bearing third-party endpoint is contacted merely because an address appears in an input payload.

Primary reference documents consulted for design (not evidence of integration):

- PostgreSQL SELECT / SKIP LOCKED: https://www.postgresql.org/docs/current/sql-select.html
- Circle CCTP technical guide: https://developers.circle.com/cctp/references/technical-guide
- Circle CCTP contracts: https://developers.circle.com/cctp/references/contract-addresses
- Circle USDC contracts: https://developers.circle.com/stablecoins/usdc-contract-addresses
- scikit-learn IsolationForest: https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html
- NCRP information: https://i4c.mha.gov.in/ncrp.aspx
- SAHYOG portal: https://sahyog.mha.gov.in/

These references describe external systems; always recheck their current scope, authorization requirements and API documentation before deployment.
