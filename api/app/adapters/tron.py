"""TronGrid adapter for TRC-20 transfer history.

Endpoints used, and what each is actually documented to return:

``GET /v1/accounts/{address}/transactions/trc20``
    Paginated TRC-20 history. Documented item fields: ``transaction_id``,
    ``block_timestamp``, ``from``, ``to``, ``type``, ``value``, and
    ``token_info{symbol,address,decimals,name}``. Pagination cursor is
    ``meta.fingerprint``. **It carries no event index and no execution status.**

``GET /v1/transactions/{transactionID}/events``
    Documented to include ``event_index`` -- "the event's index within the
    transaction's event log" -- plus ``contract_address``, ``event_name``,
    ``block_number``, ``block_timestamp`` and ``result``.

Because the history endpoint omits event identity, a transaction carrying more
than one transfer cannot be split apart from that endpoint alone. This adapter
therefore enriches from the events endpoint. When enrichment is unavailable the
event is stored with ``ordering_ambiguous=True`` and a content-derived
reference; an index is never invented (D005).

Execution status is reported as ``unknown`` from the history endpoint, because
that endpoint does not document one. ``fetch_receipt`` turns that fallback into
an answer:

``POST /walletsolidity/gettransactioninfobyid`` and
``POST /wallet/gettransactioninfobyid``
    Both take ``{"value": txid}``. Documented response fields: ``id``, ``fee``,
    ``blockNumber``, ``blockTimeStamp``, ``contractResult``, and ``receipt``
    (``net_fee`` in the published schema; the prose also describes
    ``energy_usage``, ``energy_fee`` and ``result``). The solidified path
    returns receipts for solidified transactions only, so an answer there is
    final and an empty answer there is not a failure — it means "not yet".
    Both document that an exception can arrive as HTTP 200 carrying only an
    ``Error`` field, which this adapter treats as a provider error rather than
    an empty receipt.

Execution and finality stay separate: a successful execution in an unsolidified
block is ``success`` + ``provisional``, never ``confirmed``.

Stage 2C2 (collect_resource_evidence) adds two more, both read-only:

``GET /v1/accounts/{address}/transactions``
    General account transaction history -- not TRC-20-specific. Documented
    parameters match the TRC-20 endpoint: ``min_timestamp``/``max_timestamp``,
    ``only_confirmed``, ``only_to``/``only_from``, ``limit``, ``fingerprint``,
    ``order_by``. Each item documents ``txID``, ``block_timestamp``,
    ``blockNumber``, ``ret[].contractRet``, and ``raw_data`` (whose
    ``contract[]`` entries carry ``type`` and ``parameter.value`` -- for a
    native TRX transfer, ``TransferContract`` with ``owner_address``,
    ``to_address``, ``amount``; for Stake 2.0 delegation,
    ``DelegateResourceContract``/``UnDelegateResourceContract`` with
    ``owner_address``, ``receiver_address``, ``balance``, ``resource``,
    ``lock``). This is the only source of a genuinely historical, timestamped
    delegation or TRX-funding record this adapter uses; a transaction found
    here carries its own real ``block_timestamp`` (D checks: temporal_status
    the same way a real observation always does).

``POST /wallet/getdelegatedresourceaccountindexv2``
    ``{"value": address, "visible": true}`` -> ``{"account", "fromAccounts",
    "toAccounts"}``. A pure current-state index: which addresses currently
    have a Stake 2.0 delegation relationship with this one, in either
    direction. No timestamp, no history -- it cannot support a claim about
    when a relationship began, only that it exists now.

``POST /wallet/getdelegatedresourcev2``
    ``{"fromAddress", "toAddress", "visible": true}`` -> per-resource-type
    delegation detail (``delegatedResource[].balance``, ``.resource``, and
    ``expire_time_for_*``, when a lock is set). Also current-state only:
    ``expire_time_for_*`` is a lock *expiry*, never a delegation *start* time.

Sources checked 2026-09-20:
  https://developers.tron.network/reference/get-trc20-transaction-info-by-account-address
  https://developers.tron.network/reference/get-events-by-transaction-id
  https://developers.tron.network/reference/gettransactioninfobyid
  https://developers.tron.network/reference/get-transaction-info-by-account-address
  https://developers.tron.network/reference/getdelegatedresourceaccountindexv2-1
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from app.adapters.base import (
    AcquisitionRecord,
    AssetRef,
    ChainAdapter,
    Direction,
    ExecutionReceipt,
    ExecutionVerification,
    NormalizedTransfer,
    ProviderError,
    ProviderErrorClass,
    Reconciliation,
    TransferPage,
    Unverified,
)
from app.core.settings import DataMode
from app.models.enums import (
    AcquisitionStatus,
    ConfirmationState,
    CoverageStatus,
    EventKind,
    ExecutionStatus,
)
from app.services.addresses import AddressValidationError, CanonicalAddress, canonicalize_tron

PARSER_VERSION = "tron-0.1.0"

SOLIDIFIED_RECEIPT_PATH = "/walletsolidity/gettransactioninfobyid"
HEAD_RECEIPT_PATH = "/wallet/gettransactioninfobyid"

#: ``receipt.result`` values this adapter recognises. The published schema does
#: not enumerate them, so anything else is treated as a failed execution with the
#: raw value preserved: reading an unrecognised status as success would create a
#: fund-flow edge out of a contract that did not transfer anything (D005, test 6).
RECEIPT_SUCCESS = "SUCCESS"
RECEIPT_REVERT = "REVERT"

GENERAL_TRANSACTIONS_PATH = "/v1/accounts/{address}/transactions"
DELEGATION_INDEX_PATH = "/wallet/getdelegatedresourceaccountindexv2"
DELEGATED_RESOURCE_PATH = "/wallet/getdelegatedresourcev2"

#: raw_data.contract[] type values this adapter recognises for resource
#: evidence. Anything else is skipped, not guessed at (D005's principle
#: applied to contract types: an unrecognised type is not assumed harmless).
DELEGATE_CONTRACT_TYPES = frozenset({"DelegateResourceContract", "UnDelegateResourceContract"})
TRX_TRANSFER_CONTRACT_TYPE = "TransferContract"

#: TRC-20 history ``type`` values, mapped to our event kinds. An unrecognised
#: value becomes ``unknown`` rather than being assumed to move value.
TYPE_TO_EVENT_KIND = {
    "Transfer": EventKind.transfer,
    "Approval": EventKind.approval,
}


@dataclass(frozen=True)
class GeneralTransaction:
    """One transaction from an account's general history, not decoded past
    its contract type and raw parameter values -- callers interpret the
    fields relevant to the relationship they are looking for (resource
    delegation, native TRX transfer, or anything else)."""

    tx_id: str
    block_number: int | None
    block_time: dt.datetime | None
    contract_type: str
    #: raw_data.contract[0].parameter.value, verbatim -- e.g. owner_address,
    #: to_address/receiver_address, amount/balance, resource, lock.
    contract_value: dict[str, Any]
    execution_result: str | None


@dataclass(frozen=True)
class GeneralTransactionPage:
    transactions: list[GeneralTransaction] = field(default_factory=list)
    next_cursor: str | None = None


@dataclass(frozen=True)
class DelegationIndex:
    """Current-state only (getdelegatedresourceaccountindexv2): who has a
    Stake 2.0 delegation relationship with this account right now, in either
    direction. No timestamp is returned or invented here."""

    account: str
    from_accounts: list[str]  # currently delegate resources TO this account
    to_accounts: list[str]  # this account currently delegates resources TO


@dataclass(frozen=True)
class DelegatedResourceDetail:
    """Current-state only (getdelegatedresourcev2): one from/to pair's
    resource detail. ``expire_time`` is a lock *expiry*, never a delegation
    *start* time -- it is not evidence of when the relationship began."""

    from_address: str
    to_address: str
    resource: str | None
    balance_sun: int | None
    expire_time: dt.datetime | None


def _to_datetime(millis: Any) -> dt.datetime | None:
    if millis is None:
        return None
    return dt.datetime.fromtimestamp(int(millis) / 1000, tz=dt.UTC)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _reject_error_body(body: dict[str, Any], path: str) -> None:
    """TRON documents that an exception can arrive as HTTP 200 plus ``Error``."""
    error = body.get("Error")
    if error:
        raise ProviderError(ProviderErrorClass.provider_error, f"{path}: {error}")


def _classify_receipt_result(raw: str | None) -> ExecutionStatus:
    if raw is None:
        return ExecutionStatus.unknown
    if raw == RECEIPT_SUCCESS:
        return ExecutionStatus.success
    if raw == RECEIPT_REVERT:
        return ExecutionStatus.reverted
    # Not enumerated in the published schema. Whatever it is, it is not success.
    return ExecutionStatus.failed


def _canonical_tron_address(value: Any, *, lower: bool = True) -> str | None:
    """Normalize a TRON address field to base58check, or ``None``.

    The TRC-20 history endpoint (``/v1/accounts/.../transactions/trc20``)
    returns participants in base58check. The events endpoint
    (``/v1/transactions/{id}/events``) documents a ``result`` field but not
    its address encoding, and in practice returns the SAME addresses as
    20-byte hex with no ``0x41`` TRON prefix and no ``0x`` prefix either. A
    raw string comparison between the two never matches; both are routed
    through this before comparing (D002 -- canonicalize before comparing
    across encodings, never guess by trusting one source's format).

    ``lower=True`` (the default) is for building case-insensitive comparison
    *keys*, matching every existing call site. Pass ``lower=False`` to get a
    real, correctly-cased address for actual display or storage -- base58 is
    case-sensitive, and lowercasing one would silently corrupt it.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    hex_part = text[2:] if text.lower().startswith("0x") else text
    if len(hex_part) == 40 and all(c in "0123456789abcdefABCDEF" for c in hex_part):
        text = f"0x41{hex_part}"
    try:
        canonical = canonicalize_tron(text).canonical
    except AddressValidationError:
        return None
    return canonical.lower() if lower else canonical


def reconcile_event(
    transfer: NormalizedTransfer, event_rows: list[dict[str, Any]], asset: AssetRef
) -> Reconciliation:
    """Does the transaction's event detail describe this transfer?

    Checks the asset contract, both participants and the exact base-unit amount.
    A near miss is not a match: two transfers in one transaction can differ only
    in amount, and treating them as one would merge distinct events.
    """
    usable = [
        row for row in event_rows if isinstance(row, dict) and row.get("event_name") == "Transfer"
    ]
    if not usable:
        return Reconciliation(
            transfer.event_reference, False, "no event detail available to reconcile against"
        )

    expected_from = _canonical_tron_address(transfer.from_address)
    expected_to = _canonical_tron_address(transfer.to_address)
    for row in usable:
        contract = row.get("contract_address")
        if asset.token_contract and contract != asset.token_contract:
            continue
        result = row.get("result")
        if not isinstance(result, dict):
            continue
        lowered = {str(k).lower().lstrip("_"): v for k, v in result.items()}
        if _canonical_tron_address(lowered.get("from")) != expected_from:
            continue
        if _canonical_tron_address(lowered.get("to")) != expected_to:
            continue
        if str(lowered.get("value")) != str(transfer.amount_base_units):
            continue
        return Reconciliation(
            transfer.event_reference, True, "contract, participants and amount agree"
        )

    return Reconciliation(
        transfer.event_reference,
        False,
        "no matching event: contract, participants or amount differ from the receipt detail",
    )


def _classify(status_code: int) -> ProviderErrorClass:
    if status_code in (401, 403):
        return ProviderErrorClass.authentication
    if status_code == 429:
        return ProviderErrorClass.rate_limit
    if status_code == 402:
        return ProviderErrorClass.quota
    return ProviderErrorClass.http_error


class TronGridAdapter(ChainAdapter):
    """Live TRON adapter. Refuses to run in SYNTHETIC mode (D009)."""

    network_key = "tron"
    supported_data_modes = frozenset({DataMode.LIVE, DataMode.RECORDED_PUBLIC})

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
        enrich_events: bool = True,
        max_retries: int = 3,
        max_requests: int | None = None,
        recorder: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client
        self.enrich_events = enrich_events
        self.max_retries = max_retries
        #: Caps genuine network requests across this adapter's whole lifetime --
        #: seed lookup, enrichment, receipts, pagination, the tracer's own
        #: acquisition, everything that reaches ``_get``/``_post``. A replayed
        #: (cached) exchange never reaches here at all, so it is never counted
        #: or budget-checked (C).
        self.max_requests = max_requests
        #: Called with every provider exchange, for the live-validation bundle.
        self.recorder = recorder
        #: Counts every provider request, so a caller can enforce a budget.
        self.request_count = 0

    # -- plumbing ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if self._api_key:
            headers["TRON-PRO-API-KEY"] = self._api_key
        return headers

    def _check_budget(self, path: str) -> None:
        """Refuse to issue another request once the authorized count is spent.

        Checked before anything else in ``_get``/``_post`` -- before the
        request is sent, before it is counted, before a client is opened -- so
        an exhausted budget never becomes an (n+1)th request (C). Applies only
        to genuine network calls: a replay client (``self._client is not
        None``) answers from a saved bundle, is not a network request, and is
        not budget-limited.
        """
        if self._client is not None or self.max_requests is None:
            return
        if self.request_count >= self.max_requests:
            raise ProviderError(
                ProviderErrorClass.budget_exhausted,
                f"request budget of {self.max_requests} exhausted before {path} "
                f"({self.request_count} requests already issued)",
            )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._check_budget(path)
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            self.request_count += 1
            try:
                response = await client.get(
                    f"{self.base_url}{path}", params=params, headers=self._headers()
                )
            except httpx.TimeoutException as exc:
                raise ProviderError(ProviderErrorClass.timeout, str(exc)) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(ProviderErrorClass.http_error, str(exc)) from exc

            if response.status_code >= 400:
                # An error is an error. It never becomes "no activity" (T3).
                raise ProviderError(
                    _classify(response.status_code),
                    f"{response.status_code} from {path}",
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderError(ProviderErrorClass.parse_error, str(exc)) from exc
            if not isinstance(body, dict):
                raise ProviderError(ProviderErrorClass.parse_error, "expected a JSON object")
            self._record("GET", path, params=params, status=response.status_code, body=body)
            _reject_error_body(body, path)
            return body
        finally:
            if owns_client:
                await client.aclose()

    def _record(
        self,
        method: str,
        path: str,
        *,
        status: int,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Hand the exchange to the recorder. Headers are never included: the
        API key travels in one, and a saved bundle must not carry it."""
        if self.recorder is None:
            return
        self.recorder(
            {
                "method": method,
                "path": path,
                "params": params or {},
                "payload": payload or {},
                "status": status,
                "body": body,
                "captured_at": dt.datetime.now(dt.UTC).isoformat(),
            }
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._check_budget(path)
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            self.request_count += 1
            try:
                response = await client.post(
                    f"{self.base_url}{path}", json=payload, headers=self._headers()
                )
            except httpx.TimeoutException as exc:
                raise ProviderError(ProviderErrorClass.timeout, str(exc)) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(ProviderErrorClass.http_error, str(exc)) from exc

            if response.status_code >= 400:
                raise ProviderError(
                    _classify(response.status_code), f"{response.status_code} from {path}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderError(ProviderErrorClass.parse_error, str(exc)) from exc
            if not isinstance(body, dict):
                raise ProviderError(ProviderErrorClass.parse_error, "expected a JSON object")
            self._record("POST", path, payload=payload, status=response.status_code, body=body)
            _reject_error_body(body, path)
            return body
        finally:
            if owns_client:
                await client.aclose()

    @classmethod
    def tx_hash_from_reference(cls, reference: str) -> str | None:
        """Read the transaction back out of an event reference this adapter made.

        ``tron:<txid>:<event_index>`` or ``tron:<txid>:unindexed:<digest>``.
        Anything else returns ``None`` rather than a guess.
        """
        parts = reference.split(":")
        if len(parts) < 3 or parts[0] != cls.network_key or not parts[1]:
            return None
        return parts[1]

    # -- receipts ---------------------------------------------------------

    async def fetch_receipt(self, tx_hash: str) -> ExecutionReceipt:
        """Establish execution and finality for one transaction.

        Asks the solidified endpoint first, because an answer there is final.
        An empty answer there means the transaction is not solidified yet, not
        that it does not exist, so the head endpoint is asked next and its
        answer is marked provisional.
        """
        solidified = await self._post(SOLIDIFIED_RECEIPT_PATH, {"value": tx_hash})
        if solidified.get("id"):
            return self._to_receipt(
                tx_hash,
                solidified,
                solidified=True,
                source_path=SOLIDIFIED_RECEIPT_PATH,
                confirmation=ConfirmationState.confirmed,
                note="receipt read from a solidified block",
            )

        head = await self._post(HEAD_RECEIPT_PATH, {"value": tx_hash})
        if head.get("id"):
            return self._to_receipt(
                tx_hash,
                head,
                solidified=False,
                source_path=HEAD_RECEIPT_PATH,
                confirmation=ConfirmationState.provisional,
                note=(
                    "executed at the head but not solidified; the execution status is "
                    "the node's, the finality is not established"
                ),
            )

        return ExecutionReceipt(
            tx_hash=tx_hash,
            execution_status=ExecutionStatus.unknown,
            confirmation_state=ConfirmationState.unknown,
            solidified=False,
            source_path=HEAD_RECEIPT_PATH,
            note="no receipt at either endpoint; status unknown, not absent",
        )

    def _to_receipt(
        self,
        tx_hash: str,
        body: dict[str, Any],
        *,
        solidified: bool,
        source_path: str,
        confirmation: ConfirmationState,
        note: str,
    ) -> ExecutionReceipt:
        receipt = body.get("receipt")
        raw_result = None
        if isinstance(receipt, dict):
            value = receipt.get("result")
            raw_result = str(value) if value is not None else None
        return ExecutionReceipt(
            tx_hash=tx_hash,
            execution_status=_classify_receipt_result(raw_result),
            confirmation_state=confirmation,
            solidified=solidified,
            source_path=source_path,
            note=note,
            receipt_result=raw_result,
            block_number=_int_or_none(body.get("blockNumber")),
            block_time=_to_datetime(body.get("blockTimeStamp")),
            fee=_int_or_none(body.get("fee")),
        )

    async def fetch_receipts(
        self, tx_hashes: list[str]
    ) -> tuple[dict[str, ExecutionReceipt], dict[str, str]]:
        """One receipt per distinct transaction. Failures are returned, not raised."""
        receipts: dict[str, ExecutionReceipt] = {}
        failures: dict[str, str] = {}
        for tx_hash in dict.fromkeys(tx_hashes):
            try:
                receipts[tx_hash] = await self.fetch_receipt(tx_hash)
            except ProviderError as exc:
                failures[tx_hash] = f"{exc.error_class.value}: {exc}"
                if exc.error_class is ProviderErrorClass.budget_exhausted:
                    # Stop rather than re-attempt each remaining hash only to
                    # have the same exhausted budget refuse it again (C).
                    break
        return receipts, failures

    async def verify_execution(self, events: list[NormalizedTransfer]) -> ExecutionVerification:
        """Fill in execution and confirmation from receipts, one call per transaction.

        An event whose receipt could not be read keeps ``unknown`` and is listed
        in ``unverified`` with the reason. Nothing is upgraded on a failure.
        """
        receipts, failures = await self.fetch_receipts(
            list(dict.fromkeys(event.tx_hash for event in events))
        )

        verified: list[NormalizedTransfer] = []
        unverified: list[Unverified] = []
        for event in events:
            receipt = receipts.get(event.tx_hash)
            if receipt is None:
                unverified.append(
                    Unverified(event.event_reference, event.tx_hash, failures.get(event.tx_hash, "receipt unavailable; verification budget may be exhausted"))
                )
                verified.append(
                    replace(
                        event,
                        execution_status=ExecutionStatus.unknown,
                        confirmation_state=ConfirmationState.unknown,
                    )
                )
                continue
            if receipt.execution_status is ExecutionStatus.unknown:
                unverified.append(Unverified(event.event_reference, event.tx_hash, receipt.note))
            verified.append(
                replace(
                    event,
                    execution_status=receipt.execution_status,
                    confirmation_state=receipt.confirmation_state,
                )
            )
        return ExecutionVerification(events=verified, receipts=receipts, unverified=unverified)

    # -- resource evidence (Stage 2C2) -------------------------------------

    async def fetch_account_transactions(
        self,
        *,
        address: str,
        analysis_cutoff: dt.datetime,
        analysis_start: dt.datetime | None = None,
        direction: Direction = Direction.both,
        cursor: str | None = None,
        limit: int = 200,
    ) -> GeneralTransactionPage:
        """One page of an account's general history -- not TRC-20-specific.

        Used for genuinely historical resource-delegation operations and
        native TRX funding alike: every item here carries its own real
        ``block_timestamp``, unlike the current-state delegation endpoints.
        """
        canonical = self.validate_address(address).canonical
        params: dict[str, Any] = {
            "limit": min(limit, 200),
            "only_confirmed": "true",
            "order_by": "block_timestamp,asc",
            "max_timestamp": int(analysis_cutoff.timestamp() * 1000),
        }
        if analysis_start is not None:
            params["min_timestamp"] = int(analysis_start.timestamp() * 1000)
        if direction is Direction.outgoing:
            params["only_from"] = "true"
        elif direction is Direction.incoming:
            params["only_to"] = "true"
        if cursor:
            params["fingerprint"] = cursor

        path = GENERAL_TRANSACTIONS_PATH.format(address=canonical)
        body = await self._get(path, params)

        rows = body.get("data")
        if not isinstance(rows, list):
            raise ProviderError(ProviderErrorClass.parse_error, "missing 'data' array")
        meta = body.get("meta") or {}
        next_cursor = meta.get("fingerprint")

        transactions = [self._to_general_transaction(row) for row in rows if isinstance(row, dict)]
        return GeneralTransactionPage(transactions=transactions, next_cursor=next_cursor)

    #: Address-bearing keys seen across the contract types this adapter reads
    #: (TransferContract, DelegateResourceContract, UnDelegateResourceContract).
    #: Canonicalized in place so a caller never has to know whether raw_data
    #: happened to carry hex or base58 for a given field.
    _CONTRACT_ADDRESS_KEYS = ("owner_address", "to_address", "receiver_address")

    @classmethod
    def _to_general_transaction(cls, row: dict[str, Any]) -> GeneralTransaction:
        tx_id = str(row.get("txID") or "")
        contract = ((row.get("raw_data") or {}).get("contract") or [{}])[0]
        contract_type = str(contract.get("type") or "")
        raw_value = (contract.get("parameter") or {}).get("value") or {}
        contract_value = dict(raw_value)
        for key in cls._CONTRACT_ADDRESS_KEYS:
            if key in contract_value:
                canonical = _canonical_tron_address(contract_value[key], lower=False)
                if canonical is not None:
                    contract_value[key] = canonical
        ret = row.get("ret") or [{}]
        execution_result = ret[0].get("contractRet") if ret and isinstance(ret[0], dict) else None
        return GeneralTransaction(
            tx_id=tx_id,
            block_number=_int_or_none(row.get("blockNumber")),
            block_time=_to_datetime(row.get("block_timestamp")),
            contract_type=contract_type,
            contract_value=contract_value,
            execution_result=execution_result,
        )

    async def fetch_delegation_index(self, address: str) -> DelegationIndex:
        """Current-state Stake 2.0 delegation relationships, both directions.

        No timestamp is returned by this endpoint, and none is invented: a
        name appearing here means "has a delegation relationship right now",
        never "has had one since a particular time" (B).
        """
        canonical = self.validate_address(address).canonical
        body = await self._post(DELEGATION_INDEX_PATH, {"value": canonical, "visible": True})
        return DelegationIndex(
            account=str(body.get("account") or canonical),
            from_accounts=[str(a) for a in (body.get("fromAccounts") or [])],
            to_accounts=[str(a) for a in (body.get("toAccounts") or [])],
        )

    async def fetch_delegated_resource(
        self, from_address: str, to_address: str
    ) -> list[DelegatedResourceDetail]:
        """Current-state resource detail for one from/to pair.

        ``expire_time_for_*`` documents a lock *expiry*; it is read into
        ``expire_time`` and never treated as -- or relabelled -- a start time.
        """
        from_canonical = self.validate_address(from_address).canonical
        to_canonical = self.validate_address(to_address).canonical
        body = await self._post(
            DELEGATED_RESOURCE_PATH,
            {"fromAddress": from_canonical, "toAddress": to_canonical, "visible": True},
        )
        rows = body.get("delegatedResource")
        if not isinstance(rows, list):
            return []
        details = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            resource = row.get("resource")
            expire_ms = row.get("expire_time_for_bandwidth") or row.get("expire_time_for_energy")
            details.append(
                DelegatedResourceDetail(
                    from_address=from_canonical,
                    to_address=to_canonical,
                    resource=resource,
                    balance_sun=_int_or_none(row.get("balance")),
                    expire_time=_to_datetime(expire_ms),
                )
            )
        return details

    # -- ChainAdapter -----------------------------------------------------

    def validate_address(self, value: str) -> CanonicalAddress:
        return canonicalize_tron(value)

    async def fetch_transfers(
        self,
        *,
        address: str,
        asset: AssetRef,
        direction: Direction,
        analysis_cutoff: dt.datetime,
        analysis_start: dt.datetime | None = None,
        cursor: str | None = None,
        limit: int = 200,
        enrich: bool | None = None,
    ) -> TransferPage:
        canonical = self.validate_address(address).canonical
        requested_at = dt.datetime.now(dt.UTC)

        params: dict[str, Any] = {
            "limit": min(limit, 200),
            "only_confirmed": "true",
            "order_by": "block_timestamp,asc",
            "max_timestamp": int(analysis_cutoff.timestamp() * 1000),
        }
        if analysis_start is not None:
            # A documented parameter of this same endpoint, alongside
            # max_timestamp -- narrows the query itself rather than filtering
            # a wider page after the fact (A).
            params["min_timestamp"] = int(analysis_start.timestamp() * 1000)
        if asset.token_contract:
            params["contract_address"] = asset.token_contract
        if direction is Direction.outgoing:
            params["only_from"] = "true"
        elif direction is Direction.incoming:
            params["only_to"] = "true"
        # The cursor is TronGrid's fingerprint. Every other parameter stays
        # identical across pages; changing one mid-walk invalidates the cursor.
        if cursor:
            params["fingerprint"] = cursor

        path = f"/v1/accounts/{canonical}/transactions/trc20"
        body = await self._get(path, params)

        rows = body.get("data")
        if not isinstance(rows, list):
            raise ProviderError(ProviderErrorClass.parse_error, "missing 'data' array")
        meta = body.get("meta") or {}
        next_cursor = meta.get("fingerprint")

        events = await self._normalize(rows, asset, enrich=enrich)

        acquisition = AcquisitionRecord(
            provider="trongrid",
            endpoint=f"{self.base_url}{path}",
            requested_at=requested_at,
            observed_at=dt.datetime.now(dt.UTC),
            status=AcquisitionStatus.succeeded,
            coverage_status=(
                CoverageStatus.partial if next_cursor else CoverageStatus.complete_within_scope
            ),
            data_mode=DataMode.LIVE,
            analysis_cutoff=analysis_cutoff,
            parser_version=PARSER_VERSION,
            request_params_hash=hashlib.sha256(
                json.dumps(params, sort_keys=True).encode()
            ).hexdigest()[:32],
            response_hash=hashlib.sha256(
                json.dumps(body, sort_keys=True, default=str).encode()
            ).hexdigest()[:32],
        )
        return TransferPage(events=events, next_cursor=next_cursor, acquisition=acquisition)

    # -- normalization ----------------------------------------------------

    async def _normalize(
        self, rows: list[dict[str, Any]], asset: AssetRef, *, enrich: bool | None = None
    ) -> list[NormalizedTransfer]:
        by_transaction: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            tx_hash = row.get("transaction_id")
            if not tx_hash:
                raise ProviderError(
                    ProviderErrorClass.parse_error, "history row without transaction_id"
                )
            by_transaction[tx_hash].append(row)

        want_enrichment = self.enrich_events if enrich is None else enrich
        indices: dict[str, dict[str, int]] = {}
        if want_enrichment:
            for tx_hash in by_transaction:
                resolved = await self._resolve_event_indices(tx_hash, asset)
                if resolved:
                    indices[tx_hash] = resolved

        events: list[NormalizedTransfer] = []
        for tx_hash, group in by_transaction.items():
            for row in group:
                events.append(self._to_transfer(tx_hash, row, asset, indices.get(tx_hash, {})))
        return events

    async def _resolve_event_indices(self, tx_hash: str, asset: AssetRef) -> dict[str, int]:
        """Map each Transfer event of ``tx_hash`` to its documented ``event_index``.

        Returns an empty mapping when the response does not carry what we need.
        An empty mapping means "ambiguous", never "index 0".
        """
        try:
            body = await self._get(f"/v1/transactions/{tx_hash}/events")
        except ProviderError as exc:
            if exc.error_class is ProviderErrorClass.budget_exhausted:
                # Exhaustion is never "best-effort" -- it must stop the walk,
                # not be read as an empty/ambiguous enrichment (C).
                raise
            # Otherwise enrichment is best-effort. Losing it costs ordering
            # precision, and that loss is recorded on the event rather than
            # papered over.
            return {}

        return self._indices_from_event_rows(body.get("data"), asset)

    @staticmethod
    def _indices_from_event_rows(rows: Any, asset: AssetRef) -> dict[str, int]:
        """Shared by page-wide enrichment and the single-transaction resolver."""
        if not isinstance(rows, list):
            return {}

        mapping: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("event_name") != "Transfer":
                continue
            if asset.token_contract and row.get("contract_address") != asset.token_contract:
                continue
            index = row.get("event_index")
            if index is None:
                continue
            key = TronGridAdapter._result_key(row.get("result"))
            if key is None:
                continue
            # Two identical transfers in one transaction are genuinely
            # indistinguishable by content; refuse rather than pick one.
            if key in mapping:
                return {}
            mapping[key] = int(index)
        return mapping

    async def resolve_seed_event(
        self, transfer: NormalizedTransfer, asset: AssetRef
    ) -> NormalizedTransfer | None:
        """Enrich exactly one already-located transaction, not a whole page.

        Used once a seed's transaction id has been matched cheaply from an
        unenriched page (B): the per-transaction events lookup this costs is
        spent once, for the transaction actually being sought, never for
        every other transaction merely passing through the same page.

        Returns ``None`` when the transaction's own event detail does not
        actually describe this transfer (contract, participants or amount
        differ) -- a raw history-row match on transaction id alone is not
        enough to trust; reconciliation against decoded event detail is what
        makes it trustworthy (D005).
        """
        body = await self._get(f"/v1/transactions/{transfer.tx_hash}/events")
        rows = body.get("data")
        event_rows = rows if isinstance(rows, list) else []

        reconciliation = reconcile_event(transfer, event_rows, asset)
        if not reconciliation.matched:
            return None

        indices = self._indices_from_event_rows(event_rows, asset)
        key = self._result_key(
            {
                "from": transfer.from_address,
                "to": transfer.to_address,
                "value": transfer.amount_base_units,
            }
        )
        index = indices.get(key) if key is not None else None
        if index is None:
            # Reconciled, but the index could not be pinned to one event
            # (content collision or missing field). Stay honest about that
            # rather than inventing index 0 (D005).
            return transfer
        return replace(
            transfer,
            event_index=index,
            ordering_ambiguous=False,
            event_reference=f"{self.network_key}:{transfer.tx_hash}:{index}",
        )

    @staticmethod
    def _result_key(result: Any) -> str | None:
        """Build a content key from an event's decoded parameters.

        The events endpoint documents a ``result`` field but not its inner
        shape, so this reads defensively and gives up rather than assuming a
        layout. Addresses are canonicalized (the events endpoint returns
        20-byte hex here, not the base58 the history endpoint uses for the
        same fields) so this key lines up with ``_to_transfer``'s key built
        from the history row, whichever form either side happens to be in.
        """
        if not isinstance(result, dict):
            return None
        lowered = {str(k).lower().lstrip("_"): v for k, v in result.items()}
        sender = lowered.get("from")
        recipient = lowered.get("to")
        value = lowered.get("value")
        if sender is None or recipient is None or value is None:
            return None
        sender_key = _canonical_tron_address(sender) or str(sender).lower()
        recipient_key = _canonical_tron_address(recipient) or str(recipient).lower()
        return f"{sender_key}|{recipient_key}|{value}"

    def _to_transfer(
        self,
        tx_hash: str,
        row: dict[str, Any],
        asset: AssetRef,
        indices: dict[str, int],
    ) -> NormalizedTransfer:
        token_info = row.get("token_info") or {}
        contract = token_info.get("address")
        raw_value = row.get("value")
        if raw_value is None:
            raise ProviderError(ProviderErrorClass.parse_error, "history row without value")
        # TronGrid serializes value as a decimal string. int() keeps it exact.
        amount = int(str(raw_value))

        sender = row.get("from")
        recipient = row.get("to")
        sender_key = _canonical_tron_address(sender) or str(sender).lower()
        recipient_key = _canonical_tron_address(recipient) or str(recipient).lower()
        key = f"{sender_key}|{recipient_key}|{raw_value}"
        event_index = indices.get(key)

        if event_index is None:
            ordering_ambiguous = True
            # Content-derived, not a claimed chain position. Distinct events in
            # one transaction stay distinct; the ambiguity flag says the position
            # within the transaction is unknown.
            digest = hashlib.sha256(key.encode()).hexdigest()[:16]
            event_reference = f"tron:{tx_hash}:unindexed:{digest}"
        else:
            ordering_ambiguous = False
            event_reference = f"tron:{tx_hash}:{event_index}"

        return NormalizedTransfer(
            event_reference=event_reference,
            tx_hash=tx_hash,
            event_kind=TYPE_TO_EVENT_KIND.get(str(row.get("type")), EventKind.unknown),
            asset=AssetRef(
                network_key=self.network_key,
                token_contract=contract or asset.token_contract,
                decimals=int(token_info.get("decimals", asset.decimals)),
                display_symbol=str(token_info.get("symbol", asset.display_symbol)),
            ),
            from_address=sender,
            to_address=recipient,
            amount_base_units=amount,
            # The history endpoint documents no execution status. Claiming
            # "success" here would be an invention.
            execution_status=ExecutionStatus.unknown,
            # only_confirmed=true was requested, so TronGrid returns confirmed rows.
            confirmation_state=ConfirmationState.confirmed,
            block_time=_to_datetime(row.get("block_timestamp")),
            event_index=event_index,
            ordering_ambiguous=ordering_ambiguous,
        )
