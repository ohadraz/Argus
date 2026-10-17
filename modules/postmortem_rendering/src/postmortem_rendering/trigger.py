"""What set it off: the change the confirmed cause blamed, the state it left,
the state it went to, when and by whom.

A flag's states are words and said in capitals; a deployment's are revisions,
said as written and cut as git cuts one, since a revision is an identifier and
not a word; and a change of no known kind says its states as they were written.
"""

from __future__ import annotations

from argus_core.models import Alert, ChangeKind, PostmortemDocument, Trigger
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import as_revision
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import a_reference


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
                 _a_state_of(trigger, trigger.from_state, Role.FROM_STATE, postmortem),
                 Run(text=" to "),
                 _a_state_of(trigger, trigger.to_state, Role.TO_STATE, postmortem)]
    elif noun:
        runs.append(Run(text=noun))

    if trigger.changed_at:
        runs += [Run(text=" at "), Run.a_moment(trigger.changed_at)]

    carrier = next((cited for cited in postmortem.changes_read
                    if cited.label == trigger.carried_by), None)
    if carrier is not None:
        # Whoever started the deploy, not whoever wrote the setting: the
        # deploy is the change the record holds.
        runs += [Run(text=", in the deploy of "),
                 a_reference(carrier.change, carrier.short_reference)]
        if trigger.actor:
            runs.append(Run(text=f" that {trigger.actor} started"))
    elif trigger.actor:
        runs.append(Run(text=f", by {trigger.actor}"))

    runs.append(Run(text="."))

    return TriggerSection(line=Line(runs=tuple(runs)),
                          suspected=trigger.suspected,
                          states_are_revisions=deployed,
                          absent=None)


def _a_state_of(trigger: Trigger,
                state: str | None,
                role: Role,
                postmortem: PostmortemDocument) -> Run:
    """One end of the trigger's move, playing `role`. A deployment's revision a
    change read names is said as that change's row says it - short, leading
    where it opens - so the document names one revision one way; any other
    state as `_a_state` says it."""
    read = next((cited for cited in postmortem.changes_read
                 if trigger.kind is ChangeKind.DEPLOY and state
                 and cited.change.reference == state), None)
    if read is not None:
        return a_reference(read.change, read.short_reference).model_copy(update={"role": role})

    return Run(text=_a_state(state, trigger.kind), role=role)


def _a_state(state: str | None, kind: ChangeKind | None) -> str:
    """A revision as git shows one, a flag's state in capitals, any other as
    written - a setting's `v2` is not `V2` - and a state nobody recorded as
    unknown."""
    if kind is ChangeKind.DEPLOY and state:
        return as_revision(state)

    said = state or "unknown"
    return said.upper() if kind is ChangeKind.FLAG_TOGGLE else said
