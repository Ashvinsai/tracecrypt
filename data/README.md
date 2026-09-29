# Label anchors

`anchors.csv` is the only place an address-to-entity claim the tracer reads may
live. The tracer contains no addresses (Stage 1 gate: swapping the supplied
example must exercise the same parser and tracer).

Every row needs `source_reference`, `retrieval_date`, and `methodology`; the
loader rejects a row missing any of them.

## Current contents

**Synthetic only.** Both rows describe a fictional exchange invented for
`fixtures/tron_synthetic_case_alpha.json`, marked `label_set_version=synthetic-0`.
They are not evidence about any real service and must never be imported into a
production label set or sent to a live provider.

## Adding a real anchor (Stage 1 human preparation)

A real row needs, before it is added:

1. A primary disclosure — an exchange's own proof-of-reserves file or signed
   address verification, not an aggregator's copy of one.
2. The disclosure's date, and the file's hash where one is preserved.
3. The role the source actually supports. A reserve disclosure supports a dated
   ownership claim; it does **not** establish that an address is a hot wallet or
   a customer deposit address.
4. `review_state=accepted` only after a human has opened the source and checked it.

Two aggregators repeating one source are not independent corroboration.

## The three sets (Stage 2, D017)

`import_anchors` never writes `anchors.csv`. It writes three separate files,
and what a document is decides which one a row lands in:

| File | What is in it |
|---|---|
| `verified_anchors.csv` | claims from a service's own disclosure or signed verification |
| `deposit_candidates.csv` | behavioural candidates; shown, never trusted, never terminating a branch |
| `independent_review.csv` | leads and evaluation material: aggregator copies, authorized observations |

`sources/` holds the original downloaded file under `<hash16>-<name>` plus
`manifest.csv`. Every imported row names its source hash and the file it came
from.

Rows arrive `review_state=unreviewed` whatever the source. A human opens the
source, checks it, and sets `accepted` — an importer never does. Only an
accepted `service_control` row, valid at the observed moment, can end a trace
branch.

```bash
cd api && uv run python ../scripts/import_anchors.py \
    --file ~/Downloads/okx-por-tron.csv \
    --url https://www.okx.com/proof-of-reserves/download \
    --kind proof_of_reserves \
    --disclosed 2026-06-30 \
    --methodology "Selected the rows explicitly on TRON." \
    --label-set-version okx-por-2026-06
```

Nothing is written without `--write`. The dry run prints each row's destination,
each rejection and its reason, and any address whose apparent corroboration is
one source repeated.

## Reviewing what was imported (D018)

Imported rows are inert until a human accepts them. `review_candidates` is that
step, and `review_log.csv` records every decision — who, when, from which state
to which, what they opened, and why.

```bash
cd api && uv run python ../scripts/review_candidates.py list
cd api && uv run python ../scripts/review_candidates.py decide \
    --address TXXXX --action accept \
    --reviewer "investigator-1" \
    --rationale "Found the address on the dated reserve file." \
    --evidence https://www.okx.com/proof-of-reserves/download \
    --write
```

An accept must name the row's own source in `--evidence`, and the preserved copy
is re-hashed first: a file that changed since import is not the file anyone read.
Actions are `accept`, `reject`, `quarantine` and `needs_evidence` — the last
leaves the row in the queue, so "we looked and it was not enough" stays
distinguishable from "nobody has looked".

Two things review cannot do. A deposit candidate never becomes an anchor,
whatever the corroboration: that needs a document naming the address, which is an
import. And promoting a lead into the anchors needs evidence independent of the
pattern that produced it, not more of the same pattern.
