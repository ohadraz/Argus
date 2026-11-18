"""The mark a platform write is made under, and the claims made about it.

Shared by the four suites whose actions write to the deployment platform: each
hands its action a mark and asserts that every write the action asked of the
port carried it. How the mark lands on the written object is the adapter's, and
pinned in its own suite. And by the two suites that say which changes are
marked - the server's own, and the assembled one's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from argus_testkit import Assertion
from deployment_platform import Mark


def a_mark() -> Mark:
    """A mark for one action row, written at one moment."""
    return Mark(action_id="6f1c1d2e-0000-4000-8000-0000000000a1",
                written_at=datetime(2026, 11, 18, 13, 5, tzinfo=UTC))


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
