"""A level said as a person says it: to three figures, and never fewer than
its whole part has.

One rule in one place, because the postmortem's prose and its impact cards
each write the series a paging rule watches, and a level written two ways is
two figures to a reader comparing them.
"""

from __future__ import annotations

import pytest
from argus_core import said_as_a_level
from argus_testkit import Scenario, the_answer_was


@pytest.mark.unit
@pytest.mark.parametrize(("level", "said"), [
    (0.594083, "0.594"),
    (0.000123456, "0.000123"),
    (0.92, "0.92"),
    (1234.5, "1235"),
    (0.5943428571, "0.594"),
    (0.0, "0")
], ids=["a-ratio", "a-small-one", "already-short", "a-whole-number-and-a-half",
        "a-mean-of-several-minutes", "nothing"])
def test_a_level_is_said_to_three_figures_and_never_fewer_than_its_whole_part(
        level: float, said: str) -> None:
    # Six places of a ratio read as a precision nobody measured it to: three
    # figures are what a reader compares two levels by - and never fewer than
    # a whole number has, since "1230" reads as an exact count.
    Scenario() \
        .when(
            lambda: said_as_a_level(level)
        ) \
        .then(
            the_answer_was(said)
        )
