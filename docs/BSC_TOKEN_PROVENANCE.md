# BSC validation token: provenance record

Token used for the Task 06 BNB Smart Chain validation
(`var/live-validation/20260926-bsc-usdt-live-002/`, replay
`var/live-validation/20260926-bsc-usdt-replay-001/`).

| Field | Value |
|---|---|
| Network | BNB Smart Chain Mainnet (`bsc`, chain id 56, `eip155:56`) |
| Contract | `0x55d398326f99059fF775485246999027B3197955` |
| Use in this repository | **Technical validation token; issuer/provenance not independently established.** |

## Technical facts (read on chain, recorded and replayed)

Read through the configured provider after `eth_chainId` returned `0x38` (56), at
block tag `latest`, on 2026-09-26. The same checks are in the LIVE bundle's
`raw/` exchanges and `token-verification.json`, and the replay re-derived them
from those recorded exchanges with identical results.

| Check | Result |
|---|---|
| `eth_getCode` | non-empty, 4413 bytes, sha256 `a5a6d887c581c25cba4104e4281a530044ba59d718e62cdaa80ef89900299d50` |
| `decimals()` | 18 |
| `symbol()` | `USDT` |
| `name()` | `Tether USD` |

`symbol()` and `name()` are the contract's own claims about itself. They do not
establish who issued the token or what backs it.

## Provenance sources checked (retrieved 2026-09-26)

1. **Binance Support announcement, "Binance Opens BEP2 and BEP20 (Binance Smart
   Chain) Withdrawals and Deposits for Multiple Assets"**, dated 2020-09-10:
   <https://www.binance.com/en/support/articles/daca7c991d5f4c45a4d1083f70912515>.
   Lists `USDT` under BEP20 and links it to this exact contract. This is
   first-party Binance evidence that Binance supports this contract as its
   BEP-20 "USDT" for deposits and withdrawals. The announcement does not
   say who issues the token or what backs it, and it does not use the term
   "Binance-Peg".
2. **Tether, "Supported Protocols"**:
   <https://tether.to/en/supported-protocols/>. The BNB Smart Chain section lists
   only XAU₮ (`0x21cAef8A43163Eea865baeE23b9C2E327696A3bf`). **This contract does
   not appear on the page.** Nothing found here supports calling it
   Tether-issued USD₮.
3. **BscScan** labels the contract "Binance-Peg BSC-USD (BSC-USD)". BscScan is a
   third-party explorer; its label is recorded as context only and was not
   treated as authoritative.

## Conclusion

- The contract is **not** described here as native Tether-issued USDT: Tether's
  own list does not include it.
- Binance's own announcement ties it to Binance's BEP-20 "USDT" deposits and
  withdrawals. The "Binance-Peg" name comes from BscScan, not from a checked
  Binance source.
- Its issuer, backing, and reserve arrangement were not independently
  established. It is used only as a high-volume technical validation token for
  BEP-20 `Transfer` tracing. Amounts are shown as the token's own units, never
  as US dollars.
