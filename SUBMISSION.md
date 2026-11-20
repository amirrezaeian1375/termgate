# TermGate

**Category:** Intelligent Contracts
**Network:** GenLayer Studionet

## The problem

Every company that signs someone else's terms has a list of limits it must stay
inside. Termination notice of at most 30 days. A refund window of at least 30
days. A cure period of at most 14 days. Data deleted no later than 30 days after
the contract ends.

The answer always exists, in public, in a sentence on the vendor's policy page.
Today a person opens the page, finds the sentence, reads the number, and compares
it by hand. The result goes into an email. Nobody can recompute it a month later,
and nobody can see which sentence it came from.

TermGate turns that one check into a record on chain: a page, a field, an
operator, and a threshold go in; a verdict, a distance, and the exact sentence
that proves it come out.

## What it does

`open_check(source_url, topic, op, threshold, unit)` pins one comparison and
returns an id. `resolve(id)` reads the page under consensus and stores the
answer. The model never sees the threshold and is never asked whether the
requirement is met.

```
SATISFIES     the published value meets the threshold, gap is the headroom
FAILS         it does not, gap is the shortfall
UNCOMPARABLE  the page states a different unit, so no honest comparison exists
```

`gap` is stored unsigned and the verdict carries the side, so nothing depends on
how the chain encodes negative integers.

Live, on the Hetzner terms page, one clause read three times under three
different requirements:

| check | request | verdict | gap | value |
|---|---|---|---|---|
| `C1` | `NOTICE_PERIOD`, `MIN`, 45, `DAYS` | `FAILS` | 15 | 30 `DAYS` |
| `C2` | `NOTICE_PERIOD`, `MIN`, 30, `DAYS` | `SATISFIES` | 0 | 30 `DAYS` |
| `C3` | `NOTICE_PERIOD`, `MAX`, 14, `DAYS` | `FAILS` | 16 | 30 `DAYS` |

Same page, same model, three different questions, three different answers. That
is what separates this from a wrapper that asks a model for a judgement: the
question is the caller's, and the answer is arithmetic.

## Why the consensus layer is load bearing

* **The model transcribes, the contract decides.** The prompt asks for a number,
  a unit, and the sentence that prints that number. It does not contain the
  threshold and it does not ask for an opinion. The comparison, the gap, and the
  verdict are integer arithmetic inside the contract, so any node recomputes all
  three without a model.
* **A settled answer spends its evidence twice.** Every validator re fetches the
  page itself and then requires: (1) the cited sentence exists on that fresh
  copy; (2) the sentence prints the exact number stored beside it; (3) the
  sentence contains a keyword for the field being read; (4) when the stored unit
  is `DAYS` or `MONTHS`, the sentence prints that unit as a whole word. A
  borrowed sentence fails, a real sentence carrying a different figure fails, a
  sentence about the wrong clause fails, and a leader that stores `30 MONTHS`
  beside a sentence reading `30 days` fails.
* **The validator then re runs the whole pipeline** and requires an identical
  state, verdict, gap, reason, value, and unit. A disagreement is a no vote, not
  a stored guess.
* **A failure cannot become a pass.** A page with no clause, an ungrounded
  quote, or an unreadable source is stored as `UNRESOLVED` with a reason. Only
  `SATISFIES` makes `passes(id)` true.
* **Units are never converted.** One month against a threshold in days is
  `UNCOMPARABLE`, not a guessed 30. For a compliance question a refusal is worth
  more than a confident conversion, and the choice is visible in the state.
* **Untrusted page text is passed inside `<source>` tags** with an explicit
  instruction that it is data, never instructions. A test plants an injection and
  asserts it is not obeyed.

## Reading a page that is too long for a prompt

The live Hetzner page renders to roughly 47 thousand characters. Taking the top
of the page sends cookie banners, and sending everything makes the model skim.
The contract slides a 4000 character window over the page, scores each position
by the field's own keywords, and sends the best stretch. The quote is verified
against the whole page, not the window, so a clause just outside it is not
punished.

The weights are not cosmetic. `cancel` is worth almost nothing for window
selection while `terminat`, `renew`, `cure`, `breach`, `refund`, `retain`, and
`delete` are worth a thousand each. Consumer withdrawal sections repeat
"cancellation" on every line; scoring it highly dragged the window onto a
withdrawal page and the model read nothing at all. That was found against the
live host and fixed, and the comment in the source records it.

## State

One record per `url|topic|op|threshold|unit`, ids `C1`, `C2`, cap 2000, and
opening the same tuple twice returns the same id instead of creating a second
record. States are `PENDING`, `SETTLED`, `UNRESOLVED`. Resolving a settled check
re-reads the page and bumps `version`, so a page that changed shows up as a
changed verdict rather than an overwritten history.

Every failure is stored with a reason a reader can act on:
`EXTRACTION_FAILED`, `FIELD_NOT_STATED`, `QUOTE_NOT_GROUNDED`,
`QUOTE_NOT_SUPPORTING`, `UNIT_MISMATCH`, `BAD_OPERATOR`, plus
`SOURCE_EMPTY_OR_UNREADABLE` which reverts rather than storing a guess. Input
errors revert before any network use: `URL_MUST_BE_HTTPS`, `URL_TOO_LONG`,
`UNKNOWN_TOPIC`, `UNKNOWN_OPERATOR`, `THRESHOLD_INVALID`, `UNKNOWN_UNIT`,
`UNKNOWN_CHECK`, `CAPACITY_REACHED`.

