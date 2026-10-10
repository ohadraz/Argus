"""What one pass of the relay had to report, and what a destination was told.

It compares an integer, and is not `the_answer_was`: what a reader of
`.then(it_said(3))` needs is which integer it was. A relay that said the right
number of lines and left the cursor in the wrong place is a different failure
from the reverse, and a bare equality names neither.
"""

from __future__ import annotations

from argus_testkit import Assertion

from agent_communicator_test.framework.builders import ADestination


def it_said(expected: int) -> Assertion[int]:
    """How many lines one pass reported having sent."""
    def assertion(said: int) -> bool:
        if said != expected:
            raise AssertionError(
                f"Expected {expected} lines to be said, it reported {said}."
            )

        return True

    return assertion


def the_lines_said_were(destination: ADestination, expected: list[str]) -> Assertion[object]:
    """Every line the destination was told, by kind, in the order it was told."""
    def assertion(_: object) -> bool:
        kinds = [line.kind for _, line, _ in destination.told]
        if kinds != expected:
            raise AssertionError(f"Expected the lines {expected}, got {kinds}.")

        return True

    return assertion
