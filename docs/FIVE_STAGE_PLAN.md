# Five-stage build: crypto fraud attribution

Prepared 19 September 2026. This is a revised planning/prompt file, not an implemented application or an executed test suite. It replaces the build order in the earlier 20-phase playbook; that playbook remains a reference for correctness and later production work.

## Product and scope

Build a local, read-only TRON investigation prototype first. The first deliverable is one real, correctly interpreted transfer path to a sourced service label, with JSON and a basic printable evidence report. A public-chain example is not automatically a fraud case. Recorded or synthetic data must be visibly identified.

Proposed effort allocation: stage 1 15%; stage 2 35%; stage 3 20%; stage 4 20%; stage 5 10%. These are planning allocations, not completion-time promises. Begin data collection and evaluation logging immediately; stage 5 freezes and publishes the evaluation rather than starting it. Start the frontend against the stage-1 result contract while label research continues.

Default stack: Python, FastAPI, SQLite, local raw-response files, one simple frontend. Reuse a team's existing working database or frontend instead of rebuilding it to match these defaults. Add a queue, Redis, graph database, and production infrastructure only when a measured need arises. Keep the prototype local, use public/fictional case information, and never commit secrets. Authentication and case authorization are required before external exposure or real complaint use.

## Instructions for every coding session

Read the repository and this file. Implement one stage or a small part of it, not the whole platform. Preserve existing tests. Verify external interfaces using current official documentation. Do not invent endpoints, labels, measurements, or institutional access. Do not replace a failing test with an assertion matching incorrect behavior.

End each session with changed files, actual commands executed and results, missing dependencies/evidence, and a suggested commit message. Explicitly distinguish implementation, recorded demonstrations, mocks, and unexecuted tests. The commands and filenames below are proposed interfaces for you to implement, not files already supplied by this document.

## Day-one correctness tests

Implement these as small executable tests as the relevant code lands. Do not hold the initial local demo behind a complete production test suite.

1. An outgoing event before the investigated receipt cannot continue its path.
2. A later receipt at an already encountered address is not discarded by a global visited-address set.
3. Separate transfer events in one transaction retain separate identities.
4. Network and asset contract are part of identity; a ticker alone is insufficient.
5. Integer base units survive serialization exactly; serialize large amounts as strings for JavaScript.
6. Approvals and failed transfers do not become successful fund-flow edges.
7. Pagination is consumed and duplicates removed without merging distinct events.
8. Mixed balances do not turn the full later outgoing amount into victim-associated value; reconverging paths do not duplicate value.
9. Unhandled bridge, mixer, and custody boundaries do not gain invented continuation edges.
10. A shared energy-rental sponsor alone does not merge unrelated wallets or identify an exchange.
11. Missing history or provider failure returns partial/unknown evidence, not a false successful empty result.
12. Current delegation state does not establish historical delegation timing.

# Stage 1 — One real end-to-end result

## Human preparation

Supply one independently sourced TRON service anchor, its source, disclosure date and supported role. Pick a public transfer example that reaches it. The example is for tracing, not an allegation. Record whether the example is direct or multi-hop. A known input is acceptable; a hardcoded trace result is not.

## Copy-paste coding prompt

Implement a thin local vertical slice using the project's existing stack, or Python/FastAPI/SQLite if starting empty.

Accept network, address, verified token contract, and optional incident transaction/event plus time window. Implement an actual TRON acquisition adapter, normalized transfer events, bounded chronological forward exploration, a CSV label lookup, and a result object. Use configured network hosts deliberately: official documentation examples may target a testnet.

Fetch relevant history with pagination, exact base-unit amounts, execution/confirmation checks, and receipt enrichment where necessary for event identity or ordering. Keep per-receipt/event state. When detailed ordering is unavailable, do not invent it.

Load the supplied sourced anchor from a data file. Do not embed a particular address-to-answer branch in the algorithm. Store raw responses and acquisition metadata. Clearly distinguish live, recorded, and synthetic modes. The live input need not be a scam address.

Produce a CLI or POST /trace response and a plain HTML evidence view printable to PDF. Reuse the same result object for the eventual frontend and report. Include observed path, identified service and evidence source, unresolved branches, searched limits, and data timestamps. Default mixed-fund case allocation to unknown.

Implement the applicable day-one tests. Keep the service local, protect API keys, and add a single command to run tests. Do not build enterprise auth, orchestration, general indexing, an LLM agent, or a complex dashboard before this works.

Gate: changing to another supplied example exercises the same parser and tracer; an investigator can inspect an actual transaction path and its service-label source. A live one-hop demonstration establishes the vertical slice, not general attribution coverage.

# Stage 2 — Label acquisition and TRON-specific evidence

## Human acquisition procedure

