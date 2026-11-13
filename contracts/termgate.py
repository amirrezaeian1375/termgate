# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""
TermGate - does a published policy meet the threshold you require?

The problem
-----------
Every organisation has written limits it has to check against other people's
published terms: we may only accept contracts that allow termination on at most
30 days notice, we require at least 30 days before data is deleted, we cap cure
periods at 14 days. Today a person opens each page, finds the sentence, reads the
number, and compares it by hand. It is slow, it is unauditable, and the answer
lives in an email.

This contract turns that check into a stored verdict that anyone can recompute.

What it does
------------
`open_check` pins one page, one policy field, one comparison, and one threshold.
`resolve` reads the page under consensus, transcribes the value the page prints
for that field, and derives one of three verdicts by integer comparison:

    SATISFIES     the published value meets the threshold
    FAILS         it does not
    UNCOMPARABLE  the page states a different unit, so no honest comparison exists

The verdict is never written by a model. The model transcribes a number, a unit,
and the sentence that prints it. The comparison, the gap, and the verdict are
computed by the contract in integer arithmetic, so a validator can reproduce all
three without asking any model for an opinion.

Why this is not a prompt wrapper
--------------------------------
* The model is not asked whether the requirement is met. It is not told the
  threshold at all. It cannot influence the verdict except by misreading a number
  that must then appear in the sentence it cites.
* Three independent checks stand between a claim and storage: the sentence must
  exist on the validator's own fetch of the page, it must print the number that
  was stored next to it, and it must contain a keyword for the field being read.
* The validator then re-runs the whole pipeline and requires an identical
  verdict, an identical gap, and an identical reason for a failure.
* Units are never converted. A page that says "one month" against a threshold in
  days yields UNCOMPARABLE rather than a guessed 30. Refusing to compare is a
  design decision, not a gap.

Honest limits
-------------
* One number per field per page. A page that states several figures for the same
  field is read as the one in the clearest, most specific sentence the model
  finds; that choice is recorded through the stored quote, so a reader can see
  which sentence won.
* Days and months only. Anything else is out of scope by construction.
* A page behind a bot wall or a JavaScript app reverts as unreadable instead of
  producing a value.
* A stored verdict is a claim about the page at `checked_at`. Pages change.
"""

import json
from dataclasses import dataclass

from genlayer import *

# What a check is doing
S_PENDING = "PENDING"
S_SETTLED = "SETTLED"
S_UNRESOLVED = "UNRESOLVED"

# The three verdicts a settled check can hold
V_SATISFIES = "SATISFIES"
V_FAILS = "FAILS"
V_UNCOMPARABLE = "UNCOMPARABLE"

# Comparison directions
OP_MIN = "MIN"  # published value must be at least the threshold
OP_MAX = "MAX"  # published value must be at most the threshold

OPS = (OP_MIN, OP_MAX)

# Units the contract is willing to compare
U_DAYS = "DAYS"
U_MONTHS = "MONTHS"
U_UNKNOWN = "UNKNOWN"

UNITS = (U_DAYS, U_MONTHS)

MAX_URL_CHARS = 300
MIN_PAGE_CHARS = 200
MAX_PAGE_CHARS = 7000
MAX_QUOTE_CHARS = 400
MAX_CHECKS = 2000
MAX_LIST = 60
MIN_THRESHOLD = 1
MAX_THRESHOLD = 10000
MAX_VALUE = 10000

# A finite, named set of policy fields. Each one carries the words that must be
# present in the citing sentence, so the "is this sentence about the right thing"
# test is a deterministic check and not a second opinion from a model.
TOPIC_NOTICE = "NOTICE_PERIOD"
TOPIC_CURE = "CURE_PERIOD"
TOPIC_REFUND = "REFUND_WINDOW"
TOPIC_RETENTION = "DATA_RETENTION"

TOPIC_WORDS = {
    TOPIC_NOTICE: (
        "terminat",
        "notice",
        "renew",
        "cancel",
        "non-renewal",
        "not renew",
    ),
    TOPIC_CURE: (
        "cure",
        "breach",
        "remedy",
        "remedies",
        "rectify",
    ),
    TOPIC_REFUND: (
        "refund",
        "money back",
        "return",
        "reimburse",
    ),
    TOPIC_RETENTION: (
        "retain",
        "retention",
        "delete",
        "deleted",
        "erase",
        "store",
        "stored",
        "keep",
    ),
}

TOPICS = (TOPIC_NOTICE, TOPIC_CURE, TOPIC_REFUND, TOPIC_RETENTION)

TOPIC_QUESTIONS = {
    TOPIC_NOTICE: "how much notice a party must give to terminate the agreement or decline to renew it",
    TOPIC_CURE: "how long a party has to cure or remedy a breach before further action",
    TOPIC_REFUND: "how long a customer has to ask for a refund or return a product",
    TOPIC_RETENTION: "how long the provider keeps or retains customer data before deleting it",
}


def _as_text(value) -> str:
    return value if isinstance(value, str) else ""


def _norm(text: str) -> str:
    """Pure string normalization, identical on every node."""
    if not isinstance(text, str):
        return ""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-")
    return " ".join(t.lower().split())


# --------------------------------------------------------------- comparison
# The whole verdict engine. Pure integers, no model, no clock, no locale.


def compute_verdict(op: str, threshold: int, value: int, value_unit: str, want_unit: str) -> dict:
    """Compare a transcribed value against the caller's threshold.

    Returns a verdict object. This function is the entire decision layer, and it
    is deterministic on purpose: every node can call it and get the same answer.

    `gap` is how far the value sits from the threshold, always as a non-negative
    count, and the verdict says which side it landed on. Keeping the distance
    unsigned means the stored state cannot depend on how a particular chain
    encodes negative integers.
    """
    if value_unit != want_unit:
        # Steps, percentages, weeks, business days: none of them compare to the
        # threshold the caller asked about. Guessing a conversion would turn a
        # refusal into a wrong answer, so the contract declines to compare.
        return {"verdict": V_UNCOMPARABLE, "reason": "UNIT_MISMATCH", "gap": 0}
    if op == OP_MIN:
        headroom = value - threshold
    elif op == OP_MAX:
        headroom = threshold - value
    else:
        return {"verdict": V_UNCOMPARABLE, "reason": "BAD_OPERATOR", "gap": 0}
    gap = headroom if headroom >= 0 else -headroom
    if headroom >= 0:
        return {"verdict": V_SATISFIES, "reason": "", "gap": gap}
    return {"verdict": V_FAILS, "reason": "BELOW_THRESHOLD", "gap": gap}


def _topic_ok(quote: str, topic: str) -> bool:
    words = TOPIC_WORDS.get(topic, ())
    if len(words) == 0:
        return False
    text = _norm(quote)
    for word in words:
        if word in text:
            return True
    return False


def _num_tokens(text: str) -> list:
    out = []
    cur = ""
    for ch in text:
        if ch.isdigit():
            cur += ch
        else:
            if cur != "":
                out.append(cur)
            cur = ""
    if cur != "":
        out.append(cur)
    return out


def _is_grounded(page_text: str, quote: str) -> bool:
    q = " ".join(_as_text(quote).split())
    if len(q) < 12 or len(q) > MAX_QUOTE_CHARS:
        return False
    return _norm(q) in _norm(page_text)


def _quote_supports(quote: str, value: int, topic: str) -> bool:
    """The sentence must be about this field and must print this number."""
    if not _topic_ok(quote, topic):
        return False
    if value <= 0:
        return False
    return str(int(value)) in _num_tokens(_norm(quote))
