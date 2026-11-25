"""Every flag-provider port, answered from memory.

Built from a `ProviderState` and changed by every write, so a write is read back
as the provider would read it back. Everything it says is what the port
promises and the port's suite pins over both adapters - so what Unleash does
that the port does not promise, it does not do either: it says every moment it
answers with to the second, as Unleash's `Date` header does, and tells Argus's
own changes from anybody's as the Unleash adapter does.

Two things held apart, as the port holds them apart: what the provider holds,
which `state_of` reads, and what evaluates, which `enabled` reads. A write
changes the first at once and, unless the seed says evaluation never follows,
the second with it - so the wait the Unleash adapter makes for evaluation to
agree is over before it starts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from core import to_iso
from core.models import FlagChange, FlagState, FlagUndo
from flag_provider import FlagProviderUnavailable, FlagWriteFailed

from flag_provider_double.state import ProviderState, RecordedToggle


class InMemoryFlagProvider:
    """A feature-flag provider held in memory.

    `argus_actor` is the name Argus is configured to recognise as its own -
    empty or `None` where none is, and then no change is told as Argus's or
    anybody else's, and whether anybody else changed a flag is not answered.
    `clock` is the provider's own: what every change is recorded at and every
    read and write is dated by. `unreachable` builds a provider nothing reaches,
    every call to which fails as never having been sent.
    """

    def __init__(self,
                 state: ProviderState,
                 *,
                 argus_actor: str | None,
                 clock: Callable[[], datetime],
                 unreachable: bool = False) -> None:
        self._environment = state.environment
        self._held = dict(state.flags)
        self._evaluating = dict(state.flags)
        self._history = list(state.history)
        self._signed_in_as = state.signed_in_as
        self._evaluation_follows = state.evaluation_follows
        self._argus_actor = argus_actor
        self._clock = clock
        self._unreachable = unreachable

    def enabled(self) -> list[str]:
        self._reached()

        return [flag for flag, on in self._evaluating.items() if on]

    def state_of(self, flag: str, /) -> FlagState:
        """Refused as unavailable for a flag the provider does not hold, as the
        Unleash adapter refuses one the provider answers 404 for."""
        self._reached()

        if flag not in self._held:
            raise FlagProviderUnavailable(f"the provider holds no flag [{flag}]")

        return FlagState(enabled=self._held[flag], read_at=self._now())

    def set(self, flag: str, enabled: bool, /) -> FlagUndo:
        """Recorded only where the flag moved: the provider stores a change of
        a flag's state and nothing for a write that left it as it was."""
        if self._unreachable:
            raise FlagWriteFailed("the provider is not reachable", known_not_applied=True)

        if flag not in self._held:
            raise FlagWriteFailed(f"the provider holds no flag [{flag}]", known_not_applied=True)

        if self._held[flag] != enabled:
            self._held[flag] = enabled
            self._history.append(RecordedToggle(flag=flag,
                                                enabled=enabled,
                                                occurred_at=self._clock(),
                                                actor=self._signed_in_as))

        undo = FlagUndo(flag=flag,
                        was_enabled=not enabled,
                        environment=self._environment,
                        written_at=self._now())

        if self._evaluation_follows:
            self._evaluating[flag] = enabled

        if self._evaluating[flag] != enabled:
            raise FlagWriteFailed(f"flag [{flag}] was taken but does not evaluate as set",
                                  left_behind=undo)

        return undo

    def changes_since(self, since: datetime, /) -> list[FlagChange]:
        self._reached()

        return [
            FlagChange(flag=toggle.flag,
                       enabled=toggle.enabled,
                       occurred_at=to_iso(toggle.occurred_at),
                       actor=toggle.actor,
                       made_by_argus=self._was_argus(toggle.actor))
            for toggle in self._history
            if toggle.occurred_at >= since
        ]

    def others_changed_since(self, flag: str, since: datetime, /) -> bool | None:
        """`None` where nobody can say, as the Unleash adapter says it: no name
        is configured as Argus's, or the history could not be read."""
        if not self._argus_actor:
            return None

        try:
            changes = self.changes_since(since)
        except FlagProviderUnavailable:
            return None

        return any(change.made_by_argus is False for change in changes if change.flag == flag)

    def _reached(self) -> None:
        if self._unreachable:
            raise FlagProviderUnavailable("the provider is not reachable")

    def _was_argus(self, actor: str) -> bool | None:
        """As the Unleash adapter tells it: without regard to case, and `None`
        where no name is configured."""
        if not self._argus_actor:
            return None

        return actor.casefold() == self._argus_actor.casefold()

    def _now(self) -> datetime:
        """The provider's clock, to the second, as its `Date` header says it."""
        return self._clock().astimezone(UTC).replace(microsecond=0)