`resolve` is open to any caller. The page is public, so anyone may refresh a
record; a caller can trigger a read but cannot pick the outcome.

`rules()` publishes the vocabulary and the limits on chain, so a client can
validate a request before writing one.

## Tests

39 direct mode tests, all passing. `genvm-lint check` clean, 9 methods (2 write,
7 view). They cover the decision layer on both operators, the unit mismatch
refusal, threshold and url validation, idempotent opening, a page whose clause
sits past 20000 characters of filler (where the mocked model only answers if the
clause actually reached the prompt), a quote borrowed from another clause, a
quote that exists but prints a different number, a quote that is off topic, a
quote that prints the number but not the stored unit, two injection attempts in
the page, a validator that must reject a leader whose verdict, gap, quote,
reason, or unit differs, a validator that must reject a unit outside the accepted
vocabulary, a validator that cannot fetch the page and so must not accept a
settled claim, and a re resolve that bumps `version`.

## What changed after review

The first submission stored a unit beside every value but let a validator settle
a record without binding that unit to the evidence. `_decide` returned it,
`_same_verdict` compared state, verdict, reason, gap, and value, and no check
required the quoted sentence to print the unit it was stored with. A leader could
keep `30 MONTHS` next to a sentence that reads `30 days` and every validator that
agreed on the other fields would vote yes.

That is closed in the consensus path, not in the docs:

* `UNIT_WORDS` and `_unit_ok(quote, unit)` match the stored unit as a whole word
  inside the cited sentence, allowing only short punctuation tails such as
  `days'` or `days.`.
* `_decide` refuses to settle a `DAYS` or `MONTHS` reading whose sentence does
  not print that unit, and stores `QUOTE_NOT_SUPPORTING` instead.
* `_same_verdict` compares the unit along with the state, verdict, reason, gap,
  and value.
* The validator settles only when the unit is in the accepted vocabulary,
  requires its own fetch of the page to print that unit inside the quoted
  sentence, and then requires its re-run to match it.
* `rules()` publishes the obligation as `evidence_rule`, so a caller can read the
  rule from the contract rather than from the source.

`test_validator_rejects_a_forged_unit` resolves a real check to `FAILS`, gap 15,
value 30, unit `DAYS`, then re-runs the validator with the same leader result and
the unit changed to `MONTHS`. The validator returns false.
`test_validator_rejects_an_unknown_unit` does the same with `BUSINESS_DAYS`, and
`test_a_unit_the_sentence_never_prints_is_not_a_reading` covers the leader side,
where such a reading is stored as `UNRESOLVED` with `QUOTE_NOT_SUPPORTING`.

`UNKNOWN` stays exempt on purpose. A page that states a period in business days or
weeks is an honest `UNCOMPARABLE` and can only ever settle that way, so demanding
a day or month word there would turn a valid refusal into `UNRESOLVED`. The
forgery risk lives in `DAYS` and `MONTHS`, and that is where the binding applies.

Because the change alters what validators accept, the contract was redeployed and
all three demo checks were resolved again. The address and transactions below
belong to the fixed source, and the code carried by the deployment transaction is
the code in this repository.

## Proof on chain

```
contract      0xe6aF0ad8e98bdfE3407eF2FF654d7a87449d4C18
deploy tx     0x7c2db42b1e99e8d1b126cda3cc6a0035d16ae1342bcf8eaf330872beb1ab0521  FINALIZED, MAJORITY_AGREE
open C1       0x8a0dae76d8c6053a240dbf8f06aaa1660ab724ff21095c5a8da4a9be34a2578b  C1
resolve C1    0x3ed2af6ec76fbc9e9c77242ac7e5bd15cab99e8764bd61355e4b3ba55c6f8d1d  SETTLED, FAILS, gap 15
open C2       0x8573614c4d9c5f038cd125e4bf7a395318e3d76b55b0274bd0907fedd5777269  C2
resolve C2    0xe55f5692e75b45b6ed61219709313b5214f13a01a958dc7ea96b7af88f00b516  SETTLED, SATISFIES, gap 0
open C3       0xa3199a4a4ed741d9952efe659f0c16afd6c1587dee97daa95735d25b33db9cf9  C3
resolve C3    0xb359a07413fb8c3e280004b17bd2f44f2f65ed0c5153959a6d73360ecb3911f9  SETTLED, FAILS, gap 16
```

All seven transactions are FINALIZED with MAJORITY_AGREE. The stored quote on
all three records is the same sentence, from the page itself:

```
The contract may be terminated by either party with 30 days' notice to the end
of the month, without specifying any reasons.
```

At deploy time the contract was opened in Studio from the file in
`contracts/termgate.py`. The contract code carried by the deployment transaction
matches that file byte for byte after line ending normalization, with the
trailing newline dropped by the Studio editor.

## Limits, stated honestly

* One number per field per page. When a page states several figures for the same
  field, the one in the clearest, most specific sentence wins, and the stored
  quote shows which sentence that was.
* Days and months only. Anything else is out of scope by construction.
* A page behind a JavaScript app or a bot wall reverts as unreadable instead of
  producing a number.
* A stored verdict is a claim about the page at `checked_at`. Pages change, and
  re resolving is how you see that they did.
* A check that fails under `MAX` records the reason `BELOW_THRESHOLD` even though
  the value is above the ceiling. The verdict and the gap are correct; the reason
  string is a label that predates the second operator and is being cleaned up.
