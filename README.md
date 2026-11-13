# TermGate

Ask a published policy one question and get an auditable answer: does the clause you care about meet the threshold you set, and by how much?

A company that signs other people's terms does this check by hand every day. Someone opens the vendor's policy page, finds the sentence about notice or refund or cure, reads the number, and compares it to the limit procurement set. The answer ends up in an email and nobody can recompute it later. TermGate turns that into a record on chain that anyone can re-derive from the same page.

```
open_check  ->  resolve  ->  SATISFIES | FAILS | UNCOMPARABLE  +  gap
```

## What it does

`open_check` pins one page, one policy field, one comparison, and one threshold. `resolve` reads that page under consensus, transcribes the number the page prints for that field, and derives the verdict by integer comparison.

| Verdict | Meaning |
|---|---|
| `SATISFIES` | The published value meets the threshold, with headroom equal to `gap`. |
| `FAILS` | The published value misses the threshold, by `gap`. |
| `UNCOMPARABLE` | The page states a different unit, so no honest comparison exists. |

`gap` is always a non-negative distance and the verdict carries the side. Nothing in the stored state depends on negative integer encoding.

A check is idempotent per tuple: opening the same page, field, operator, threshold, and unit twice returns the same id instead of creating a second record. Resolving an already settled check re-reads the page and bumps `version`, so a changed page shows up as a changed verdict with a new `checked_at` rather than silently overwriting history.

## Live proof

Deployed on GenLayer Studio, contract `0x266AFc5b6ab20B73091891723A678B78AF540008`, deployment transaction `0xe9b61cca1ab6d22600fa5c512d612dc4c1b92f4022c48c3ff3e43e901815f603` (FINALIZED, MAJORITY_AGREE).

One clause on the Hetzner terms page: "The contract may be terminated by either party with 30 days' notice to the end of the month, without specifying any reasons."

| Check | Request | Verdict | gap | Value read |
|---|---|---|---|---|
| `C1` | `NOTICE_PERIOD`, `MIN`, 45, `DAYS` | `FAILS` | 15 | 30 DAYS |
| `C2` | `NOTICE_PERIOD`, `MIN`, 30, `DAYS` | `SATISFIES` | 0 | 30 DAYS |
| `C3` | `NOTICE_PERIOD`, `MAX`, 14, `DAYS` | `FAILS` | 16 | 30 DAYS |

Each row is two write transactions, and every one of them finished FINALIZED with MAJORITY_AGREE:

| Step | Transaction |
|---|---|
| deploy | `0xe9b61cca1ab6d22600fa5c512d612dc4c1b92f4022c48c3ff3e43e901815f603` |
| open `C1` | `0xe790bde3ac321c06a64592f127de813d9cf6802613b4af4122effd9f1d4cbcee` |
| resolve `C1` | `0xa9092b688e64710295502ca87301b45e39e1295481240f74226af2600d9d54f0` |
| open `C2` | `0xdc4637e4fa886e146fd85f480fe662b960cb1d60c084dda7b03fbbfc7631a4ec` |
| resolve `C2` | `0xa6e6de323bd92930317fdc0b8d4ce0e68ca5098baa85fe7e9ce65ae74c65dfee` |
| open `C3` | `0x2c96c4ee3648ec46b8c798414c573c53b84cdf54681988be19e5cb3b84933b41` |
| resolve `C3` | `0x10933596643992e13e2b7efd2508184377f0fca06124ae38ef438df7844a624b` |

The same page produces three different verdicts, because the caller set three different requirements. That is the point: the contract answers your question about their text, and it answers it the same way for everyone who asks the same question.

## Why the verdict is not written by a model

The model never sees the threshold and is never asked whether the requirement is met. Its entire job is to transcribe three fields: a number, a unit, and the sentence that prints that number. The comparison, the gap, and the verdict are computed by the contract in integer arithmetic, so any node can reproduce all three without consulting a model.

Before a settled answer is stored, an independent validator does four things on its own fetch of the page:

1. It requires the cited sentence to exist on the page it fetched itself. A hallucinated or borrowed sentence fails here.
2. It requires that sentence to print the number stored beside it. A real sentence carrying a different figure fails here.
3. It requires the sentence to contain a keyword for the field being read, so a number lifted from the wrong clause fails here.
4. It re-runs the whole read and requires an identical state, verdict, gap, reason, and value.

