"""What one pass of the relay had to report.

Both of these compare an integer, and neither is `the_answer_was`: what a
reader of `.then(it_delivered(3))` needs is which integer it was. A relay that
delivered the right number of lines and left the cursor in the wrong place is
a different failure from the reverse, and a bare equality names neither.
"""

from __future__ import annotations

from argus_testkit import Assertion


def it_delivered(expected: int) -> Assertion[int]:
    """How many lines one pass reported having sent."""
    def assertion(delivered: int) -> bool:
        if delivered != expected:
            raise AssertionError(
                f"Expected {expected} lines to be delivered, it reported {delivered}."
            )

        return True

    return assertion


def the_place_is(expected: int) -> Assertion[int]:
    """Where the relay will start reading next time.

    The half that outlives the run: a pass that delivered correctly and then
    recorded the wrong place sends the same lines again on the next pass, and
    nothing about this pass's own answer would say so.
    """
    def assertion(place: int) -> bool:
        if place != expected:
            raise AssertionError(f"Expected the place {expected}, got {place}.")

        return True

    return assertion
