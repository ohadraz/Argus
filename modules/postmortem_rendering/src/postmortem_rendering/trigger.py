"""What set it off: the change the confirmed cause blamed, the state it left,
the state it went to, when and by whom.

A flag's states are words and said in capitals; a deployment's are revisions,
said as written and cut as git cuts one, since a revision is an identifier and
not a word.
"""

from __future__ import annotations

from argus_core.models import Alert, ChangeKind, PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import as_revision
from postmortem_rendering.lines import Line, Role, Run


class TriggerSection(BaseModel):
    """The sentence, whether it is only suspected, and whether its states are
    revisions - for a destination that marks either - or the sentence said in
    its place where no trigger was established."""

    model_config = ConfigDict(frozen=True)

    line: Line | None
    suspected: bool
    states_are_revisions: bool
    absent: str | None


def the_trigger(postmortem: PostmortemDocument, alert: Alert) -> TriggerSection:
    """The trigger said as one sentence.

    Suspected where nothing tested it - the leading candidate's change, which
    an action only recommended would have confirmed or refuted - and said so
    first, so it is read before the change is. A deployment's subject is the
    service it went to.
    """
    trigger = postmortem.trigger
    if trigger is None:
        return TriggerSection(line=None, suspected=False, states_are_revisions=False,
                              absent="No trigger was established.")

    deployed = trigger.kind is ChangeKind.DEPLOY
    runs: list[Run] = []

    if trigger.suspected:
        runs += [Run(text="Suspected, not confirmed:", role=Role.STRONG), Run(text=" ")]

    subject = alert.service if deployed else trigger.subject
    noun = " flag" if trigger.kind is ChangeKind.FLAG_TOGGLE else ""
    runs.append(Run(text=subject, role=Role.CODE))

    if trigger.from_state or trigger.to_state:
        runs += [Run(text=f"{noun} {'was deployed' if deployed else 'went'} from "),
                 Run(text=_a_state(trigger.from_state, deployed), role=Role.FROM_STATE),
                 Run(text=" to "),
                 Run(text=_a_state(trigger.to_state, deployed), role=Role.TO_STATE)]
    elif noun:
        runs.append(Run(text=noun))

    if trigger.changed_at:
        runs += [Run(text=" at "), Run.a_moment(trigger.changed_at)]

    if trigger.actor:
        runs.append(Run(text=f", by {trigger.actor}"))

    runs.append(Run(text="."))

    return TriggerSection(line=Line(runs=tuple(runs)),
                          suspected=trigger.suspected,
                          states_are_revisions=deployed,
                          absent=None)


def _a_state(state: str | None, deployed: bool) -> str:
    """A revision as git shows one, a flag's state in capitals, and a state
    nobody recorded as unknown."""
    if deployed and state:
        return as_revision(state)

    return (state or "unknown").upper()
