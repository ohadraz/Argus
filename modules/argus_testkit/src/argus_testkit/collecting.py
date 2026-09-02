from __future__ import annotations

"""Keeping what a collaborator was handed, so a test can read it back.

The counterpart to `assertions.py`: that module says how a result is checked,
this one says how the thing to check is captured when the code under test
reports by calling somebody rather than by returning.

Deliberately knows nothing about what it collects. A publisher is handed
events, a recorder is handed replay entries, a notifier is handed messages, and
none of that is this module's business - which is what keeps `argus_testkit`
free of dependencies on the packages it is used to test.
"""


class Kept[T]:
    """A one-argument collaborator that remembers instead of doing.

    Passed as `kept.take` wherever a callable collaborator is expected. The
    method is separate from the collection so that handing it over does not
    hand over the list as well: a test reads `taken`, and the code under test
    only ever sees something it can call.

    `take` is positional-only, matching the seams it stands in for - a
    `Publisher` or a `Recorder` is called with one argument and nothing else,
    whatever the parameter happens to be named.
    """

    def __init__(self) -> None:
        self.taken: list[T] = []

    def take(self, item: T, /) -> None:
        self.taken.append(item)

    def only(self) -> T:
        """The single item taken, when a test means exactly one.

        Raises rather than returning the first, because "the collaborator was
        called once" is usually half of what a test is asserting - and a silent
        `[0]` would let a double-recorded call pass as a single one.
        """
        if len(self.taken) != 1:
            raise AssertionError(f"Expected exactly one item, got {len(self.taken)}.")

        return self.taken[0]
