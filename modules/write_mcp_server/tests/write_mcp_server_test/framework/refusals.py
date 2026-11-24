"""What a write tool's refusal says, read as the server answers it.

Shared because every action that can change the estate refuses under one rule,
and each action's suite asserts which of its steps the rule was applied at. Read
off the refusal the tool raised - its kind, what it left behind and whether its
change had landed - which is what the server answers the call with whole, so
what is asserted is what a caller would be told rather than a sentence, which is
allowed to change.
"""

from __future__ import annotations

from argus_testkit import Assertion
from core.models import UndoDescriptor
from mcp_transport import ToolRefusal, ToolRefusalKind, ToolRefused


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
    """The refusal is of the changed-since kind.

    Its own kind because the walk does something different with each: a
    changed-since refusal escalates - somebody is acting on the service now, and
    Argus hands it to a person rather than act beside them - an exhausted one is
    spent, and an unreachable platform narrows every action through it.
    """
    return its_kind_is(ToolRefusalKind.CHANGED_SINCE)


def its_kind_is(expected: ToolRefusalKind) -> Assertion[object]:
    def assertion(raised: object) -> bool:
        refusal = _the_refusal_of(raised)

        if refusal.kind is not expected:
            raise AssertionError(
                f"Expected a [{expected}] refusal, and it was a [{refusal.kind}] one: "
                f"[{refusal.words}]."
            )

        return True

    return assertion


def its_change_is_said_performed(expected: bool) -> Assertion[object]:
    """Whether a changed-since refusal says this claim's own change - the value,
    under this claim's mark - had landed before somebody overtook it. The walk
    records the action performed where it had and not performed where it had not,
    and a suspension alone is not the change."""
    def assertion(raised: object) -> bool:
        refusal = _the_refusal_of(raised)

        if refusal.performed is not expected:
            raise AssertionError(
                f"Expected the refusal to say this claim's change "
                f"{'had' if expected else 'had not'} landed, and it said it "
                f"{'had' if refusal.performed else 'had not'}: [{refusal.words}]."
            )

        return True

    return assertion


def it_is_refused_as_unreachable(expected: bool) -> Assertion[object]:
    def assertion(raised: object) -> bool:
        refusal = _the_refusal_of(raised)
        unreachable = refusal.kind is ToolRefusalKind.PLATFORM_UNREACHABLE

        if unreachable is not expected:
            raise AssertionError(
                f"Expected the refusal {'' if expected else 'not '}to report a "
                f"platform that could not be reached, and it was a [{refusal.kind}] "
                f"one: [{refusal.words}]."
            )

        return True

    return assertion


def what_it_left_is_known(expected: bool) -> Assertion[object]:
    """Known for every refusal but one that cannot vouch for the estate."""
    def assertion(raised: object) -> bool:
        refusal = _the_refusal_of(raised)

        if refusal.left_behind_known is not expected:
            raise AssertionError(
                f"Expected the refusal to say what it left behind is "
                f"{'known' if expected else 'not known'}, and it was a [{refusal.kind}] "
                f"one: [{refusal.words}]."
            )

        return True

    return assertion


def it_left_behind(expected: UndoDescriptor | None) -> Assertion[object]:
    """Compared as a value: a descriptor that arrived with a field lost would put
    back something other than what was changed."""
    def assertion(raised: object) -> bool:
        carried = _the_refusal_of(raised).left_behind

        if carried != expected:
            raise AssertionError(
                f"Expected the refusal to carry {expected!r} as what it left "
                f"behind, and it carried {carried!r}: [{raised}]."
            )

        return True

    return assertion


def _the_refusal_of(raised: object) -> ToolRefusal:
    """The refusal a tool raised, or the refusal itself where one is answered
    rather than raised - as `a_platform_refusal` answers what a tool raises."""
    if isinstance(raised, ToolRefusal):
        return raised

    if not isinstance(raised, ToolRefused):
        raise AssertionError(f"Expected the action to be refused, and what was raised was "
                             f"{raised!r}.")

    return raised.refusal
