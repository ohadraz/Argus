"""The claims made about whether a put-back found the change somebody else's.

Shared by the four suites whose restores read the platform before they write:
a rollback, a scale-out, an autoscaler pin and a pin to a card. Each answers
with a type of its own, and all four say the same two things beside their own
halves - what was found where the change was left as somebody set it, and
whether the reconciliation Argus suspended still stands - so the claims about
those two are made once, over what the four have in common.
"""

from __future__ import annotations

from typing import Protocol

from argus_testkit import Assertion


class AnAnswerToAPutBack(Protocol):
    """What every restore of a change to a deployment says beside its own
    halves."""

    @property
    def left_because(self) -> str | None: ...

    @property
    def sync_still_suspended(self) -> bool: ...


def it_was_not_left_alone() -> Assertion[AnAnswerToAPutBack]:
    """Nothing of anybody else's was said to be found: the change was Argus's,
    or nobody could establish whose it was."""
    def assertion(restored: AnAnswerToAPutBack) -> bool:
        if restored.left_because is not None:
            raise AssertionError(
                f"Expected nothing of anybody else's found, and the restore left the "
                f"change because [{restored.left_because}]."
            )

        return True

    return assertion


def it_was_left_because(*mentioning: str) -> Assertion[AnAnswerToAPutBack]:
    """Left as somebody set it, saying what was found - naming each of
    `mentioning`."""
    def assertion(restored: AnAnswerToAPutBack) -> bool:
        if restored.left_because is None:
            raise AssertionError(
                f"Expected the change left as somebody set it, and the restore "
                f"reported {restored!r}."
            )

        missing = [each for each in mentioning if each not in restored.left_because]

        if missing:
            raise AssertionError(
                f"Expected what was found to name {list(mentioning)}, and it said "
                f"[{restored.left_because}]."
            )

        return True

    return assertion


def the_suspension_is_said_to_stand(expected: bool) -> Assertion[AnAnswerToAPutBack]:
    """Whether the restore said the reconciliation Argus suspended is still
    suspended - read off the platform where the change was left."""
    def assertion(restored: AnAnswerToAPutBack) -> bool:
        if restored.sync_still_suspended is not expected:
            raise AssertionError(
                f"Expected the sync Argus suspended said to be still suspended "
                f"[{expected}], got [{restored.sync_still_suspended}]."
            )

        return True

    return assertion