A. Obtain anchors from primary disclosures. OKX publishes proof-of-reserves wallet files and address-verification tools. Download a dated disclosure, select records explicitly on the intended network, preserve the original file and its hash, and verify signed ownership where supported. Distinguish exchange-controlled assets from third-party custody. A reserve disclosure supports a dated claim; it does not automatically identify a hot wallet or customer deposit address. Inspect activity before choosing a collection anchor.

B. Use public attribution collections such as GraphSense TagPacks as sourced leads. Follow the original source and inspect permitted reuse. Two aggregators copying one source are not independent corroboration. Never import unsupported strings as verified ownership.

C. For each active anchor H, inspect a capped, recorded time window of incoming genuine-token transfers. Candidate D addresses are senders to H, not automatically exchange deposits. Select a manageable sample before looking at outcomes and record selection bias and truncation. Retrieve D's relevant histories and native-resource evidence.

D. Preserve three distinct relationships: D transfers tokens to H; a delegator R lends resources to D; a funder F transfers TRX to D. Resource delegation is not a token payment or proof of shared ownership. Independently investigate R and F; exchange withdrawals, public energy services, and shared providers can create misleading overlap.

E. Query resource indices/state for discovery. Historical timing requires successful historical delegation/undelegation transactions or correctly decoded supported protocol records. Current state is not complete history. Annotate native/internal/protocol coverage explicitly and do not infer past absence from an empty current response.

F. Collect independent evaluation evidence. Authorized observations of an existing team member's exchange-issued deposit address can verify assignment without sharing credentials or requiring a transfer. Existing authorized deposit records are better behavioral controls where available. Include independently established self-custody users, frequent exchange customers, payment services, and energy-rental recipients as confounders. Do not label every unlabeled address a negative. No transactions to suspicious wallets are required.

## Copy-paste coding prompt

Build import_anchors, collect_candidates, collect_resource_evidence, extract_features, and review_candidates interfaces. They may be CLI commands or small scripts.

Keep verified_anchors, deposit_candidates, and independent_review separate. Every claim must have network, address, entity, role, source, valid-as-of information, last-checked timestamp, evidence identifiers, and status. Store underlying responses.

For candidates, calculate observed token-forwarding concentration, repeated forwarding count, receipt-to-outflow timing features, post-outflow residue where supportable, resource-sponsor identity/role and history, and TRX-funding corroboration. Make incomplete observation windows explicit. Timing features are behavioral summaries, not proof that particular token units moved.

Integrate read-only delegation index/state queries. Obtain historical operations separately where available; do not call transaction-creation or broadcast methods. Explain when only current state is available.

Allow candidate labels and ranked leads to be returned. Prevent candidate-to-trusted promotion based solely on repeated sweeps, a shared sponsor, or a repeated rule. No unrestricted transitive merging. Independently supported operational links may contribute to a documented strong-inference policy; record conflicts and limitations.

Create a feature comparison report: anchor-only, chronological tracing, sweep rules, and sweep plus resource evidence. Do not invent precision when independent ground truth is unavailable.

Gate: the team can open the exact source behind each anchor and the exact events behind each candidate. At least some unseeded inputs are tested; whether they resolve is recorded rather than guaranteed. Missing useful anchors is a project risk to resolve before adding chains.

# Stage 3 — Useful inference and a modest real ML component

## Copy-paste coding prompt

Implement four service-outcome categories: supported destination, strong inference, candidate lead, and unknown/blocked. Keep data completeness and case-value uncertainty as separate fields.

A path reaching a sourced service anchor can report that observed destination even when an earlier intermediary's ownership is unknown. Do not infer that the reported wallet belongs to the destination service. Strong inference requires an explicit multi-evidence policy and must remain identified as inference. Return plausible named leads with reasons rather than suppressing everything without direct ownership proof. Do not turn bands into percentage probabilities without empirical calibration.

Keep mixed-balance allocation unknown by default. Any optional range/estimate must name its assumptions, use complete-enough history, and avoid duplicated value across branches. Implement explicit custody/protocol boundaries with preserved entry evidence.

In parallel, implement a small Isolation Forest module for behavioral anomaly ranking, not service identification or fraud probability. Use reproducibly collected wallet-window observations from the supported network/asset. Features may include transaction burstiness, distinct counterparty counts, outgoing concentration, and observed timing/turnover measures. Exclude addresses, case IDs, complaint status, and future information. Treat missing features as missing data, not automatically suspicious behavior.

Implement extract_features, train_anomaly, and evaluate_anomaly. Save feature definitions, sample-selection method, seed, model version, training cutoff, and holdout split. Split by wallet/related group and time to avoid near-duplicate windows across training and evaluation. Do not fit and evaluate on the same rows. Synthetic-only evaluation must be labelled a pipeline demonstration.

Show anomaly ranking separately from attribution evidence. Display feature observations rather than claiming they are a faithful explanation of a model without implementing an explanation method. Evaluate review-worthy precision@k under a predeclared analyst rubric against a random-ranking baseline and known operational confounders. This does not measure criminal guilt. Do not relabel a rules-only system as trained ML.

