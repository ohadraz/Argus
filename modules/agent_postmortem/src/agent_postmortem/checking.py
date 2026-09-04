"""What is wrong with an answer, said in words the model can act on.

Two faults, checked together because they are answered together. A required
field the model left out is the obvious one. The other is a figure in the
executive summary that Argus never computed: the document's columns are safe
by construction, but the summary is published as written, so a fluent sentence
naming an invented number reaches the reader least able to check it.

Faults are phrased for the model rather than for a log. "Missing field" and
"you wrote $1.2M, which is not the figure" are both things a second attempt
can be about; "invalid answer" is not, and a model told only that its answer
was wrong rewrites the part it liked least.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Final

from agent_postmortem.prompting import EXECUTIVE_SUMMARY_FIELD, REQUIRED_FIELDS

# A currency amount as prose writes one: a dollar sign, then digits with
# whatever grouping and decimals the writer felt like. Deliberately only `$` -
# the estimate is in dollars, and a pattern chasing every currency symbol
# would be inventing a problem Argus does not have.
CURRENCY_IN_PROSE: Final = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")

# How far a stated figure may sit from the computed one and still be the same
# figure. Wide on purpose: a summary saying "roughly $340" about an estimate of
# $336 is doing exactly what it should, and a check that failed it would teach
# the next prompt to print the number to the cent.
FIGURE_TOLERANCE: Final = 0.05


def faults_in(answer: dict[str, Any], estimate: Decimal | None) -> list[str]:
    """Everything about this answer that has to be put right, or nothing."""
    return _missing_fields(answer) + _invented_figures(answer, estimate)


def _missing_fields(answer: dict[str, Any]) -> list[str]:
    return [f"the field [{field}] was missing from your answer"
            for field in REQUIRED_FIELDS
            if answer.get(field) is None]


def _invented_figures(answer: dict[str, Any], estimate: Decimal | None) -> list[str]:
    """Amounts in the summary that are not the one Argus arrived at.

    With no estimate every amount is invented by definition: there is nothing
    for it to agree with. That happens whenever the payment provider or the
    rate source could not be read, and a summary is not licensed to fill the
    gap with a number of its own.
    """
    summary = answer.get(EXECUTIVE_SUMMARY_FIELD)
    if not isinstance(summary, str):
        return []

    return [
        f"your summary states [{stated}], which is not a figure Argus computed - "
        f"say only what you were given, or say nothing about what it cost"
        for stated in CURRENCY_IN_PROSE.findall(summary)
        if not _agrees_with(stated, estimate)
    ]


def _agrees_with(stated: str, estimate: Decimal | None) -> bool:
    if estimate is None:
        return False

    return abs(_amount_in(stated) - estimate) <= abs(estimate) * Decimal(str(FIGURE_TOLERANCE))


def _amount_in(stated: str) -> Decimal:
    """The number inside `$1,200,000`.

    Total, with no failure to handle: only text the pattern above matched
    reaches here, and that is a digit followed by digits, commas and at most
    one decimal point - which is a `Decimal` once the grouping is dropped.
    """
    return Decimal(stated.removeprefix("$").strip().replace(",", ""))
