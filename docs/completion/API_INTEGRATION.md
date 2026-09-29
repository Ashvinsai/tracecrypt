# Application-owned complaint intake API

This is **not** an official NCRP, SAHYOG or VASP API specification. It is the receiving contract an authorized integration service can call after performing its own approved mapping. Do not use scraped credentials, assume an official endpoint, or embed victim secrets in this payload.

## Credential administration

Prepare the database and create an operator/organization first. In local SYNTHETIC setup the organization slug is `demo-cyber-cell` (confirm in the seeded output). On the server host an authorized administrator can issue a token:

```bash
python gateway_admin.py issue --organization-slug demo-cyber-cell --name "Local demonstration gateway" --source agency_gateway --days 30
python gateway_admin.py list --organization-slug demo-cyber-cell
python gateway_admin.py revoke --id CREDENTIAL_UUID
```

The one-time `tcu_...` token is printed only on issue. Only its SHA-256 digest is stored. Protect it in the gateway secret manager; it grants complaint ingestion into one organization/source and expires after the configured 1–90 days. Issuance and revocation create audit rows. These commands require administrative access to the application host; they are not a remote self-service enrollment flow.

Allowed source tags are `agency_gateway`, `ncrp_gateway`, `sahyog_gateway`, and `vasp_gateway`. Tags express your local mapping intent, not successful official onboarding. The sender cannot choose another organization or source in the request body.

## Submit

```http
POST /api/v1/integrations/complaints
Authorization: Bearer YOUR_ONE_TIME_TOKEN
Content-Type: application/json
```

Use `examples/complaint.synthetic.json` for the prepared SYNTHETIC environment. `schemas/complaint-intake-v1.schema.json` is generated from the actual Pydantic model. Unknown fields are rejected; the payload is limited to 64 KiB. Keep victim names, documents, bank credentials and private keys in the authorized source system, not in this contract.

```json
{
  "schema_version": "1.0",
  "external_reference": "SYNTHETIC-GATEWAY-001",
  "title": "Synthetic automated investigation",
  "allegation_type": "investment_scam",
  "incident_start": "2026-08-01T00:00:00Z",
  "analysis_cutoff": "2027-01-01T00:00:00Z",
  "wallets": [{
    "network_key": "tron",
    "address": "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM",
    "token_contract": "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
    "seed_event_reference": "tron:tx_seed_multi:0"
  }]
}
```

The fixture is deliberately fictional. LIVE refuses a future analysis cutoff. A missing cutoff is fixed at intake time, so queue delay does not silently expand the analysis window. Time values require timezones. An empty token selection expands only to explicitly supported, same-mode registered tokens. A seed event requires one exact selected asset. Without an incident seed, the run is address discovery and makes no victim-fund allocation claim.

HTTP 202 returns the persistent case and queued job IDs, not a completed trace. A repeated organization/source/reference with identical submitted content returns the same receipt and `duplicate=true`; changed content under that reference returns 409. Incorrect addresses, unsupported networks/tokens or schema errors return 422; invalid/expired credentials return 401; oversize bodies return 413; queue backpressure returns 429. The quota is a best-effort local bound, not a serialized multi-writer tenant quota.

An example standard-library sender is supplied:

```bash
# Set TRACECRYPT_INTAKE_TOKEN securely in the process environment first.
python examples/submit_complaint.py --base-url http://127.0.0.1:8010 --file examples/complaint.synthetic.json
```

Start `python launch.py --with-worker` or a separate single `operations_worker.py` to execute queued work. The gateway bearer is intentionally intake-only; investigator result access requires an authorized session, not this token. A future authorized agency callback/retrieval interface is a separate integration task.

## Investigator endpoints (session required)

| Route | Purpose |
|---|---|
| `POST /api/v1/operations/intakes` | Same contract through the current organization's session. |
| `GET /api/v1/operations/jobs` | Recent jobs, status filter, truncation flag. |
| `GET /api/v1/operations/jobs/{id}` | Authorized job, outcome or recorded failure. |
| `POST /api/v1/operations/jobs/{id}/retry` | Requeue failed/blocked work after configuration correction, with an audit event. |
| `POST /api/v1/operations/jobs/{id}/cancel` | Cancel queued/retry/running work and fence late worker saves; evidence is not deleted. |
| `GET /api/v1/operations/overview` | Actual job counts/durations, indexed observations and connector limitations. |
| `GET /api/v1/operations/events?after=0&limit=100` | Cursor-paginated, hash-checked event observations; address filtering also requires a network. |
| `GET /api/v1/operations/signals?after=0` | Forward-cursor signals; `latest=true` is a recent snapshot, not full chronological paging. |
| `POST /api/v1/operations/signals/{id}/acknowledge` | Record investigator review. |
| `GET /api/v1/operations/audit` | Authorized local audit records. |
| `GET /api/v1/cases/{case}/investigations/{run}/attribution` | Evidence-qualified nearest receiving VASPs and unresolved boundaries. |
| `GET /api/v1/cases/{case}/investigations/{run}/export` | Saved evidence ZIP, no fresh trace. |
| `GET /api/v1/operations/ml-ranking?network_key=tron&token_contract=...` | Optional bounded held-out anomaly ranking for the authorized organization. |
| `POST /api/v1/cases/{case}/cross-chain/cctp` | LIVE checked CCTP acquisition for a supplied Ethereum transaction. |
| `GET /api/v1/cases/{case}/cross-chain/{review}/evidence` | Checksum-verified source/destination evidence bundle. |
| `POST /api/v1/cases/{case}/cross-chain/{review}/continue` | Idempotent recipient address-discovery job after a successful checked link. |

Use the generated OpenAPI contract for exact query names and request schemas. `POST /operations/process-next` is a local dev/test convenience; it is disabled in production. Production should use the worker, TLS, trusted proxy configuration, actual access-control review and a separately validated database deployment.
