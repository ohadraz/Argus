"""What a write tool's refusal says, read as the transport reads it.

Shared because every action that can change the estate refuses under one rule,
and each action's suite asserts which of its steps the rule was applied at. Read
off the words through the transport's own reading, so what is asserted is what a
caller would be told rather than the spelling of a marker.
"""

from __future__ import annotations

from argus_core.mcp_transport import (
    LEFT_BEHIND_KNOWN_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from argus_core.models import UndoDescriptor
from argus_testkit import Assertion


def it_was_refused_as(refusal: type[Exception]) -> Assertion[object]:
    def assertion(raised: object) -> bool:
        if not isinstance(raised, refusal):
            raise AssertionError(
                f"Expected the action to be refused with {refusal.__name__}, and "
                f"what was raised was {raised!r}."
            )

        return True

    return assertion


def it_is_marked_unreachable(expected: bool) -> Assertion[object]:
    def assertion(raised: object) -> bool:
        if (UNREACHABLE_PLATFORM_MARKER in str(raised)) is not expected:
            raise AssertionError(
                f"Expected the refusal {'' if expected else 'not '}to report a "
                f"platform that could not be reached, and it said [{raised}]."
            )

        return True

    return assertion


def what_it_left_is_known(expected: bool) -> Assertion[object]:
    """Known where a marker says it: the unreachable platform's own, which
    promises it, or the ordinary refusal's."""
    def assertion(raised: object) -> bool:
        said = str(raised)
        known = LEFT_BEHIND_KNOWN_MARKER in said or UNREACHABLE_PLATFORM_MARKER in said

        if known is not expected:
            raise AssertionError(
                f"Expected the refusal to say what it left behind is "
                f"{'known' if expected else 'not known'}, and it said [{said}]."
            )

        return True

    return assertion


def it_left_behind(expected: UndoDescriptor | None) -> Assertion[object]:
    """Compared as a value: a descriptor that arrived with a field lost would put
    back something other than what was changed."""
    def assertion(raised: object) -> bool:
        carried = what_was_left_behind(str(raised))

        if carried != expected:
            raise AssertionError(
                f"Expected the refusal to carry {expected!r} as what it left "
                f"behind, and it carried {carried!r}: [{raised}]."
            )

        return True

    return assertion
