"""A structural, optional capability: receipt-backed execution verification.

Not part of ``ChainAdapter`` itself. ``TronGridAdapter`` and ``EvmRpcAdapter``
each implement ``fetch_receipts``/``tx_hash_from_reference`` independently,
with different acquisition mechanics underneath (TRON's solidified/head
receipt endpoints vs. EVM's single receipt endpoint plus separate finality
tags). ``live_validation.py`` needs only this shared shape to verify execution
for whichever adapter a run actually used, so it is expressed here as a
``Protocol`` rather than added to ``ChainAdapter``: adding a method to the
central adapter contract for every future capability only one or two
adapters share would make the interface accrete chain-specific concepts
(AGENTS.md: use existing abstractions; do not enlarge a shared contract for
one implementation's needs). Both existing adapters already satisfy this
structurally, with no changes to either class.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.adapters.base import ExecutionReceipt


@runtime_checkable
class ReceiptVerifiable(Protocol):
    """An adapter that can turn transaction hashes into execution receipts."""

    async def fetch_receipts(
        self, tx_hashes: list[str]
    ) -> tuple[dict[str, ExecutionReceipt], dict[str, str]]: ...

    @classmethod
    def tx_hash_from_reference(cls, reference: str) -> str | None: ...


__all__ = ["ReceiptVerifiable"]