Gate: the model actually fits and scores saved data, the module has a held-out comparison, and disabling it does not change observed transfer evidence or service labels. Limited evidence means experimental ML, not fabricated validation.

# Stage 4 — Investigator workflow, monitoring, and export

## Copy-paste coding prompt

Use the stage-1 result contract to build a single useful console. Show input, a chronological transfer table and optional graph, service outcome, label provenance, resource corroboration, unresolved branches, amount uncertainty, acquisition time, and confirmation state. Keep observed token transfers, resource delegations, and inferred control relationships visually distinct.

Add checkpointed new-event monitoring for supported token transfers, with deduplication, restart recovery, and measured observation lag. Do not claim a public mempool feed unless such a source is actually implemented and verified.

Upgrade the first plain report to a PDF plus CSV/JSON evidence package. Include exact network/asset/event identifiers, sources, analysis scope, versions, limitations, and file integrity hashes. A checksum establishes file consistency, not truth of attribution.

Generate distinct information/preservation/asset-restriction request drafts marked DRAFT / INVESTIGATOR REVIEW REQUIRED. Use a verified provider guide as a field checklist; do not fabricate legal authority or signatures. No automatic external sending. Do not request a blanket freeze of a pooled exchange wallet.

Provide a clearly marked mock complaint adapter only. Do not invent NCRP/SAHYOG APIs or claim approved connectivity. Require appropriate authentication/authorization before exposure beyond local public-data use.

Gate: one input produces an inspectable finding, one supported new event produces one alert, and the export agrees with the screen. Recorded fallback and simulated connector modes remain visibly labelled.

# Stage 5 — Publish evidence of value, then consider expansion

## Copy-paste coding prompt

Freeze the code, labels, thresholds, and evaluation inputs. Run reproducible comparisons for:
A. direct-anchor lookup;
B. A plus chronological tracing;
C. B plus sweep inference;
D. C plus resource evidence.

Use an independently checked holdout for service and address-role claims. Discovery labels are not evaluation truth. Report denominators and separate seeded cases, independently sourced cases, reviewer-unverified outputs, and synthetic tests. Report supported coverage and strong-inference/lead coverage separately. Use the same decisions and data for comparable methods and document different source availability.

Measure per-band precision where verification exists, resolution coverage, false attributions, temporal-path failures, cold/warm latency, observation lag, API usage, and incomplete outcomes. Report model review-prioritization results separately. Do not tune thresholds after inspecting final holdout outcomes.

Create a demonstration with a supported result, an inference with visible supporting evidence, a confounder or unsupported boundary, a live/recorded alert, and a draft report. Never invent an exchange name to make an unseen address succeed.

Only add a second chain after useful labels, core correctness, the report, and evaluation are stable. Multi-chain query support is not cross-chain linkage. Unimplemented requirements belong in a coverage matrix, not in the completed-features list.

Gate: another teammate can reproduce the results, every pitch metric has an actual run behind it, and no national fraud-share or recovery claim is inferred from a convenience sample.

## Kill list for the first demo

Do not prioritize a full-chain index, elaborate roles, microservices, Kubernetes, a general bridge decoder, automatic legal submission, broad Bitcoin support, a GNN, or decorative dashboards over a sourced attribution result. Do not remove correctness, provenance, secret handling, or visible uncertainty to save effort.

## Primary references checked for this revision

These document available mechanisms and workflows; they do not prove the proposed attribution heuristic's accuracy. Verify current access, network, and API terms when implementing.

- TRON delegation model: https://developers.tron.network/docs/delegation
- Delegation account index: https://developers.tron.network/reference/getdelegatedresourceaccountindexv2-1
- Solidified delegation state: https://developers.tron.network/reference/getdelegatedresourcev2-1
- TRON token history: https://developers.tron.network/reference/get-trc20-transaction-info-by-account-address
- TRON receipt information: https://developers.tron.network/reference/gettransactioninfobyid
- TRON event access: https://developers.tron.network/docs/event-subscription
- JustLend energy marketplace: https://docs.justlend.org/getting_started/concepts/energy_rental/
- OKX ownership disclosure and verification: https://www.okx.com/proof-of-reserves
- OKX download page: https://www.okx.com/proof-of-reserves/download
- GraphSense sourced TagPacks: https://github.com/graphsense/graphsense-tagpacks
- Isolation Forest implementation: https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html
- Example exchange request requirements: https://www.okx.com/help/okx-law-enforcement-request-guide

No live wallet sample was collected and no real-world heuristic or model accuracy was measured in preparing this plan. The earlier ZIP was inspected: it contains 20 prompts, 40 acceptance-test specifications, and 10 synthetic fixture cases. Those specifications are not executable tests.
