"""The mark a platform write is made under, and the claims made about it.

Shared by the four suites whose actions write to the deployment platform: each
hands its action a mark and asserts that every write the action asked of the
port carried it. How the mark lands on the written object is the adapter's, and
pinned in its own suite. And by the two suites that say which changes are
marked - the server's own, and the assembled one's.

The same four read a mark back: a write compares the claim an object is marked
with against its own before it writes, so each suite names this claim, another
one, and the objects a mark is read off. A mark read back is what the port
finds on the object - the claim, and the moment the mark says it was written,
where it says one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, overload

from argus_testkit import Assertion
from deployment_platform import Mark, MarkFound

# The claim a write in these suites is made for, as a marked object names it -
# the action row `a_mark()` marks every write with. Which object a mark is read
# off is the port's own `MarkedObject`.
THIS_CLAIM = "6f1c1d2e-0000-4000-8000-0000000000a1"
# Another action's claim - not this one - whose mark an object may carry from an
# earlier change of Argus's.
ANOTHER_CLAIM = "6f1c1d2e-0000-4000-8000-0000000000b2"
# When `a_mark()` says its write was made, by the tier's own clock - and so what
# an object it marked says when its mark is read back.
THE_MOMENT_A_MARK_SAYS = datetime(2026, 11, 18, 13, 5, tzinfo=UTC)


def a_mark() -> Mark:
    """A mark for one action row - `THIS_CLAIM` - written at one moment."""
    return Mark(action_id=THIS_CLAIM, written_at=THE_MOMENT_A_MARK_SAYS)


@overload
def a_mark_found(claim: str,
                 written_at: datetime | None = THE_MOMENT_A_MARK_SAYS) -> MarkFound: ...


@overload
def a_mark_found(claim: None,
                 written_at: datetime | None = THE_MOMENT_A_MARK_SAYS) -> None: ...


@overload
def a_mark_found(claim: str | None,
                 written_at: datetime | None = THE_MOMENT_A_MARK_SAYS) -> MarkFound | None: ...


def a_mark_found(claim: str | None,
                 written_at: datetime | None = THE_MOMENT_A_MARK_SAYS) -> MarkFound | None:
    """What an object `claim` marked carries when its mark is read back: the
    claim, and `written_at` - `THE_MOMENT_A_MARK_SAYS` unless a case names
    another, `None` for a mark whose moment is absent or unreadable. `None` for
    an object no claim marked."""
    if claim is None:
        return None

    return MarkFound(action_id=claim, written_at=written_at)


def every_write_carried(platform: Any, write: str, mark: Mark) -> Assertion[object]:
    """`write` was asked of `platform` at least once, and every time with `mark`
    as its last argument - where every port write that takes one takes it.

    Read off `call_args_list` rather than through `assert_called_with`, which
    does not survive a spec built from a `Protocol`: `self` is left on the
    signature.
    """
    def assertion(dont_care: object) -> bool:
        asked = [call.args for call in getattr(platform, write).call_args_list]
        unmarked = [args for args in asked if not args or args[-1] != mark]

        if not asked or unmarked:
            raise AssertionError(
                f"Expected every [{write}] asked of the platform under [{mark}], and it "
                f"was asked {asked}."
            )

        return True

    return assertion


def marked_are(expected: set[str]) -> Assertion[frozenset[str]]:
    """The changes registered as marked are `expected`, and no others."""
    def assertion(marked: frozenset[str]) -> bool:
        if set(marked) != expected:
            raise AssertionError(
                f"Expected {sorted(expected)} marked, got {sorted(marked)}."
            )

        return True

    return assertion