Only then is the record written. A check that cannot be grounded is stored as `UNRESOLVED` with a reason, never as a pass.

Units are never converted. A page that says "one month" against a threshold in days yields `UNCOMPARABLE`, not a guessed 30. Refusing to compare is a decision, not a missing feature: an honest refusal is more useful to a compliance team than a confident conversion.

## API

Writes:

| Method | Arguments | Effect |
|---|---|---|
| `open_check` | `source_url`, `topic`, `op`, `threshold`, `unit` | Creates a pending check, returns its id such as `C1`. Idempotent per tuple. |
| `resolve` | `check_id` | Reads the page under consensus, stores the verdict, returns the new state. |

Views:

| Method | Returns |
|---|---|
| `get_check(check_id)` | The whole record: request, state, verdict, reason, gap, value, unit, quote, `checked_at`, `version`. |
| `verdict(check_id)` | Verdict string, empty while pending. |
| `gap(check_id)` | Non-negative distance to the threshold. |
| `passes(check_id)` | `true` only for `SATISFIES`. |
| `list_checks()` | Ids in creation order. |
| `count()` | Number of checks stored. |
| `rules()` | The accepted vocabulary and limits, so a client can validate before writing. |

## Vocabulary

Topics and the words that must appear in the citing sentence:

| Topic | Keywords |
|---|---|
| `NOTICE_PERIOD` | terminat, notice, renew, cancel, non-renewal, not renew |
| `CURE_PERIOD` | cure, breach, remedy, remedies, rectify |
| `REFUND_WINDOW` | refund, money back, return, reimburse |
| `DATA_RETENTION` | retain, retention, delete, deleted, erase, store, stored, keep |

Operators: `MIN` (satisfied when value >= threshold), `MAX` (satisfied when value <= threshold).

Units: `DAYS`, `MONTHS`.

States: `PENDING`, `SETTLED`, `UNRESOLVED`.

Reasons for an unresolved check: `EXTRACTION_FAILED`, `FIELD_NOT_STATED`, `QUOTE_NOT_GROUNDED`, `QUOTE_NOT_SUPPORTING`, `UNIT_MISMATCH`, `BAD_OPERATOR`.

Errors raised by the writes: `URL_MUST_BE_HTTPS`, `URL_TOO_LONG`, `UNKNOWN_TOPIC`, `UNKNOWN_OPERATOR`, `THRESHOLD_INVALID`, `UNKNOWN_UNIT`, `CAPACITY_REACHED`, `UNKNOWN_CHECK`, `SOURCE_EMPTY_OR_UNREADABLE`.

Limits: URL up to 300 characters, threshold from 1 to 10000, pages from 200 to 7000 characters are read, quotes up to 400 characters, up to 2000 checks.

## Try it

Deploy `contracts/termgate.py` in GenLayer Studio, then write:

```
open_check("https://www.hetzner.com/legal/terms-and-conditions/", "NOTICE_PERIOD", "MIN", 45, "DAYS")
-> "C1"

resolve("C1")
-> "SETTLED"

get_check("C1")
-> {"id": "C1", "state": "SETTLED", "verdict": "FAILS", "gap": 15, "value": 30, "unit": "DAYS",
    "quote": "The contract may be terminated by either party with 30 days' notice to the end of the month, ..."}
```

Change the threshold to 30 and the same page satisfies the check. Change the operator to `MAX` with 14 and it fails the other way.

## Tests

`tests/direct/test_termgate.py` runs 33 tests against the contract with the model and the page fetch stubbed, covering the decision layer, the window selection, grounding and support checks, idempotency, capacity, input validation, and a validator that must reject a leader whose quote is borrowed from another clause.

```
pip install -r requirements.txt
pytest tests/direct -q
genvm-lint check contracts/termgate.py
```

## Honest limits

- One number per field per page. When a page states several figures, the one in the clearest, most specific sentence wins, and the stored quote shows which sentence that was.
- Days and months only. Anything else is out of scope by construction.
- A page behind a bot wall or rendered by JavaScript reverts as unreadable instead of producing a value.
- A stored verdict is a claim about the page at `checked_at`. Pages change, and re-resolving is how you see that they did.

## Layout

```
contracts/termgate.py           the contract, no dependencies outside the GenLayer runtime
tests/direct/test_termgate.py   direct-mode tests
gltest.config.yaml              localnet and studionet targets
requirements.txt                gltest and the linter
```
