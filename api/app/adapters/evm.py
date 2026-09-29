"""Generic EVM JSON-RPC adapter for ERC-20 ``Transfer`` events.

One adapter class, parameterized by network configuration (:data:`EVM_NETWORKS`),
so a second EVM chain is a new registry entry, not a new adapter class.
Enabled: ``ethereum`` (Ethereum Mainnet, chain_id=1, Task 05) and ``bsc`` (BNB
Smart Chain Mainnet, chain_id=56, Task 06). Each has its own acceptance tests
and its own RPC setting (AGENTS.md: additional networks need their own
acceptance tests before appearing supported). BEP-20 tokens emit the same
``Transfer(address,address,uint256)`` event as ERC-20, so BSC uses exactly the
same decoder, ordering, receipt, finality, range-splitting and recording code.

Endpoints used, all standard JSON-RPC, documented at
https://ethereum.org/en/developers/docs/apis/json-rpc/ (checked 2026-09-26):

``eth_chainId``
    Returns the connected node's chain id. Checked once per adapter instance,
    before any other request, and the acquisition refuses to proceed if it does
    not match the configured network's chain id -- a misrouted or mislabeled
    endpoint (Sepolia, a fork, a different chain entirely) is never silently
    accepted as "Ethereum" (or "BSC") merely because it was placed in
    ``CFA_ETHEREUM_RPC_URL`` (or ``CFA_BSC_RPC_URL``).

``eth_getBlockByNumber``
    Takes a block tag (``"latest"``, ``"safe"``, ``"finalized"``) or an
    ``0x``-prefixed block number, plus a boolean for whether to include full
    transaction objects (always ``False`` here -- only ``number`` and
    ``timestamp`` are read). Documents ``number`` and ``timestamp`` as
    ``0x``-prefixed hex quantities. A tag a node does not support (older
    clients, some non-Ethereum-labelled endpoints) documents returning
    ``null``; that is read as "this finality tier is not available", not as an
    error, and the corresponding finality classification becomes ``unknown``.

``eth_getLogs``
    Takes ``fromBlock``/``toBlock`` (hex block numbers), ``address`` (the
    token contract), and ``topics`` (indexed-parameter filter, positional).
    Each returned log documents ``address``, ``topics``, ``data``,
    ``blockNumber``, ``blockHash``, ``transactionHash``, ``transactionIndex``,
    ``logIndex``, and ``removed``. This adapter never asks for an unbounded
    range -- ``fromBlock``/``toBlock`` are always resolved from the caller's
    analysis window first (see ``_resolve_block_range``).

``eth_getCode`` / ``eth_call``
    Read-only token verification only (:meth:`EvmRpcAdapter.verify_token_contract`):
    the contract's deployed bytecode, and its ``decimals()``, ``symbol()`` and
    ``name()`` views, all at ``"latest"``. Never a state-changing call, never a
    signed transaction. These establish technical facts about a contract, not
    who issued the token.

``eth_getTransactionReceipt``
    Documents ``status`` (``"0x1"`` success, ``"0x0"`` reverted -- Byzantium
    and later; Ethereum Mainnet has been past Byzantium since block
    4,370,000, and BSC launched with Byzantium rules active), ``blockNumber``,
    ``gasUsed``, and ``effectiveGasPrice``.
    Execution and finality are established independently here, exactly as for
    TRON: a successful execution in a non-finalized block is
    ``success`` + not-yet-final, never promoted to finalized by inference.

Explicitly NOT implemented in this phase:

* Native ETH/BNB value transfers (plain value-carrying transactions and internal
  calls). Those need transaction/internal-call tracing, a different
  acquisition problem from log-based ERC-20 tracking, and are out of scope
  here (see AGENTS.md and the Task 05 completion report).
* Any explorer API (Etherscan or otherwise) as a data source. Standard
  JSON-RPC only.
* A confirmation-count fallback for finality. A provider that does not
  support the ``safe``/``finalized`` tags yields ``finality_detail="unknown"``,
  never an inferred finalization from block-depth alone.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qsl, urlsplit

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
from app.services.addresses import AddressValidationError, CanonicalAddress, canonicalize_evm

PARSER_VERSION = "evm-0.1.0"

#: keccak256("Transfer(address,address,uint256)"), the standard ERC-20/EIP-20
#: event signature. Well-known and documented on every block explorer (e.g. any
#: ERC-20 contract's "Transfer" log topic0 on Etherscan); not computed here
#: because no keccak implementation is an existing project dependency, and
#: adding one merely to re-derive a constant that never changes is not
#: justified (AGENTS.md: use existing abstractions; do not invent an endpoint
#: or a dependency without a measured need).
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

#: Hard bound on adaptive eth_getLogs range splitting (Phase K). A single-block
#: query that still fails is never split further; it is recorded incomplete.
MAX_LOG_SPLIT_DEPTH = 10

#: Hard bound on the timestamp -> block binary search (Phase J), independent of
#: the provider request budget, so a pathological search cannot itself become
#: an unbounded scan even when the budget is generous.
MAX_BLOCK_RESOLUTION_ITERATIONS = 40

#: How a window's *start* instant is resolved to a block, recorded in every
#: EVM validation manifest so a replay reissues exactly the requests its bundle
#: holds. ``CURRENT``: last block strictly before the start (never skips blocks
#: sharing the start's one-second timestamp). ``LEGACY``: last block at or
#: before the start -- the Task 05 behavior, kept only to replay bundles
#: recorded with it; it can skip same-second blocks on chains that produce
#: several blocks per second, so new runs never use it.
BLOCK_RESOLUTION_CURRENT = "start-strictly-before-v2"
BLOCK_RESOLUTION_LEGACY = "start-at-or-before-v1"
BLOCK_RESOLUTION_POLICIES = frozenset({BLOCK_RESOLUTION_CURRENT, BLOCK_RESOLUTION_LEGACY})


#: Function selectors (first 4 bytes of keccak256 of the signature) for the
#: standard ERC-20 metadata views, used only by read-only token verification.
#: Well-known constants, not computed here for the same reason as
#: ``TRANSFER_TOPIC``.
DECIMALS_SELECTOR = "0x313ce567"  # decimals()
SYMBOL_SELECTOR = "0x95d89b41"  # symbol()
NAME_SELECTOR = "0x06fdde03"  # name()


@dataclass(frozen=True)
class EvmNetworkConfig:
    network_key: str
    chain_id: int
    display_name: str
    native_symbol: str
    #: Name of the ``Settings`` attribute holding this network's RPC URL. Each
    #: network has its own, and one never falls back to another's.
    rpc_setting: str
    #: What the finality tags mean here, for reports. A note, not a policy:
    #: classification is always what the provider's own tags return.
    finality_note: str

    @property
    def caip2(self) -> str:
        return f"eip155:{self.chain_id}"

    @property
    def rpc_env_var(self) -> str:
        return f"CFA_{self.rpc_setting.upper()}"


#: Every enabled EVM network (AGENTS.md: each chain needs its own acceptance
#: tests before appearing supported). Adding another is a new entry here, not a
#: new adapter class.
EVM_NETWORKS: dict[str, EvmNetworkConfig] = {
    "ethereum": EvmNetworkConfig(
        network_key="ethereum",
        chain_id=1,
        display_name="Ethereum Mainnet",
        native_symbol="ETH",
        rpc_setting="ethereum_rpc_url",
        finality_note=(
            "Proof-of-stake 'finalized'/'safe' block tags as returned by the provider."
        ),
    ),
    "bsc": EvmNetworkConfig(
        network_key="bsc",
        chain_id=56,
        display_name="BNB Smart Chain Mainnet",
        native_symbol="BNB",
        rpc_setting="bsc_rpc_url",
        finality_note=(
            "'finalized'/'safe' block tags as returned by the configured provider. BSC "
            "fast finality (BEP-126) is why the tags are consulted; their availability "
            "and meaning are observed per provider, not assumed. No confirmation-count "
            "fallback: an unsupported tag yields finality 'unknown'."
        ),
    ),
    "base": EvmNetworkConfig(
        network_key="base",
        chain_id=8453,
        display_name="Base Mainnet",
        native_symbol="ETH",
        rpc_setting="base_rpc_url",
        finality_note=(
            "'finalized'/'safe' block tags as returned by the configured provider. "
            "Base L2 finality depends on L1 rollup posting; provider tags are observed, "
            "not assumed. No confirmation-count fallback: an unsupported tag yields "
            "finality 'unknown'."
        ),
    ),
}


@dataclass(frozen=True)
class BlockRangeResolution:
    """A caller's [analysis_start, analysis_cutoff] window, resolved to blocks.

    ``truncated_reason`` is set whenever the resolution could not be trusted as
    exact -- provider-visible history ends before/after the requested instant,
    or the block-resolution budget ran out mid-search. The caller reports
    ``coverage_status=partial`` whenever it is set; nothing here silently
    widens or narrows the range to make the search look clean.
    """

    from_block: int
    to_block: int
    truncated_reason: str | None = None
    block_resolution_requests: int = 0


class EvmRpcAdapter(ChainAdapter):
    """Live/RECORDED_PUBLIC EVM adapter. Refuses to run in SYNTHETIC mode (D009)."""

    supported_data_modes = frozenset({DataMode.LIVE, DataMode.RECORDED_PUBLIC})

    def __repr__(self) -> str:
        # Never the RPC URL: it may embed a provider API key.
        return f"EvmRpcAdapter(network_key={self.network_key!r}, chain_id={self.chain_id})"

    def __init__(
        self,
        rpc_url: str,
        *,
        network_key: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
        max_requests: int | None = None,
        recorder: Any = None,
        max_log_split_depth: int = MAX_LOG_SPLIT_DEPTH,
        block_resolution_policy: str = BLOCK_RESOLUTION_CURRENT,
    ) -> None:
        config = EVM_NETWORKS.get(network_key)
        if config is None:
            raise ProviderError(
                ProviderErrorClass.unsupported,
                f"no EVM network configuration for {network_key!r}; supported: "
                f"{sorted(EVM_NETWORKS)}",
            )
        if block_resolution_policy not in BLOCK_RESOLUTION_POLICIES:
            raise ProviderError(
                ProviderErrorClass.unsupported,
                f"unknown block-resolution policy {block_resolution_policy!r}",
            )
        self.block_resolution_policy = block_resolution_policy
        self.network_key = network_key
        self.chain_id = config.chain_id
        self._config = config
        self.rpc_url = rpc_url
        self._secret_fragments = _url_secret_fragments(rpc_url)
        self._client = client
        self._timeout = timeout
        self.max_requests = max_requests
        self.recorder = recorder
        self.max_log_split_depth = max_log_split_depth

        self.request_count = 0
        self._rpc_id = 0
        #: Set once ``eth_chainId`` has been checked against ``self.chain_id``.
        self.observed_chain_id: int | None = None
        #: Cache of ``eth_getBlockByNumber`` results, keyed by the exact tag or
        #: hex number requested -- shared by the binary search and block-time
        #: enrichment so neither pays twice for the same block (Phase J: "cache
        #: every result during one run").
        self._block_cache: dict[str, dict[str, Any] | None] = {}
        self._finality_cache: tuple[int | None, int | None] | None = None
        #: Fully resolved, deduplicated events for one (address, contract,
        #: direction, block range) query -- computed once per run, then paged
        #: in memory (Phase K: "cached during one run").
        self._log_cache: dict[tuple[str, str | None, str, int, int], list[NormalizedTransfer]] = {}
        #: Block ranges that could not be read even after splitting to the
        #: minimum span, for honest partial-coverage reporting.
        self.incomplete_ranges: list[tuple[int, int]] = []
        #: eth_getLogs ranges the provider rejected and that were split in two.
        #: Rejected requests that fail at the HTTP level are never recorded, so
        #: this (with ``request_count``) is how a bundle accounts for them.
        self.log_range_splits = 0
        self.block_resolution_requests = 0

    # -- plumbing -----------------------------------------------------------

    def _redact(self, text: str) -> str:
        """Strip the RPC URL, and any part of it that could be a credential,
        from provider-derived text before it can reach a ``ProviderError`` --
        and from there a tracer limitation, ``run.failure``, a manifest,
        stdout/stderr, or a report. httpx exception messages and some
        providers' JSON-RPC error messages echo the request URL."""
        return redact_url_text(text, self._secret_fragments)

    def _provider_error(self, error_class: ProviderErrorClass, text: str) -> ProviderError:
        return ProviderError(error_class, self._redact(text))

    def _check_budget(self, method: str) -> None:
        if self._client is not None or self.max_requests is None:
            return
        if self.request_count >= self.max_requests:
            raise ProviderError(
                ProviderErrorClass.budget_exhausted,
                f"request budget of {self.max_requests} exhausted before {method} "
                f"({self.request_count} requests already issued)",
            )

    def _record(
        self,
        *,
        rpc_method: str,
        params: list[Any],
        request_id: int,
        status: int,
        body: dict[str, Any],
    ) -> None:
        """Hand a sanitized exchange to the recorder. Never the RPC URL: it may
        carry a provider API key, and a saved bundle must not carry secrets.

        ``path`` is a fixed constant, not derived from the real request. A
        single JSON-RPC endpoint answers every method at one URL, and replay
        never has (or needs) the real, possibly secret-bearing URL path -- it
        replays through a placeholder host whose own path also normalizes to
        ``"/"`` (``replay_client`` matches on exactly this recorded value, not
        on whatever path the live run's real endpoint happened to have).
        ``payload`` mirrors the exact JSON body sent on the wire, ``id``
        included: ``replay_client`` matches on the real outgoing request's
        body, and a replay reissues requests in the same order starting from
        the same counter, so the ids line up call-for-call between the live
        recording and the replay.
        """
        if self.recorder is None:
            return
        self.recorder(
            {
                "method": "POST",
                "path": "/",
                "params": {},
                "payload": {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": rpc_method,
                    "params": params,
                },
                "status": status,
                "body": body,
                "captured_at": dt.datetime.now(dt.UTC).isoformat(),
            }
        )

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        """One JSON-RPC call. Returns ``result``; raises on a JSON-RPC error."""
        self._check_budget(method)
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        self._rpc_id += 1
        request_id = self._rpc_id
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            self.request_count += 1
            # ``from None``: the original httpx exception's own text (and its
            # ``request.url``) can carry the RPC URL, so it is not chained onto
            # the error a traceback would print. Only the redacted text survives.
            try:
                response = await client.post(self.rpc_url, json=body)
            except httpx.TimeoutException as exc:
                raise self._provider_error(
                    ProviderErrorClass.timeout, f"{type(exc).__name__}: {exc}"
                ) from None
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                raise self._provider_error(
                    ProviderErrorClass.http_error, f"{type(exc).__name__}: {exc}"
                ) from None

            if response.status_code == 429:
                raise ProviderError(ProviderErrorClass.rate_limit, f"429 from {method}")
            if response.status_code >= 400:
                raise ProviderError(
                    ProviderErrorClass.http_error, f"{response.status_code} from {method}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise self._provider_error(ProviderErrorClass.parse_error, str(exc)) from None
            if not isinstance(payload, dict):
                raise ProviderError(ProviderErrorClass.parse_error, "expected a JSON object")
            self._record(
                rpc_method=method,
                params=params,
                request_id=request_id,
                status=response.status_code,
                body=payload,
            )
            error = payload.get("error")
            if error:
                raise self._provider_error(ProviderErrorClass.provider_error, f"{method}: {error}")
            # ``replay_client`` (live_validation.py) signals "the live run made
            # no recording of this exchange" with ``{"Error": "..."}`` -- a
            # capital-E field, distinct from JSON-RPC's own lowercase "error".
            # A request that failed live at the HTTP level (status >= 400,
            # above) is never recorded in the first place, so its absence
            # during replay must surface as the same kind of failure it was
            # live, not as a false empty/None result (T3).
            replay_miss = payload.get("Error")
            if replay_miss:
                raise self._provider_error(
                    ProviderErrorClass.provider_error, f"{method}: {replay_miss}"
                )
            return payload.get("result")
        finally:
            if owns_client:
                await client.aclose()

    async def _ensure_chain_id(self) -> None:
        """Refuse to serve any data before the endpoint proves it is the
        configured network (constraint 3): no address, log, or receipt is ever
        read from an endpoint that has not first confirmed its chain id."""
        if self.observed_chain_id is not None:
            return
        result = await self._rpc("eth_chainId", [])
        observed = _hex_to_int(result) if isinstance(result, str) else None
        self.observed_chain_id = observed
        if observed != self.chain_id:
            raise ProviderError(
                ProviderErrorClass.unsupported,
                f"configured endpoint reports chain_id={observed!r}, expected "
                f"{self.chain_id} for network {self.network_key!r}; refusing to treat "
                "it as this network",
            )

    def _require_own_network(self, asset: AssetRef) -> None:
        """An ``AssetRef`` names its network. Refuse one from another network
        rather than silently rewriting its identity to this adapter's: an
        Ethereum asset handed to a BSC adapter (or the reverse) is a caller
        error, never a BSC observation."""
        if asset.network_key != self.network_key:
            raise ProviderError(
                ProviderErrorClass.unsupported,
                f"asset is on network {asset.network_key!r} but this adapter serves "
                f"{self.network_key!r}; refusing to relabel it",
            )

    async def _block_by_number(self, tag_or_number: str | int) -> dict[str, Any] | None:
        key = tag_or_number if isinstance(tag_or_number, str) else hex(tag_or_number)
        if key in self._block_cache:
            return self._block_cache[key]
        result = await self._rpc("eth_getBlockByNumber", [key, False])
        block = result if isinstance(result, dict) else None
        self._block_cache[key] = block
        return block

    # -- ChainAdapter ---------------------------------------------------------

    def validate_address(self, value: str) -> CanonicalAddress:
        return canonicalize_evm(value)

    @classmethod
    def tx_hash_from_reference(cls, reference: str) -> str | None:
        """Read the transaction id back out of ``eip155:<chain_id>:<tx_hash>:<log_index>``.

        The chain id lives in the reference itself, so this needs no instance
        state and can stay a true classmethod (unlike the network/chain id this
        adapter otherwise carries per instance, since one adapter class serves
        every configured EVM network).
        """
        parts = reference.split(":")
        if len(parts) != 4 or parts[0] != "eip155" or not parts[1].isdigit() or not parts[2]:
            return None
        return parts[2]

    async def resolve_seed_event(
        self,
        transfer: NormalizedTransfer,
        asset: AssetRef,  # noqa: ARG002
    ) -> NormalizedTransfer | None:
        """EVM logs from ``eth_getLogs`` are already exact and fully decoded --
        contract, participants, amount, and log index all come from the same
        call that located the transfer, unlike TRON's split history/events
        endpoints. There is nothing further to reconcile against."""
        return transfer

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
        enrich: bool | None = None,  # noqa: ARG002 -- EVM logs need no separate enrichment pass
    ) -> TransferPage:
        self._require_own_network(asset)
        await self._ensure_chain_id()
        canonical = self.validate_address(address).canonical
        requested_at = dt.datetime.now(dt.UTC)

        resolution = await self._resolve_block_range(analysis_start, analysis_cutoff)

        cache_key = (
            canonical,
            asset.token_contract,
            direction.value,
            resolution.from_block,
            resolution.to_block,
        )
        if cache_key not in self._log_cache:
            self._log_cache[cache_key] = await self._collect_transfer_events(
                canonical, asset, direction, resolution
            )
        events = self._log_cache[cache_key]

        start = int(cursor) if cursor else 0
        window = events[start : start + limit]
        next_cursor = str(start + limit) if start + limit < len(events) else None

        params_hash = hashlib.sha256(
            json.dumps(
                {
                    "address": canonical,
                    "contract": asset.token_contract,
                    "direction": direction.value,
                    "from_block": resolution.from_block,
                    "to_block": resolution.to_block,
                    "cursor": cursor,
                    "limit": limit,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()[:32]

        coverage = (
            CoverageStatus.partial
            if (resolution.truncated_reason or self.incomplete_ranges or next_cursor)
            else CoverageStatus.complete_within_scope
        )
        acquisition = AcquisitionRecord(
            provider=f"evm-json-rpc:{self.network_key}",
            endpoint="eth_getLogs",
            requested_at=requested_at,
            observed_at=dt.datetime.now(dt.UTC),
            status=AcquisitionStatus.succeeded,
            coverage_status=coverage,
            data_mode=DataMode.LIVE,
            analysis_cutoff=analysis_cutoff,
            parser_version=PARSER_VERSION,
            request_params_hash=params_hash,
        )
        return TransferPage(events=window, next_cursor=next_cursor, acquisition=acquisition)

    # -- block-range resolution (Phase J) ------------------------------------

    async def _resolve_block_range(
        self, start: dt.datetime | None, cutoff: dt.datetime
    ) -> BlockRangeResolution:
        before = self.block_resolution_requests
        latest_block = await self._block_by_number("latest")
        if latest_block is None:
            raise ProviderError(
                ProviderErrorClass.parse_error, "eth_getBlockByNumber('latest') failed"
            )
        latest_number = _hex_to_int(latest_block["number"])
        latest_time = _hex_timestamp(latest_block["timestamp"])

        truncated: str | None = None
        if cutoff >= latest_time:
            to_block = latest_number
            if cutoff > latest_time:
                truncated = (
                    f"requested cutoff {cutoff.isoformat()} is after the latest observed block "
                    f"({latest_number} at {latest_time.isoformat()}); bounded at chain head"
                )
        else:
            to_block, extra = await self._binary_search_block(
                cutoff, 0, latest_number, before_or_at=True
            )
            if extra is not None:
                truncated = extra

        if start is None:
            from_block = 0
        elif start > latest_time:
            from_block = latest_number
            truncated = (
                f"requested start {start.isoformat()} is after the latest observed block; "
                "no history exists yet in this window"
            )
        else:
            from_block, extra = await self._binary_search_block(
                start, 0, latest_number, before_or_at=False
            )
            if extra is not None:
                truncated = truncated or extra

        if from_block > to_block:
            from_block = to_block

        return BlockRangeResolution(
            from_block=from_block,
            to_block=to_block,
            truncated_reason=truncated,
            block_resolution_requests=self.block_resolution_requests - before,
        )

    async def _binary_search_block(
        self, target: dt.datetime, lo: int, hi: int, *, before_or_at: bool
    ) -> tuple[int, str | None]:
        """Find the block whose timestamp brackets ``target``.

        ``before_or_at=True`` finds the last block with timestamp <= target
        (an upper bound for a cutoff: every block stamped at the cutoff second
        is included). ``False`` finds the last block with timestamp strictly
        *before* target (a lower bound for a start) under
        ``BLOCK_RESOLUTION_CURRENT``; ``BLOCK_RESOLUTION_LEGACY`` keeps the
        Task 05 at-or-before rule for replaying bundles recorded with it. That lower bound may sit
        up to one block before the window, and never after its first block:
        block timestamps have one-second resolution, and a chain can produce
        several blocks within one second (observed on BSC Mainnet), so "the
        last block at or before the start" would silently skip the earlier
        blocks that share the start's second. Bounded by
        ``MAX_BLOCK_RESOLUTION_ITERATIONS`` and the adapter's own request
        budget; on exhaustion, returns the tightest safe bound found so far
        (never one that would overclaim coverage) plus a reason.
        """
        iterations = 0
        best = lo
        strict = not before_or_at and self.block_resolution_policy == BLOCK_RESOLUTION_CURRENT
        while lo <= hi:
            if iterations >= MAX_BLOCK_RESOLUTION_ITERATIONS:
                return (
                    best,
                    "block-resolution iteration bound reached; range narrowed conservatively",
                )
            try:
                if self.max_requests is not None and self.request_count >= self.max_requests:
                    raise ProviderError(ProviderErrorClass.budget_exhausted, "block resolution")
                mid = (lo + hi) // 2
                block = await self._block_by_number(mid)
                self.block_resolution_requests += 1
                iterations += 1
            except ProviderError as exc:
                if exc.error_class is ProviderErrorClass.budget_exhausted:
                    return best, "provider request budget exhausted during block resolution"
                raise
            if block is None:
                return (
                    best,
                    f"eth_getBlockByNumber({mid}) returned no block; range narrowed conservatively",
                )
            block_time = _hex_timestamp(block["timestamp"])
            if block_time < target if strict else block_time <= target:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best, None

    # -- log acquisition and splitting (Phase I, K) --------------------------

    async def _collect_transfer_events(
        self,
        canonical: str,
        asset: AssetRef,
        direction: Direction,
        resolution: BlockRangeResolution,
    ) -> list[NormalizedTransfer]:
        raw_logs: list[dict[str, Any]] = []
        if direction in (Direction.outgoing, Direction.both):
            topics = [TRANSFER_TOPIC, _address_to_topic(canonical), None]
            raw_logs.extend(
                await self._fetch_logs_range(
                    resolution.from_block, resolution.to_block, asset.token_contract, topics
                )
            )
        if direction in (Direction.incoming, Direction.both):
            topics = [TRANSFER_TOPIC, None, _address_to_topic(canonical)]
            raw_logs.extend(
                await self._fetch_logs_range(
                    resolution.from_block, resolution.to_block, asset.token_contract, topics
                )
            )

        by_reference: dict[str, NormalizedTransfer] = {}
        for raw in raw_logs:
            transfer = self._normalize_log(raw, asset)
            if transfer is None:
                continue
            # Deduplicate by exact canonical identity only -- the same log
            # reached through both the incoming and outgoing query stays one
            # event, never two, and two distinct logs never collapse into one
            # merely because they share a transaction, amount, or addresses.
            by_reference[transfer.event_reference] = transfer

        events = list(by_reference.values())
        await self._attach_block_times(events)
        events.sort(key=lambda e: (e.block_height or 0, e.index_in_block or 0, e.event_index or 0))
        return events

    async def _attach_block_times(self, events: list[NormalizedTransfer]) -> None:
        block_numbers = sorted({e.block_height for e in events if e.block_height is not None})
        for index, transfer in enumerate(events):
            if transfer.block_height is None:
                continue
            block = await self._block_by_number(transfer.block_height)
            if block is None:
                continue
            events[index] = replace(transfer, block_time=_hex_timestamp(block["timestamp"]))
        del block_numbers  # documents intent; per-event cache lookups already dedupe repeats

    async def _fetch_logs_range(
        self,
        from_block: int,
        to_block: int,
        contract: str | None,
        topics: list[str | None],
        *,
        depth: int = 0,
    ) -> list[dict[str, Any]]:
        """``eth_getLogs`` over one block range, splitting on failure.

        Deterministic left-then-right recursion, a hard split-depth ceiling, a
        minimum span of one block, and the adapter's own request budget are all
        enforced here (Phase K). A range that still cannot be read at minimum
        span, or once the depth ceiling is reached, is recorded in
        ``self.incomplete_ranges`` and contributes no events -- it is never
        silently treated as empty activity.
        """
        params = [
            {
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "address": contract,
                "topics": topics,
            }
        ]
        try:
            result = await self._rpc("eth_getLogs", params)
        except ProviderError as exc:
            if exc.error_class is ProviderErrorClass.budget_exhausted:
                # Exhaustion stops the walk; it is never "best effort" (C).
                raise
            if from_block >= to_block or depth >= self.max_log_split_depth:
                self.incomplete_ranges.append((from_block, to_block))
                return []
            self.log_range_splits += 1
            mid = (from_block + to_block) // 2
            left = await self._fetch_logs_range(from_block, mid, contract, topics, depth=depth + 1)
            right = await self._fetch_logs_range(
                mid + 1, to_block, contract, topics, depth=depth + 1
            )
            return left + right
        return result if isinstance(result, list) else []

    def _normalize_log(self, raw: Any, asset: AssetRef) -> NormalizedTransfer | None:
        """Strict ERC-20 ``Transfer`` decode. Anything that does not match the
        exact documented shape is skipped rather than guessed at (D005)."""
        if not isinstance(raw, dict):
            return None
        topics = raw.get("topics")
        if not isinstance(topics, list) or len(topics) != 3:
            return None
        if not isinstance(topics[0], str) or topics[0].lower() != TRANSFER_TOPIC:
            return None
        from_address = _topic_to_address(topics[1])
        to_address = _topic_to_address(topics[2])
        if from_address is None or to_address is None:
            return None
        amount = _decode_uint256(raw.get("data"))
        if amount is None:
            return None

        contract = raw.get("address")
        if not isinstance(contract, str):
            return None
        contract = contract.lower()
        if asset.token_contract and contract != asset.token_contract.lower():
            return None

        tx_hash = raw.get("transactionHash")
        log_index = _hex_to_int_or_none(raw.get("logIndex"))
        if not isinstance(tx_hash, str) or not tx_hash or log_index is None:
            # Cannot build a stable identity without both. Refuse rather than
            # invent an index (D005) -- this row is dropped, not guessed at.
            return None

        block_number = _hex_to_int_or_none(raw.get("blockNumber"))
        tx_index = _hex_to_int_or_none(raw.get("transactionIndex"))
        removed = bool(raw.get("removed", False))

        self._require_own_network(asset)
        return NormalizedTransfer(
            event_reference=f"eip155:{self.chain_id}:{tx_hash}:{log_index}",
            tx_hash=tx_hash,
            event_kind=EventKind.transfer,
            asset=AssetRef(
                network_key=asset.network_key,
                token_contract=contract,
                decimals=asset.decimals,
                display_symbol=asset.display_symbol,
            ),
            from_address=from_address,
            to_address=to_address,
            amount_base_units=amount,
            # eth_getLogs documents no execution status; a receipt establishes it.
            execution_status=ExecutionStatus.unknown,
            confirmation_state=ConfirmationState.removed if removed else ConfirmationState.unknown,
            block_height=block_number,
            block_hash=raw.get("blockHash") if isinstance(raw.get("blockHash"), str) else None,
            block_time=None,
            index_in_block=tx_index,
            event_index=log_index,
            ordering_ambiguous=block_number is None or tx_index is None,
        )

    # -- read-only token verification -------------------------------------------

    async def _eth_call(self, contract: str, selector: str) -> str | None:
        result = await self._rpc("eth_call", [{"to": contract, "data": selector}, "latest"])
        return result if isinstance(result, str) else None

    async def verify_token_contract(self, contract: str) -> dict[str, Any]:
        """Technical facts about a token contract on this network, read-only.

        Chain id (checked first, as for every read), deployed bytecode, and the
        ``decimals()``/``symbol()``/``name()`` views at ``"latest"``. Every call
        goes through ``_rpc``, so it is budgeted and recorded like any other
        exchange and replays from the same bundle. A symbol or name here is the
        contract's own claim about itself: it does not establish who issued
        the token (AGENTS.md: symbols are display metadata, not identifiers).
        """
        await self._ensure_chain_id()
        canonical = self.validate_address(contract).canonical
        code = await self._rpc("eth_getCode", [canonical, "latest"])
        code_hex = code if isinstance(code, str) and code.startswith("0x") else "0x"
        code_bytes = bytes.fromhex(code_hex[2:]) if len(code_hex) % 2 == 0 else b""
        decimals_word = _decode_uint256(await self._eth_call(canonical, DECIMALS_SELECTOR))
        decimals = decimals_word if decimals_word is not None and decimals_word < 256 else None
        return {
            "network": self.network_key,
            "chain_id": self.chain_id,
            "caip2": self._config.caip2,
            "observed_chain_id": self.observed_chain_id,
            "contract": canonical,
            "block_tag": "latest",
            "code_present": len(code_bytes) > 0,
            "code_size_bytes": len(code_bytes),
            "code_sha256": hashlib.sha256(code_bytes).hexdigest() if code_bytes else None,
            "decimals": decimals,
            "symbol": _decode_abi_string(await self._eth_call(canonical, SYMBOL_SELECTOR)),
            "name": _decode_abi_string(await self._eth_call(canonical, NAME_SELECTOR)),
            "note": (
                "Technical, read-only contract checks. They do not establish the "
                "token's issuer, backing, or provenance."
            ),
        }

    # -- receipts and finality ------------------------------------------------

    async def _finality_tags(self) -> tuple[int | None, int | None]:
        """(finalized_block, safe_block), cached for the run. ``None`` for a tag
        the provider does not support -- never inferred from confirmation depth."""
        if self._finality_cache is None:
            finalized = await self._safe_tag_block("finalized")
            safe = await self._safe_tag_block("safe")
            self._finality_cache = (finalized, safe)
        return self._finality_cache

    async def _safe_tag_block(self, tag: str) -> int | None:
        try:
            block = await self._block_by_number(tag)
        except ProviderError:
            return None
        if block is None:
            return None
        return _hex_to_int_or_none(block.get("number"))

    async def fetch_receipt(self, tx_hash: str) -> ExecutionReceipt:
        await self._ensure_chain_id()
        receipt = await self._rpc("eth_getTransactionReceipt", [tx_hash])
        if not isinstance(receipt, dict):
            return ExecutionReceipt(
                tx_hash=tx_hash,
                execution_status=ExecutionStatus.unknown,
                confirmation_state=ConfirmationState.unknown,
                solidified=False,
                source_path="eth_getTransactionReceipt",
                note="no receipt returned; not yet mined, or unknown to this node",
            )

        status_hex = receipt.get("status")
        execution_status = ExecutionStatus.unknown
        if isinstance(status_hex, str):
            execution_status = (
                ExecutionStatus.success
                if _hex_to_int(status_hex) == 1
                else ExecutionStatus.reverted
            )

        block_number = _hex_to_int_or_none(receipt.get("blockNumber"))
        finalized, safe = await self._finality_tags()
        finality_detail = "unknown"
        confirmation = ConfirmationState.unknown
        if block_number is not None:
            if finalized is not None and block_number <= finalized:
                finality_detail, confirmation = "finalized", ConfirmationState.confirmed
            elif safe is not None and block_number <= safe:
                finality_detail, confirmation = "safe", ConfirmationState.provisional
            elif finalized is not None or safe is not None:
                finality_detail, confirmation = "head_unfinalized", ConfirmationState.provisional

        block_time = None
        if block_number is not None:
            block = await self._block_by_number(block_number)
            if block is not None:
                block_time = _hex_timestamp(block["timestamp"])

        return ExecutionReceipt(
            tx_hash=tx_hash,
            execution_status=execution_status,
            confirmation_state=confirmation,
            solidified=finality_detail == "finalized",
            source_path="eth_getTransactionReceipt",
            note=f"finality={finality_detail}",
            receipt_result=status_hex if isinstance(status_hex, str) else None,
            block_number=block_number,
            block_time=block_time,
            fee=_gas_fee(receipt),
            finality_detail=finality_detail,
        )

    async def fetch_receipts(
        self, tx_hashes: list[str]
    ) -> tuple[dict[str, ExecutionReceipt], dict[str, str]]:
        receipts: dict[str, ExecutionReceipt] = {}
        failures: dict[str, str] = {}
        for tx_hash in dict.fromkeys(tx_hashes):
            try:
                receipts[tx_hash] = await self.fetch_receipt(tx_hash)
            except ProviderError as exc:
                failures[tx_hash] = f"{exc.error_class.value}: {exc}"
                if exc.error_class is ProviderErrorClass.budget_exhausted:
                    break
        return receipts, failures

    async def verify_execution(self, events: list[NormalizedTransfer]) -> ExecutionVerification:
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


# -- module-level decode helpers ----------------------------------------------


def _hex_to_int(value: str) -> int:
    return int(value, 16)


def _hex_to_int_or_none(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _hex_timestamp(value: Any) -> dt.datetime:
    return dt.datetime.fromtimestamp(_hex_to_int(value), tz=dt.UTC)


def _address_to_topic(address: str) -> str:
    """Left-pad a 20-byte address to a 32-byte indexed-parameter topic."""
    return "0x" + "0" * 24 + address[2:].lower()


def _topic_to_address(topic: Any) -> str | None:
    """Read a 20-byte address back out of a 32-byte indexed topic.

    Strict: the topic must be exactly 32 bytes (66 chars including ``0x``) and
    its upper 12 bytes must be zero. A topic that fails either check is not a
    plain indexed address -- it is not guessed at, the log is skipped instead
    (relevant to malformed logs and to any non-standard event that happens to
    share the ``Transfer`` topic0 by coincidence).
    """
    if not isinstance(topic, str) or len(topic) != 66 or not topic.startswith("0x"):
        return None
    body = topic[2:]
    if not all(c in "0123456789abcdefABCDEF" for c in body):
        return None
    if body[:24] != "0" * 24:
        return None
    try:
        canonicalize_evm("0x" + body[24:])
    except AddressValidationError:
        return None
    return "0x" + body[24:].lower()


def _decode_uint256(data: Any) -> int | None:
    """A ``Transfer`` event's non-indexed ``value`` is exactly one 32-byte word."""
    if not isinstance(data, str) or not data.startswith("0x") or len(data) != 66:
        return None
    try:
        return int(data, 16)
    except ValueError:
        return None


def _decode_abi_string(data: str | None) -> str | None:
    """Decode an ABI ``string`` return value; ``bytes32`` for older tokens.

    Strict: anything that is not a well-formed encoding yields ``None`` rather
    than a guessed string.
    """
    if not isinstance(data, str) or not data.startswith("0x"):
        return None
    try:
        raw = bytes.fromhex(data[2:])
    except ValueError:
        return None
    try:
        if len(raw) == 32:
            return raw.rstrip(b"\x00").decode("utf-8") or None
        if len(raw) < 64:
            return None
        offset = int.from_bytes(raw[:32], "big")
        if offset + 32 > len(raw):
            return None
        length = int.from_bytes(raw[offset : offset + 32], "big")
        body = raw[offset + 32 : offset + 32 + length]
        if len(body) != length:
            return None
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


_URL_PATTERN = re.compile(r"(?i)\b(?:https?|wss?)://[^\s'\"<>]+")

#: Path segments or query values this short are too generic to redact
#: without mangling ordinary words ("v1", "rpc"); a credential is longer.
_MIN_SECRET_FRAGMENT = 4


def _url_secret_fragments(url: str) -> list[str]:
    """Every part of ``url`` that could identify or authenticate the caller:
    the whole URL, host/netloc, user info, path segments, query values."""
    fragments = {url}
    try:
        parts = urlsplit(url)
    except ValueError:
        return [url]
    for piece in (parts.netloc, parts.hostname, parts.username, parts.password, parts.query):
        if piece:
            fragments.add(piece)
    fragments.update(segment for segment in parts.path.split("/") if segment)
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        fragments.update(item for item in (key, value) if item)
    return sorted(
        (f for f in fragments if len(f) >= _MIN_SECRET_FRAGMENT or f == url),
        key=len,
        reverse=True,
    )


def redact_url_text(text: str, fragments: list[str]) -> str:
    """Remove any URL, and every known fragment of the configured one."""
    redacted = _URL_PATTERN.sub("<redacted-url>", text)
    for fragment in fragments:
        redacted = redacted.replace(fragment, "<redacted>")
    return redacted


def _gas_fee(receipt: dict[str, Any]) -> int | None:
    gas_used = _hex_to_int_or_none(receipt.get("gasUsed"))
    gas_price = _hex_to_int_or_none(receipt.get("effectiveGasPrice"))
    if gas_used is None or gas_price is None:
        return None
    return gas_used * gas_price


__all__ = [
    "BLOCK_RESOLUTION_CURRENT",
    "BLOCK_RESOLUTION_LEGACY",
    "EVM_NETWORKS",
    "TRANSFER_TOPIC",
    "EvmNetworkConfig",
    "EvmRpcAdapter",
    "redact_url_text",
]
