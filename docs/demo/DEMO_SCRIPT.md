# TraceCrypt: 5-minute demo script

Voice-over for `tracecrypt-demo.mp4`. Timestamps match the scenes and on-screen captions in the video, so you can read this over the recording. At a normal pace (about 140 words a minute) each block fits its time slot.

All data in the demo is synthetic. "Northwind Exchange" is a fictional exchange used only for the demo.

---

**0:00 – 0:17 · Intro card**

> A fraud victim can usually give the police only one thing: the crypto wallet address they paid. This is TraceCrypt. It takes that address, follows the money on the blockchain, and tells the investigator which exchange received it, with evidence to back it up.

**0:17 – 0:34 · Sign in**

> Everything runs on one laptop. We sign in as an investigator. Cases are scoped to the investigator's own unit, so one team can't see another team's complaints.

**0:34 – 1:04 · Overview**

> The overview is the investigator's home screen. The top row shows the saved evidence, the transfers in focus, reviewed exchange boundaries and behaviour patterns.
>
> The dark panel is a fund-flow preview: the reported wallet on the left, the exchange it reached on the right.
>
> The evidence brief sums it up in plain language: a service boundary was reached, the triage priority, how complete the coverage is, and which patterns need review.

**1:04 – 1:46 · Complaint intake**

> This is how a complaint comes in. In a real deployment it would arrive from an NCRP or SAHYOG-style complaint feed through our intake API. Here we fill in a synthetic example.
>
> It records the fraud type (investment scam, task-based fraud, sextortion, ransomware, phishing), the blockchain network, the reported wallet and the token.
>
> Submit and queue. The complaint becomes a durable job, and a background worker picks it up by itself. A few seconds later it has succeeded, and it has already raised an alert: a receiving exchange was observed.

**1:46 – 2:50 · Trace workspace**

> Let's open the result. At the top is the answer the investigator needs: the nearest receiving exchange. Here it's Northwind Exchange, five verified transfer hops from the reported wallet, reached through intermediary wallets, with the deposit address. We only name an exchange when a reviewed, dated label supports it.
>
> Below that is the case summary: nine verified transfers, one exchange boundary, a triage risk of Medium, and coverage that is complete within the scope we traced.
>
> This is the fund-flow graph. The money leaves the reported wallet and splits across intermediary wallets. One branch has no label, so it's shown as unresolved instead of guessed. The main path reaches a candidate and then the reviewed exchange.
>
> The evidence inspector lets the investigator click any wallet and see its role and every transfer in and out.

**2:50 – 3:22 · Evidence tabs**

> "Patterns and intermediaries" flags laundering behaviour: fan-in, fan-out, rapid and repeated forwarding, peeling, and cycles. These are leads for the investigator, not verdicts.
>
> The transfer ledger keeps exact amounts, timestamps and event IDs for every hop. Scope and limitations says clearly what the trace did not cover. And next actions gives concrete steps: preserve the evidence, review the scope, and prepare the request to the exchange.

**3:22 – 3:45 · Reports and export**

> Every trace produces a standard investigation report. This is the report itself, with the label source and the exact transfers.
>
> One click exports the full evidence bundle: JSON, HTML, PDF and CSV, with a SHA-256 checksum manifest so any change to the files can be detected. Freeze and preservation requests to the exchange are drafted for an officer to review. Nothing is sent or frozen automatically.

**3:45 – 4:10 · Cases and monitoring**

> Every complaint is a case. We select this one and put the reported wallet on a watch, because fraudsters often reuse wallets. Poll now: polling is checkpointed and de-duplicated, so each new transfer raises exactly one alert. Here are the alerts.

**4:10 – 4:25 · Cross-case leads**

> Cross-case leads compares saved cases for shared wallets. If the same mule wallet or exchange shows up across many complaints, the investigator sees the link.

**4:25 – 4:40 · Cross-chain evidence**

> Funds often jump between blockchains. For USDC bridged from Ethereum to Base through Circle's CCTP bridge, TraceCrypt checks both sides (nonce, domains, recipient and amount) before it continues the trace on the new chain.

**4:40 – 4:51 · AI/ML risk ranking**

> For risk, an IsolationForest model ranks unusual fund-flow graphs. It needs at least 25 saved wallets, and when there aren't enough it says so rather than showing a made-up score.

**4:51 – 4:56 · Capabilities**

> The capabilities page shows honestly what is live, partial or not yet configured, including the NCRP and SAHYOG connectors.

**4:56 – 5:04 · Outro**

> TraceCrypt: from a reported wallet, to the traced funds, to the nearest exchange, to an evidence package. Thank you.

---

## Recording the voice-over

1. Open `tracecrypt-demo.mp4` in any editor (Kdenlive, Shotcut, Clipchamp, CapCut).
2. Record your narration block by block, starting each block at its timestamp.
3. If a block runs long, trim the words rather than speeding up. The on-screen captions carry the key points either way.

To re-record the screen capture yourself, start the app (`python launch.py --prepare --with-worker`) and run `scripts/record_demo.py` (see the header of that file).
