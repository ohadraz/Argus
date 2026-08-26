from __future__ import annotations

from typing import Protocol

from argus_core.models.change_event import ChangeEvent


class ChangeSourceUnavailable(Exception):
    """The change source could not be asked what changed.

    Deliberately not an empty list. "The deploy API was down" and "nothing
    changed" are opposite facts, and a source that reports the first as the
    second lets an outage become evidence of absence - the Investigator would
    conclude "no change explains this" from having seen nothing at all, which
    is the confident-about-nothing failure one layer below where §9 fights it.
    """


class ChangeSource(Protocol):
    """What Argus needs from a system that records changes.

    A `Protocol` rather than a `Callable` alias because it is called with
    keywords, and because a test doubling it wants something introspectable.

    The window is the caller's, in wire format, and every implementation
    honours it identically - whether the vendor filters server-side or, like
    Argo CD, hands over an application's whole history and leaves the filtering
    to the adapter. Nothing above this line can tell which happened.
    """

    def __call__(
        self, application: str, *, window_start: str, window_end: str
    ) -> list[ChangeEvent]: ...
