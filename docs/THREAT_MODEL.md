# Threat model

Scope: the prototype as built, plus the risks that must be closed before any
real complaint data touches it. Phase 15 extends and tests this.

## Assets worth protecting
1. Complaint PII and victim identity.
2. Private investigative labels (attribution work product).
3. Case-derived analysis and exports.
4. Provider credentials and session secrets.
5. The integrity of the evidence record itself.

## Trust boundaries
- Browser ↔ API (authenticated session, org-scoped).
- API ↔ worker (shared DB/queue, same trust domain, separate identity).
- System ↔ blockchain data providers (untrusted input).
- System ↔ imported label sources (untrusted input).
- System ↔ complaint text and token metadata (untrusted input, never instructions).

## Threats and controls

| ID | Threat | Impact | Control | Phase | State |
|---|---|---|---|---|---|
| T1 | Case-ID guessing / IDOR across orgs | PII and case leak | Server-side org scope on every route, job, stream, export; deny-by-default dependency | 01, 15 | implemented, tested |
| T2 | Label poisoning via import | False attribution of an innocent party | Review state machine, quarantine, provenance required, candidates never auto-promoted | 04 | model in place |
| T3 | Provider returns error and we store it as "no activity" | Silent false negative — looks like clean address | Acquisition records carry `status` and `coverage_status`; error ≠ empty history; enforced in adapter contract tests | 03 | contract defined |
| T4 | Token spoofing (fake USDT contract) | Wrong asset traced | Asset identity is `(network, token_contract)`; symbol is display only; issuer-verified config | 02, 03 | enforced in model |
| T5 | Float arithmetic on amounts | Wrong amounts in a legal document | Integer base units end to end; `Numeric(78,0)`; string in JSON; no JS `Number` | 02 | enforced + tested |
| T6 | Same tx hash used as event identity | Deduplicated away a real transfer | `event_reference` is chain-specific `(tx, event index)`; unique constraint | 02 | enforced + tested |
| T7 | Reorg / removed event reported as settled | False evidence | Block inclusion history table + `confirmation_state`; removal propagates | 02, 09 | model in place |
| T8 | Prompt injection via complaint text or token name | Exfiltration or fabricated findings | Untrusted-data rule; LLM sees only approved structured findings; output validated against evidence IDs | 14, 15 | rule recorded |
| T9 | CSV formula injection in exports | Code execution on reviewer's machine | Neutralise leading `= + - @ TAB CR` in CSV cells | 10, 15 | not started |
| T10 | SSRF via provenance URL fetch / webhooks | Internal network access | Allowlist external destinations; no arbitrary fetch | 15 | not started |
| T11 | Secrets in logs | Credential loss | Structured logging with redaction; secret scan in CI | 01, 15 | partial |
| T12 | Quota exhaustion (self-inflicted DoS of provider) | Analysis stops mid-case | Global provider budget shared by traces and watches | 07, 09 | not started |
| T13 | Synthetic fixtures leaking into production labels | Fictional exchange in a real report | Fixture addresses live in a separate `data_mode`; live providers reject synthetic mode | 02 | implemented, tested |
| T14 | Report generation treated as submission | Unauthorised contact with a VASP or agency | Drafts marked DRAFT / REVIEW REQUIRED; no send path exists | 10, 11 | no send path exists |

## Accepted risks for the prototype
- Single-node deployment, no HA. Local demo only.
- Evidence snapshots hashed but not stored in WORM storage. A hash chain is not
  tamper-proof storage and is not a claim of admissibility.
- No penetration test performed.

These block real-data deployment and are listed as such in `docs/PRD.md` §7.
