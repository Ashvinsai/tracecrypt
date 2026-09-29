# Merge record — TraceCrypt Unified 1.0

## Source inputs

Base: `crypto-attribution-full-20260927.zip`.
Secondary: `tracecrypt.zip`.
The separate `clm_investigation_router.zip` was compared with the full project's routing implementation. The integrated full-project router is retained rather than adding a competing second router. Original subset/audit archives are not application dependencies.

The full attribution backend, React source/dist, CCTP implementation, scripts, label-review policies and public/synthetic proof artifacts remain the base. The principal added modules are:

- `api/app/services/tracecrypt_intelligence.py`: safely reimplemented TraceCrypt-style pattern/profile/cross-case analysis.
- `api/app/routes/unified.py` and `models/unified.py`: integrated workspace API and case-scoped saved results.
- `api/app/adapters/receipt_gate.py`: pre-traversal execution/finality verification using the original real-provider verifiers.
- `workspace/`: a new static primary workspace; uses TraceCrypt's locally bundled vis-network distribution with its license header retained.
- `launch.py`, `manage.py`: explicit local initialization, operator/token setup and bounded foreground polling.
- `tests/test_unified_intelligence.py`, `tests/test_unified_api.py`: new regression and integration cases.

## Deliberately rejected behavior

The old TraceCrypt attribution engine's forwarding-ratio-to-100%-ownership conclusion is not part of this build. Neither its float haircut calculation nor any alternative invented victim-fund allocation is used. Invalid/review-misrepresented exchange registries, mock/live label mixing, synthetic chain-data fallbacks, pretend connected status and mock cross-chain destination matches were not imported.

Pattern flags produce referenced observations and explicit alternative explanations. They do not promote a wallet into an accepted service label. Shared address overlap does not become a campaign or common-owner confidence score. Routine reviewed exchange/protocol endpoints are excluded from cross-case leads.

The model router remains optional and shadow-only. It cannot change finality, execution, ownership, authorization, labels or case-fund allocation. Recorded upstream model metrics are not presented as newly run detection accuracy.

## Correctness and integration repairs

1. Successful execution and confirmed finality are both required before continuation, including the incident seed. Zero and negative-value transfers do not continue.
2. Real adapters verify receipts before the graph walk. Previously a validation workflow's post-trace check was too late to support a fail-closed walk. Removed inclusions are not upgraded from a different receipt.
3. Unverified execution/finality, repeated pagination cursors, incomplete terminal coverage and exhausted request budgets are explicit limitations, not clean empty history.
4. Provider request budgets are passed to live adapters; receipt-verification budget exhaustion no longer produces an unrelated dictionary lookup error.
5. API asset UUID strings are validated and converted before SQLAlchemy lookup. Unsupported or wrong-network assets are rejected.
6. New saved-case runs enforce process/case/asset data-mode agreement. Reopening/exporting a saved run checks its trace and intelligence digests.
7. Exports contain the original saved evidence plus derived intelligence, request metadata and hashes. CSV formula-like text is escaped, while authoritative JSON is unchanged. PDF tables wrap; wide provenance records are displayed vertically rather than clipped.
8. Same-origin checks protect browser mutations, and case responses are non-cacheable. These do not constitute a full production security certification.
9. Portable Base58 encoding/decoding preserves existing checksum validation; it does not relax address policy. Structured stdlib logging and an actual WeasyPrint PDF fallback allow a dependency-light local runtime without fake dependency stubs.

## What remains separate

The new workspace is a static client of the same backend, not a rewritten React build. The original `/investigator` console remains a non-production research surface, with its existing historical artifacts and specialized CCTP/model views. The merged primary workspace links to it. The frontend package was not rebuilt because package downloads were unavailable in the merge environment.

The workspace's CCTP view is a recorded-evidence view; the retained command-line CCTP acquisition/linking flow is the implementation. It is not silently executed as a universal cross-chain continuation inside every new case trace. Missing bridge support remains unresolved.

The original `ppt/`, historical handoff files and proof artifacts are retained as upstream material, not refreshed claims about this combined release. Start with the root README and `validation/TEST_RESULTS.md` for the present implementation.

## Data and operational limits

The network adapters, modes, accepted labels, evidence caveats and missing authorized integrations are described in the README. No fresh exchange-intelligence feed, current comprehensive deposit-address database, NCRP/SAHYOG credentials, cloud account, private key or GPU model weights are included. No transaction signing or actual freezing/submission was added.

Checksums are consistency checks, not independent authentication, cryptographic signatures or a substitute for a separately controlled evidence store. The single-worker polling command is not a distributed scheduler. PostgreSQL production concurrency and Windows installation were not executed during this merge.

## Provenance and distribution

`SOURCE_CHANGES.json` lists added and changed text/source paths against the full upload. `SOURCE_INPUTS.json` records input ZIP hashes. `PACKAGE_MANIFEST.json` records hashes of shipped files for download integrity; it is not a signing certificate.

No source/runtime `.env`, generated database, installed dependency folder, Python cache, Git metadata or standalone font file is shipped. The original public proof-of-reserves ZIP remains included because the original provenance tests use it. Keep API keys only in your local generated configuration.
