"""The flag provider's recorded changes, each said as the move it was.

A change is shown as a transition rather than described as one, because that is
what the page can strike through: the state that is no longer true beside the
state that is. No colour on either - which direction is the bad one depends
entirely on the flag, and a page that reddened "on" would be asserting
something about `legacy-checkout-fallback` that is exactly backwards.
"""

from __future__ import annotations

from argus_core.models.flag_change import FlagChange
from pydantic import BaseModel

from argus_web.views.clock import a_moment


class FlagToggleRow(BaseModel):
    """One recorded flag change, as the page shows it.

    `moved` is the whole transition where the history contains the flag's
    previous state, and only the new one where it does not - a prior state
    invented to fill the arrow would be a guess about production. No colour on
    it: which direction is the bad one depends entirely on the flag, and a page
    that reddened "on" would be asserting something about `legacy-checkout-
    fallback` that is exactly backwards.
    """

    flag: str
    when: str
    # The state the flag left and the state it arrived in. Two fields rather
    # than one sentence, so the page can strike the state that is no longer
    # true - which is the difference between showing a change and describing
    # one.
    was: str
    now: str
    actor: str | None
    # Whether this is the newest recorded change to this flag. It is the row an
    # action points at: the change Mitigation chose to undo is by definition
    # the latest one, and a link to an older move would show a reader the wrong
    # reason for what Argus did.
    latest_for_flag: bool = False


def a_flag_history(toggles: list[FlagChange]) -> list[FlagToggleRow]:
    """The recorded toggles, each said as the move it was."""
    return _with_the_latest_marked([
        FlagToggleRow(
            flag=toggle.flag,
            when=a_moment(toggle.occurred_at),
            # The state before a change is the other one. Not an assumption
            # about production but the meaning of the record: the provider
            # writes one of these when a flag's state changes, so a flag that
            # arrived ON is a flag that was OFF.
            was=on_or_off(not toggle.enabled),
            now=on_or_off(toggle.enabled),
            actor=toggle.actor,
        )
        for toggle in toggles
    ])


def on_or_off(enabled: bool | None) -> str:
    """A flag's state, said the one way the whole page says it."""
    return "ON" if enabled else "OFF"


def _with_the_latest_marked(history: list[FlagToggleRow]) -> list[FlagToggleRow]:
    """The same history, with each flag's newest change marked as its own."""
    newest = {row.flag: index for index, row in enumerate(history)}

    return [
        row.model_copy(update={"latest_for_flag": newest[row.flag] == index})
        for index, row in enumerate(history)
    ]
