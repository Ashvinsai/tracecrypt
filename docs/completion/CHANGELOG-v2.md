# v2 source map and change log

## Application additions

`api/app/models/operations.py`: credential, complaint, job, indexed observation, signal and cross-chain review models.

`api/migrations/versions/a092operations02_operations.py`, `a093crosschain03_reviews.py`: operations/cross-chain persistence.

`api/app/services/operations/contracts.py`, `intake.py`: strict application-owned intake, scoped credentials and idempotent task creation.

`queue.py`: persistent claims, leases, retries, expiry recovery, cancellation fences and atomic trace/snapshot/index/signal saves.

`attribution.py`: verified-path nearest-service summaries, ties and accepted-service grouping.

`indexing.py`: hash-checked exact per-run events and indexed retrieval.

`ml.py`: genuine optional held-out IsolationForest anomaly ranking, insufficient-data reporting and no criminality probability.

`cctp.py`: bounded single-message Ethereum→Base USDC CCTP V2 acquisition/reconciliation and partial evidence retention.

`api/app/routes/operations.py`: authenticated operations and cross-chain endpoints.

`workspace/operations.js`, additions to `workspace/index.html`, `app.js`: complaint/jobs/signals, attribution, CCTP review and ML views.

`operations_worker.py`, `gateway_admin.py`, changes to `launch.py`: persistent automatic work and local credential administration.

## Correctness changes

Incident-start propagation reaches traversal, not just initial seed search. Conflicting accepted entity/role labels do not select the first registry row. Reviewed duplicate sources agreeing on the same conclusion remain usable. Nearest-service rank uses actual event-path length. Optional ML canonicalizes the actual token string. Source/destination protocol evidence can be attached to recipient investigation exports.

SQLite uses local WAL, idle workers do not reserve write locks, and lengthy trace/PDF work releases read transactions. Repeat demo setup preserves the existing complete fixture and refuses partial/conflicting data. API no-store headers and bounded streamed intake bodies are retained.

## Validation

Four new `test_operations*.py` modules cover intake/jobs, tenancy, hashes, windows, stale workers, ML, CCTP evidence reconciliation and attribution conflicts/ties. Their executed results, broader regression logs, browser screenshots and package startup checks are under `validation/v2/`. Older merge validation remains historical, not the authoritative v2 pass count.

## Deliberately not merged into active behavior

Fixed 100%-confidence sender ownership from forwarding ratios; incorrect haircut accounting; mock labels promoted to verified intelligence; fake provider connection/indexing statistics; invented cross-chain matches; silent network errors represented as complete empty results; automatic external enforcement or freezing.
