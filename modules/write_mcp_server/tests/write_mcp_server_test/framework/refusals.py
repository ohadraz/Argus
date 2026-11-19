"""What a write tool's refusal says, read as the transport reads it.

Shared because every action that can change the estate refuses under one rule,
and each action's suite asserts which of its steps the rule was applied at. Read
off the words through the transport's own reading, so what is asserted is what a
caller would be told rather than the spelling of a marker.
"""

from __future__ import annotations

from argus_testkit import Assertion
from core.mcp_transport import (
    CHANGED_SINCE_MARKER,
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_KNOWN_MARKER,
    PERFORMED_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from core.models import UndoDescriptor


def it_was_refused_as(refusal: type[Exception]) -> Assertion[object]:
    def assertion(raised: object) -> bool:
        if not isinstance(raised, refusal):
            raise AssertionError(
                f"Expected the action to be refused with {refusal.__name__}, and "
                f"what was raised was {raised!r}."
            )

        return True

    return assertion


def it_was_refused_as_changed_since() -> Assertion[object]:
    """The refusal carries the changed-since marker, and neither of the others.

    Its own marker because the walk does something different with each: a
    changed-since refusal escalates - somebody is acting on the service now, and
    Argus hands it to a person rather than act beside them - an exhausted one is
    spent, and an unreachable platform narrows every action through it. Asserted
    against the marker rather than the sentence, which is allowed to change.
    """
    def assertion(raised: object) -> bool:
        said = str(raised)

        if raised is None or CHANGED_SINCE_MARKER not in said:
            raise AssertionError(
                f"Expected the refusal to carry [{CHANGED_SINCE_MARKER}], and it "
                f"said [{raised}]."
            )

        others = [marker for marker in (EXHAUSTED_ACTION_MARKER, UNREACHABLE_PLATFORM_MARKER)
                  if marker in said]

        if others:
            raise AssertionError(
                f"Expected a changed-since refusal to carry no other marker, and it "
                f"carried {others}: [{raised}]."
            )

        return True

    return assertion


def its_change_is_said_performed(expected: bool) -> Assertion[object]:
    """Whether a changed-since refusal says this claim's own change - the value,
    under this claim's mark - had landed before somebody overtook it. The walk
    records the action performed where it had and not performed where it had not,
    and a suspension alone is not the change."""
    def assertion(raised: object) -> bool:
        if (PERFORMED_MARKER in str(raised)) is not expected:
            raise AssertionError(
                f"Expected the refusal to say this claim's change "
                f"{'had' if expected else 'had not'} landed, and it said [{raised}]."
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
