"""Both adapters satisfy ``ReceiptVerifiable`` structurally (no ChainAdapter change).

This is the regression test constraint 2 asked for before generalizing
``live_validation.py``: proof that the shared shape ``live_validation.py``
needs already exists on both adapters, so the generalization can rely on a
``Protocol`` instead of adding a method to ``ChainAdapter`` itself.
"""

from __future__ import annotations

from app.adapters.evm import EvmRpcAdapter
from app.adapters.execution import ReceiptVerifiable
from app.adapters.tron import TronGridAdapter


def test_tron_adapter_satisfies_receipt_verifiable() -> None:
    adapter = TronGridAdapter("https://api.trongrid.io", api_key="x")
    assert isinstance(adapter, ReceiptVerifiable)


def test_evm_adapter_satisfies_receipt_verifiable() -> None:
    adapter = EvmRpcAdapter("https://rpc.example.test", network_key="ethereum")
    assert isinstance(adapter, ReceiptVerifiable)
