"""The claims made about what a resumed walk's reads found of a change.

Shared by the five suites whose change a walk resumed after its worker died asks
after - a flag, a rollback, a scale-out, an autoscaler pin and a pin to a card.
Each answers the same two questions in the same shapes, so the claims about them
are made once.

Whether a claimed change was made: made, with what puts it back and when; not
landed, saying what of the claim's is out there all the same - the suspension a
patch kind or a rollback makes before its change, where that stands - or
nothing; or refused as the write itself would refuse it on the same estate -
the read is the write's own rule without the write, so the one way to say it
agrees with the write is to ask the write.

Whether a performed change is still as Argus left it: still Argus's, somebody's
change since - saying what was found - or nobody can say, saying why.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from argus_testkit import Assertion
from core.models import ChangeFound, Made, NotMade, UndoDescriptor
from mcp_transport import ToolRefusalKind, ToolRefused


def it_was_made(descriptor: UndoDescriptor, made_at: datetime | None) -> Assertion[Any]:
    """Made, answered with `descriptor` and dated `made_at` - `None` where
    nothing says when."""
    def assertion(answered: Made[Any] | NotMade[Any]) -> bool:
        if not isinstance(answered, Made):
            raise AssertionError(
                f"Expected the change found made at [{made_at}] as {descriptor!r}, got "
                f"[{answered!r}]."
            )

        wrong = {
            field: (expected, getattr(answered, field))
            for field, expected in (("descriptor", descriptor), ("made_at", made_at))
            if getattr(answered, field) != expected
        }

        if wrong:
            raise AssertionError(
                f"Expected the change found made at [{made_at}] as {descriptor!r}, and "
                f"{wrong} differed (expected, got)."
            )

        return True

    return assertion


def nothing_landed(left_behind: UndoDescriptor | None = None) -> Assertion[Any]:
    """The claim's change is not out there, and the write is still to make -
    carrying `left_behind`, what of the claim's is out there all the same: the
    plan, where this claim's suspension stands, so a walk that stops before it
    writes still has what puts the suspension back. `None` where nothing of
    the claim's is out there at all."""
    def assertion(answered: Made[Any] | NotMade[Any]) -> bool:
        if not isinstance(answered, NotMade):
            raise AssertionError(
                f"Expected nothing found landed, leaving {left_behind!r} behind, got "
                f"[{answered!r}]."
            )

        if answered.left_behind != left_behind:
            raise AssertionError(
                f"Expected nothing found landed, leaving {left_behind!r} behind, and it "
                f"left {answered.left_behind!r}."
            )

        return True

    return assertion


def it_refused_as_the_write_does(write: Callable[[], object]) -> Assertion[Exception | None]:
    """The read refused, and `write` - asked on the same estate - refuses with the
    same type and in the same words: changed since, performed and what it left
    behind included."""
    def assertion(refused: Exception | None) -> bool:
        if refused is None:
            raise AssertionError("Expected the read refused as the write is, got an answer.")

        try:
            write()
        except Exception as by_the_write:
            if (type(by_the_write), _said(by_the_write)) != (type(refused), _said(refused)):
                raise AssertionError(
                    f"Expected the read refused as the write is, [{type(by_the_write).__name__}: "
                    f"{_said(by_the_write)!r}], got [{type(refused).__name__}: "
                    f"{_said(refused)!r}]."
                ) from None

            return True

        raise AssertionError(
            f"Expected the write refused as the read was, [{type(refused).__name__}: "
            f"{refused}], and the write answered."
        )

    return assertion


def it_is_not_said_changed_since() -> Assertion[Exception | None]:
    """Refused, and not as a change made since: a question nobody could answer
    is no evidence anybody acted."""
    def assertion(refused: Exception | None) -> bool:
        if refused is None:
            raise AssertionError(
                "Expected a refusal saying nobody can say, not changed since, got an answer."
            )

        if isinstance(refused, ToolRefused) and (
            refused.refusal.kind is ToolRefusalKind.CHANGED_SINCE
        ):
            raise AssertionError(
                f"Expected a refusal saying nobody can say, not changed since, got "
                f"{_said(refused)!r}."
            )

        return True

    return assertion


def it_is_still_argus_s() -> Assertion[ChangeFound]:
    """Still as Argus left it, with nothing of anybody else's found."""
    def assertion(found: ChangeFound) -> bool:
        if found.still_argus_s is not True or found.found is not None:
            raise AssertionError(
                f"Expected the change found still Argus's with nothing else found, got "
                f"[{found.still_argus_s}] finding [{found.found}]."
            )

        return True

    return assertion


def it_was_changed_since(*mentioning: str) -> Assertion[ChangeFound]:
    """Somebody's change since, saying what was found - naming each of
    `mentioning`."""
    def assertion(found: ChangeFound) -> bool:
        if found.still_argus_s is not False or found.found is None:
            raise AssertionError(
                f"Expected the change found changed since, saying what was found, got "
                f"[{found.still_argus_s}] finding [{found.found}]."
            )

        missing = [each for each in mentioning if each not in found.found]

        if missing:
            raise AssertionError(
                f"Expected what was found to name {list(mentioning)}, got [{found.found}]."
            )

        return True

    return assertion


def nobody_can_say(*mentioning: str) -> Assertion[ChangeFound]:
    """Neither still Argus's nor somebody's: the check could not be made, and
    says why - naming each of `mentioning`."""
    def assertion(found: ChangeFound) -> bool:
        if found.still_argus_s is not None or not found.found:
            raise AssertionError(
                f"Expected nobody able to say whose the change is, saying why, got "
                f"[{found.still_argus_s}] finding [{found.found}]."
            )

        missing = [each for each in mentioning if each not in found.found]

        if missing:
            raise AssertionError(
                f"Expected why nobody can say to name {list(mentioning)}, got [{found.found}]."
            )

        return True

    return assertion


def what_was_found_does_not_say(words: str) -> Assertion[ChangeFound]:
    """What was found is not said in `words` - a reading the estate does not
    bear."""
    def assertion(found: ChangeFound) -> bool:
        if found.found is not None and words in found.found:
            raise AssertionError(
                f"Expected what was found not to say [{words}], got [{found.found}]."
            )

        return True

    return assertion


def _said(refused: Exception) -> object:
    """What a refusal says: the whole of a write tool's refusal - its kind, its
    words, what it left behind and whether its change had landed - and the words
    of anything else."""
    return refused.refusal if isinstance(refused, ToolRefused) else str(refused)
