# PRD — Crypto Fraud Attribution Triage

Status: phase 00 contract. Version 0.1.0. Written 2026-09-19.

## 1. Problem

An investigator receives a complaint naming a crypto address or transaction.
They need to know, quickly and defensibly: where did the funds go, did they
reach a service that can be served legal process, and what part of that answer
is observation versus inference.

Public block explorers show transfers but not who controls an address. Commercial
attribution tools supply the missing labels but are licensed, opaque, and not
available to this project. This system is therefore built around an explicit,
inspectable, small label registry rather than around a pretence of complete
attribution coverage.

## 2. Two modes, distinguished at intake

### 2.1 Incident trace mode
Input:
- `network` (explicit; never inferred from address syntax)
- `address` (canonicalized, original input preserved)
- `transaction_hash` (optional but preferred)
- `transfer_event_reference` (required when the transaction holds several transfers)
- `asset` (network-scoped asset id or token contract; never a bare symbol)
- `amount_base_units` (integer, optional)
- `incident_time` and `time_window`
- `case_reference`

Output: a chronological, directed multigraph of observed transfers starting from
the seed event, terminating on each branch at a boundary with a recorded reason.

### 2.2 Address discovery mode
Input: `network` + `address` only.

Output: scoped activity leads. The system does not assert that any transfer in
this mode carries victim funds. Every finding carries
`case_flow_linkage = not_established`.

## 3. What a destination means

Supported tracing stops on a branch at the **first supported receiving custody
or service boundary**, per branch, in chronological order.

Endpoint classes, never collapsed into one another:

| Class | Meaning | Terminates branch? |
|---|---|---|
| `known_service` | Address has an accepted `service_control` label assertion with evidence, provenance, reviewer, and a validity interval covering the observation time | Yes |
| `deposit_candidate` | Behavioural features suggest a service deposit address; no accepted control assertion | No — shown, branch continues where evidence permits |
| `unresolved` | No label, budget remains | No |
| `boundary` | Hop/event/time/API budget exhausted, or unsupported asset change, bridge, privacy mechanism, opaque contract | Yes, with `boundary_reason` |

A candidate label may be displayed but must never silently terminate a branch as
verified.

## 4. Uncertainty is first-class output

Four independent axes. None is derived from another:

- `execution_status` — did the chain event succeed (`success`, `failed`, `reverted`, `unknown`)
- `coverage_status` — how complete is our observation (`complete_within_scope`, `partial`, `unknown`, `failed`)
- `attribution_status` — what we can say about ownership (`supported`, `inferred`, `candidate`, `conflicted`, `unresolved`, `unsupported`)
- `case_flow_linkage` — is this connected to the seed event (`established`, `partial`, `not_established`, `ambiguous`)

`complete_within_scope` means complete inside the declared network, asset, time
window, and budget. It never means complete knowledge of a blockchain.

## 5. Amount semantics

- Observed transfer amount is always shown, in base units, as an exact integer.
- Case-associated (victim-fund) estimate is a separate field, defaulting to
  `allocation_unknown`.
- An observed path establishes a sequence of transfers, not ownership of
  fungible units. 900 pre-existing + 100 victim in, 500 out, is ambiguous —
  not a 500 victim transfer.
- Estimates are never summed across reconvergent paths, never exceed the seed
  amount, and are never duplicated across branches.

## 6. Data modes

`LIVE`, `RECORDED_PUBLIC`, `SYNTHETIC`. The active mode appears in the UI header,
every API response envelope, every export, and every report. Synthetic fixtures
use deliberately fictional addresses and service names and are barred from the
production label database and from any live provider call.

## 7. Scope

**In scope (initial):** TRON mainnet; one issuer-verified TRC-20 USDT contract;
read-only observation; manual label registry with provenance; bounded forward
tracing; evidence export; draft (never submitted) request documents.

**Out of scope, stated as such in the product:** KYC identity discovery,
automatic or requested freezes, all-chain coverage, universal mixer/privacy-tool
tracing, approved NCRP/SAHYOG connectivity, recovery outcomes, criminal
attribution to a named person.

## 8. Budgets

Configurable, and **targets, not measured performance**. Nothing in this
repository has been benchmarked yet.

| Budget | Proposed default | Notes |
|---|---|---|
| Max hops | 8 | per branch |
| Max transfer events examined | 5,000 | per run |
| Max provider requests | 400 | per run, shared org-wide budget on top |
| First partial result | 30 s | target to test in phase 16, not a guarantee |
| Wall clock per run | 300 s | hard cancel, with accounting |

Exhaustion is reported explicitly as `boundary_reason`, never as a completed trace.

## 9. Non-goals restated for report copy
The product must not display: fabricated confidence percentages, accuracy rates,
recovery rates, national coverage claims, or a count of cases solved.
